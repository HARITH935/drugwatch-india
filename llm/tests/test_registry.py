"""Step 6's registry, exercised for real: `pytest -m model`, needs MLflow up and a registered
version at the "production" alias (run `publish_run.py` or its `--register-existing` mode
first). Everything else about this module is either MLflow's own behaviour (nothing to unit
test) or exercised by actually running `fallback.py`/`evaluate.py` against the stack.
"""

import pytest

from drugwatch_llm.prompting import build_prompt, parse_reply
from drugwatch_llm.zero_shot import device_for, generate


@pytest.mark.model
def test_the_registered_adapter_loads_and_answers(mlflow_available):
    from drugwatch_llm import registry

    device = device_for()
    loaded = registry.load(device)
    assert loaded.name == "drugwatch-extraction-fallback"
    assert loaded.version
    assert loaded.base_model_id  # came from the version's own tag, not a hardcoded guess

    reply = generate(loaded.model, loaded.tokenizer, build_prompt("Batch No: TB-1201", "B"), device)
    assert parse_reply(reply, "B") is not None  # the registered adapter still follows the schema
