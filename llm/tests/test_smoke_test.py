"""No model needed. Runs in CI on every push.

Exists because the memory reading in smoke_test.py was wrong once already: `ru_maxrss`'s unit
depends on the operating system, not on how big the number looks, and the first version of
`peak_rss_mb` guessed from the number's size instead of asking the platform.
"""

from unittest import mock

from drugwatch_llm import smoke_test


def test_peak_rss_mb_treats_darwin_as_bytes():
    with mock.patch("drugwatch_llm.smoke_test._BYTES_PER_UNIT", 1):
        with mock.patch(
            "drugwatch_llm.smoke_test.resource.getrusage",
            return_value=mock.Mock(ru_maxrss=500 * 1024 * 1024),  # 500 MB, in bytes
        ):
            assert smoke_test.peak_rss_mb() == 500.0


def test_peak_rss_mb_treats_linux_as_kibibytes():
    with mock.patch("drugwatch_llm.smoke_test._BYTES_PER_UNIT", 1024):
        with mock.patch(
            "drugwatch_llm.smoke_test.resource.getrusage",
            return_value=mock.Mock(ru_maxrss=500 * 1024),  # 500 MB, in KiB
        ):
            assert smoke_test.peak_rss_mb() == 500.0


def test_candidate_model_is_declared_apache_2_0_licensed_in_its_own_comment():
    # Not a guarantee - the real check is reading the model's Hugging Face page (done for this
    # one, 2026-11-22) - but a model swapped in later without updating this constant's neighbour
    # comment is a reviewer's first clue that the check was skipped.
    assert smoke_test.CANDIDATE_MODEL == "Qwen/Qwen2.5-0.5B-Instruct"
