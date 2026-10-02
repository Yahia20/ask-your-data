from datetime import date
from decimal import Decimal

from ask_data.compare import agree, majority, matches


def test_order_names_extra_columns_and_rounding_do_not_matter():
    expected = [("أحمد", 81.4721), ("سارة", 85.3108)]
    got = [(85.31, "سارة", 120), (81.47, "أحمد", 98)]
    assert matches(expected, got)


def test_a_wrong_value_fails():
    assert not matches([("أحمد", 81.47)], [("أحمد", 79.0)])


def test_labels_must_stay_with_their_values():
    assert not matches([("أحمد", 81.0), ("سارة", 85.0)], [("أحمد", 85.0), ("سارة", 81.0)])


def test_ratio_and_percentage_are_the_same_answer():
    assert matches([(19.39,)], [(0.1939,)])


def test_minutes_and_seconds_are_not():
    assert not matches([(12.4,)], [(744.0,)])


def test_two_columns_or_two_rows_for_a_comparison():
    assert matches([(1475, 2179)], [("2026-08", 2179), ("2026-09", 1475)])


def test_month_labels_in_different_types():
    assert matches([(date(2026, 7, 1), Decimal("807910.00"))], [("2026-07", 807910.0)])


def test_dumping_a_whole_table_is_not_an_answer():
    assert not matches([(18,)], [(i,) for i in range(100)])


def test_majority_needs_agreement():
    a, b, c = [(10,)], [(10.0,)], [(11,)]
    assert agree(a, b)
    assert majority([a, b, c]) == (0, 2)
    assert majority([a, c, None])[1] == 1
