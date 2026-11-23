"""Tokenization and loss-masking. Marked `model`: needs the real Qwen tokenizer from the Hugging
Face Hub (not weights - a tokenizer is a few MB and fast - but it still needs network, which is
exactly what the `model` marker exists to let CI skip)."""

import pytest
import torch

from drugwatch_llm.dataset import JSONExtractionDataset, collate, target_json, tokenize_example

MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"


def test_target_json_orders_fields_consistently_regardless_of_input_order():
    fields = {"failure_reason": "Assay", "batch_no": "Y", "product_name": "X"}
    first = target_json(fields, "B")
    second = target_json({"product_name": "X", "batch_no": "Y", "failure_reason": "Assay"}, "B")
    assert first == second  # same family, same field order, however the dict was built


def test_target_json_only_includes_this_familys_fields():
    # Family F has no failure_reason at all (docs/extraction-report.md §2.9).
    assert "failure_reason" not in target_json({"product_name": "X"}, "F")


@pytest.mark.model
class TestWithRealTokenizer:
    @pytest.fixture(scope="class")
    @classmethod
    def tokenizer(cls):
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(MODEL_ID)

    def test_the_prompt_tokens_are_all_masked_and_the_answer_tokens_are_not(self, tokenizer):
        example = {
            "text": "some jumbled row text",
            "family": "B",
            "fields": {
                "product_name": "X",
                "batch_no": "Y",
                "mfg_date": "09/2024",
                "expiry_date": "08/2026",
                "manufacturer": "Z",
                "failure_reason": "Assay",
            },
        }
        encoded = tokenize_example(tokenizer, example)
        assert len(encoded["input_ids"]) == len(encoded["labels"])

        # The prompt prefix is masked...
        num_masked = sum(1 for label in encoded["labels"] if label == -100)
        assert num_masked > 0
        assert encoded["labels"][:num_masked] == [-100] * num_masked
        # ...and the answer's own tokens are real ids, matching input_ids exactly (labels ==
        # input_ids over the answer span is what "predict this" means).
        assert encoded["labels"][num_masked:] == encoded["input_ids"][num_masked:]

    def test_the_model_is_taught_to_stop(self, tokenizer):
        example = {
            "text": "x",
            "family": "F",  # no failure_reason: the shortest possible answer
            "fields": {
                "product_name": "",
                "batch_no": "",
                "mfg_date": "",
                "expiry_date": "",
                "manufacturer": "",
            },  # fmt: skip
        }
        encoded = tokenize_example(tokenizer, example)
        assert encoded["input_ids"][-1] == tokenizer.eos_token_id
        assert encoded["labels"][-1] == tokenizer.eos_token_id  # not masked: stopping is learned

    def test_a_too_long_example_is_dropped_not_truncated(self, tokenizer):
        examples = [
            {
                "text": "word " * 5000,  # guaranteed to exceed any reasonable max_length
                "family": "B",
                "fields": {
                    "product_name": "X",
                    "batch_no": "Y",
                    "mfg_date": "09/2024",
                    "expiry_date": "08/2026",
                    "manufacturer": "Z",
                    "failure_reason": "Assay",
                },  # fmt: skip
            }
        ]
        dataset = JSONExtractionDataset(examples, tokenizer, max_length=64)
        assert len(dataset) == 0
        assert dataset.dropped == 1

    def test_collate_pads_the_shorter_row_and_masks_its_padding(self, tokenizer):
        short = {"input_ids": torch.tensor([1, 2, 3]), "labels": torch.tensor([-100, -100, 3])}
        long = {
            "input_ids": torch.tensor([1, 2, 3, 4, 5]),
            "labels": torch.tensor([-100, -100, -100, 4, 5]),
        }
        batch = collate([short, long], pad_token_id=0)
        assert batch["input_ids"].shape == (2, 5)
        assert batch["input_ids"][0].tolist() == [1, 2, 3, 0, 0]
        assert batch["labels"][0].tolist() == [-100, -100, 3, -100, -100]
        assert batch["attention_mask"][0].tolist() == [1, 1, 1, 0, 0]
