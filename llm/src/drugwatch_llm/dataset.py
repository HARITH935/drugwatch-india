"""Turns a training example into tokens the model actually learns from.

The SAME prompt format as step 2's zero-shot comparison (`prompting.build_prompt`) - a model
fine-tuned on one prompt shape and evaluated zero-shot on another would not really be the model
being tested, and this phase already leaned on that once (ADR 0019's amendment compares all three
candidates on one shared prompt).

LOSS MASKING: the model is only trained to predict the JSON answer, not to predict the row's own
text back at itself. Concretely: tokenize the prompt and the target answer, then label every
prompt token with -100 (the value `CrossEntropyLoss` ignores) and every answer token with its real
id. Without this, the model would spend most of its gradient "learning" to reproduce whatever
jumbled row text appears in the prompt - the one thing it must never need to invent, since it is
already given.

The target's fields are serialised in the SAME order every time (`expected_fields`), so the model
sees one consistent JSON shape to produce rather than a shuffled one that makes the task harder
than it needs to be for no reason.
"""

import json
from typing import Any

import torch
from torch.utils.data import Dataset

from drugwatch_llm.prompting import build_prompt, expected_fields


def target_json(fields: dict[str, str], family: str) -> str:
    ordered = {name: fields.get(name, "") for name in expected_fields(family)}
    return json.dumps(ordered, ensure_ascii=False)


def tokenize_example(tokenizer: Any, example: dict[str, Any]) -> dict[str, list[int]]:
    """input_ids and labels for one example, labels -100 over the prompt tokens."""
    prompt = build_prompt(example["text"], example["family"])
    # apply_chat_template(tokenize=True) returns a BatchEncoding (like step 2's generate() call),
    # not a bare list - ["input_ids"] is needed even with no return_tensors given.
    prompt_ids = tokenizer.apply_chat_template(
        [{"role": "user", "content": prompt}], add_generation_prompt=True, tokenize=True
    )["input_ids"]
    answer = target_json(example["fields"], example["family"])
    # add_special_tokens=False: the chat template already added the turn's special tokens; adding
    # them again here would insert a second BOS/EOS in the middle of the sequence.
    answer_ids = tokenizer(answer, add_special_tokens=False)["input_ids"]
    answer_ids = [*answer_ids, tokenizer.eos_token_id]  # the model must learn where to STOP
    return {
        "input_ids": prompt_ids + answer_ids,
        "labels": [-100] * len(prompt_ids) + answer_ids,
    }


class JSONExtractionDataset(Dataset):
    """A torch Dataset over pre-tokenized examples. Tokenizing once up front (not per epoch)
    keeps every epoch's cost to the model itself, not to re-running the tokenizer and the chat
    template on 737 rows every time."""

    def __init__(self, examples: list[dict[str, Any]], tokenizer: Any, max_length: int):
        self.tokenized = []
        dropped = 0
        for example in examples:
            encoded = tokenize_example(tokenizer, example)
            if len(encoded["input_ids"]) > max_length:
                # Truncating a label-masked sequence risks cutting into the answer itself and
                # silently training on a half-built one; dropping the row is the honest choice.
                dropped += 1
                continue
            self.tokenized.append(encoded)
        self.dropped = dropped

    def __len__(self) -> int:
        return len(self.tokenized)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        item = self.tokenized[index]
        return {
            "input_ids": torch.tensor(item["input_ids"], dtype=torch.long),
            "labels": torch.tensor(item["labels"], dtype=torch.long),
        }


def collate(batch: list[dict[str, torch.Tensor]], pad_token_id: int) -> dict[str, torch.Tensor]:
    """Right-pads a batch to its longest sequence. Padding tokens are labelled -100 (never scored)
    and masked out of attention, so a shorter row in the same batch costs it nothing."""
    max_length = max(item["input_ids"].shape[0] for item in batch)
    input_ids, labels, attention_mask = [], [], []
    for item in batch:
        pad_length = max_length - item["input_ids"].shape[0]
        input_ids.append(torch.cat([item["input_ids"], torch.full((pad_length,), pad_token_id)]))
        labels.append(torch.cat([item["labels"], torch.full((pad_length,), -100)]))
        attention_mask.append(
            torch.cat([torch.ones_like(item["input_ids"]), torch.zeros(pad_length)])
        )
    return {
        "input_ids": torch.stack(input_ids),
        "labels": torch.stack(labels),
        "attention_mask": torch.stack(attention_mask).long(),
    }
