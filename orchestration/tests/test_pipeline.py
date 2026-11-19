"""The backfill's month arithmetic, and the guards that stop a typo becoming a CDSCO hammering."""

import pytest

from drugwatch_orchestration.pipeline import (
    MAX_MONTHS,
    PORTAL_FIRST_MONTH,
    month_arguments,
    months_in_range,
)


def test_one_month_is_itself():
    assert months_in_range("2025-06", "2025-06") == ["2025-06"]


def test_a_range_inside_one_year():
    assert months_in_range("2025-06", "2025-09") == ["2025-06", "2025-07", "2025-08", "2025-09"]


def test_a_range_crossing_a_year_boundary():
    # December to January is the arithmetic that an off-by-one gets wrong
    assert months_in_range("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]


def test_a_whole_year_is_twelve_months():
    months = months_in_range("2023-01", "2023-12")
    assert len(months) == 12
    assert months[0] == "2023-01" and months[-1] == "2023-12"


def test_several_years():
    months = months_in_range("2019-01", "2026-09")
    assert len(months) == (2026 - 2019) * 12 + 9
    assert "2019-12" in months and "2020-01" in months  # no month skipped at the boundary


@pytest.mark.parametrize("bad", ["2025-13", "2025-00", "2025-1", "25-01", "2025/01", "", "june"])
def test_a_month_that_is_not_a_month_is_refused(bad):
    with pytest.raises(ValueError, match="must look like"):
        months_in_range(bad, "2025-06")


def test_a_backwards_range_is_refused():
    # Silently returning [] would make the backfill look like it worked and fetch nothing
    with pytest.raises(ValueError, match="before"):
        months_in_range("2025-06", "2025-01")


def test_months_before_the_portal_existed_are_refused_with_an_explanation():
    with pytest.raises(ValueError, match="only as PDFs"):
        months_in_range("2018-05", "2019-06")


def test_the_portal_first_month_itself_is_allowed():
    assert months_in_range(PORTAL_FIRST_MONTH, PORTAL_FIRST_MONTH) == [PORTAL_FIRST_MONTH]


def test_an_absurd_range_is_refused():
    with pytest.raises(ValueError, match=f"{MAX_MONTHS}-month limit"):
        months_in_range("2019-01", "2099-12")


def test_month_arguments_are_what_the_downloader_expects():
    # The flag is repeatable (action="append"), so each month gets its own --month
    assert (
        month_arguments("2025-05", "2025-07") == "--month 2025-05 --month 2025-06 --month 2025-07"
    )


def test_month_arguments_validate_too():
    """The macro is rendered before any request is made, so this is where a typo must stop."""
    with pytest.raises(ValueError):
        month_arguments("2025-99", "2025-99")
