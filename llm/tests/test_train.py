"""train()'s own bookkeeping - step counting, gradient-accumulation math, loss averaging -
exercised with a fake model, not Qwen. No GPU, no download: this is about the loop's arithmetic
being right, which a real model would only make slower to check, not more informative to check."""

import torch
from torch.utils.data import DataLoader, Dataset

from drugwatch_llm.train import train


class _FixedLossModel(torch.nn.Module):
    """Returns a known, decreasing loss from a single trainable scalar, so the test can assert
    on exact call counts and on the optimizer actually having moved the parameter."""

    def __init__(self):
        super().__init__()
        self.weight = torch.nn.Parameter(torch.tensor(1.0))
        self.calls = 0

    def forward(self, **batch):
        self.calls += 1
        loss = self.weight * self.weight  # a real, differentiable scalar loss
        return type("Output", (), {"loss": loss})()


class _RowDataset(Dataset):
    def __init__(self, n: int):
        self.n = n

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, index: int) -> dict:
        return {"input_ids": torch.tensor([1, 2, 3])}


def _loader(n: int) -> DataLoader:
    return DataLoader(_RowDataset(n), batch_size=1, collate_fn=lambda batch: batch[0])


def test_total_micro_batches_is_examples_times_epochs():
    model = _FixedLossModel()
    result = train(model, _loader(10), device="cpu", epochs=1, grad_accum=8, lr=0.01, log_every=5)
    assert result["micro_batches"] == 10
    assert model.calls == 10


def test_fractional_epochs_truncate_rather_than_round():
    model = _FixedLossModel()
    result = train(
        model, _loader(10), device="cpu", epochs=0.25, grad_accum=1, lr=0.01, log_every=5
    )
    assert result["micro_batches"] == 2  # int(10 * 0.25) == 2, not 3


def test_the_optimizer_actually_moves_the_parameter():
    model = _FixedLossModel()
    before = model.weight.item()
    train(model, _loader(5), device="cpu", epochs=1, grad_accum=1, lr=0.1, log_every=5)
    after = model.weight.item()
    assert after != before  # a real step happened, not just a forward pass


def test_more_than_one_epoch_revisits_the_dataset():
    model = _FixedLossModel()
    result = train(model, _loader(4), device="cpu", epochs=2.0, grad_accum=1, lr=0.01, log_every=5)
    assert result["micro_batches"] == 8  # 4 examples x 2 epochs, looping the loader again
    assert model.calls == 8
