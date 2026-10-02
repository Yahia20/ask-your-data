from datetime import date

import pytest

from ask_data.periods import Period, resolve

TODAY = date(2026, 10, 2)   # a Friday
NAMED = {"ramadan_2026": {"start": date(2026, 2, 18), "end": date(2026, 3, 19), "label": {"ar": "رمضان", "en": "Ramadan"}}}


def r(**kw):
    return resolve(Period(**kw), TODAY, NAMED)


def test_last_month_is_the_whole_previous_calendar_month():
    p = r(kind="last_month")
    assert (p.start, p.end) == (date(2026, 9, 1), date(2026, 9, 30))


def test_weeks_start_on_sunday():
    assert r(kind="this_week").start == date(2026, 9, 27)
    p = r(kind="last_week")
    assert (p.start, p.end) == (date(2026, 9, 20), date(2026, 9, 26))


def test_last_n_months_means_full_months_before_this_one():
    p = r(kind="last_n_months", n=3)
    assert (p.start, p.end) == (date(2026, 7, 1), date(2026, 9, 30))


def test_a_month_without_a_year_is_the_latest_one_that_started():
    assert r(kind="month", month=8).start == date(2026, 8, 1)
    assert r(kind="month", month=12).start == date(2025, 12, 1)


def test_named_period_and_unknown_name():
    assert r(kind="named", name="ramadan_2026").end == date(2026, 3, 19)
    with pytest.raises(ValueError):
        r(kind="named", name="hajj_1999")


def test_previous_of_a_partial_month_is_the_whole_month_before():
    prev = r(kind="this_month").previous()
    assert (prev.start, prev.end) == (date(2026, 9, 1), date(2026, 9, 30))


def test_previous_quarter():
    prev = r(kind="quarter", quarter=3).previous()
    assert (prev.start, prev.end) == (date(2026, 4, 1), date(2026, 6, 30))


def test_all_time_means_no_filter():
    assert resolve(None, TODAY, NAMED) is None
    assert r(kind="all_time") is None


def test_missing_fields_are_rejected():
    with pytest.raises(ValueError):
        Period(kind="last_n_days")
