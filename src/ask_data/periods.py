"""Turn a period the model named ("last_month", "ramadan_2026") into exact dates.

The model is bad at calendar arithmetic and good at recognising "الشهر اللي فات",
so it only ever names the period and this module does the counting.
All ranges are inclusive dates in the business timezone.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, model_validator

PeriodKind = Literal[
    "today", "yesterday", "this_week", "last_week", "this_month", "last_month",
    "this_quarter", "last_quarter", "this_year", "last_year",
    "last_n_days", "last_n_weeks", "last_n_months",
    "month", "quarter", "year", "range", "named", "all_time",
]


class Period(BaseModel):
    kind: PeriodKind
    n: int | None = None              # last_n_*
    year: int | None = None           # month / quarter / year
    month: int | None = None          # month
    quarter: int | None = None        # quarter
    start: date | None = None         # range
    end: date | None = None           # range
    name: str | None = None           # named

    @model_validator(mode="after")
    def _needs(self):
        need = {"last_n_days": ["n"], "last_n_weeks": ["n"], "last_n_months": ["n"], "month": ["month"],
                "quarter": ["quarter"], "year": ["year"], "range": ["start", "end"], "named": ["name"]}
        missing = [f for f in need.get(self.kind, []) if getattr(self, f) is None]
        if missing:
            raise ValueError(f"period kind '{self.kind}' needs {missing}")
        return self


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date            # inclusive
    label_ar: str
    label_en: str
    unit: str | None = None   # 'day' | 'week' | 'month' | 'quarter' | 'year' when it is one calendar unit

    @property
    def end_exclusive(self) -> date:
        return self.end + timedelta(days=1)

    def previous(self) -> DateRange:
        """The comparable period just before: the whole previous calendar unit, or the same length."""
        s = self.start
        if self.unit == "day":
            p = s - timedelta(days=1)
            return DateRange(p, p, "اليوم السابق", "previous day", "day")
        if self.unit == "week":
            return DateRange(s - timedelta(days=7), s - timedelta(days=1), "الأسبوع السابق", "previous week", "week")
        if self.unit in ("month", "quarter"):
            k = 1 if self.unit == "month" else 3
            ps = _add_months(s, -k)
            label = ("الشهر السابق", "previous month") if k == 1 else ("الربع السابق", "previous quarter")
            return DateRange(ps, s - timedelta(days=1), *label, self.unit)
        if self.unit == "year":
            return DateRange(date(s.year - 1, 1, 1), date(s.year - 1, 12, 31), "العام السابق", "previous year", "year")
        length = (self.end - s).days + 1
        return DateRange(s - timedelta(days=length), s - timedelta(days=1), "الفترة السابقة", "previous period")


def _add_months(d: date, k: int) -> date:
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, 1)


def _month_end(d: date) -> date:
    return _add_months(date(d.year, d.month, 1), 1) - timedelta(days=1)


def _week_start(d: date) -> date:          # weeks start on Sunday
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _latest_year(today: date, month: int) -> int:
    """'August' with no year means the most recent August that has started."""
    return today.year if month <= today.month else today.year - 1


AR_MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def resolve(p: Period | None, today: date, named: dict) -> DateRange | None:
    """None = no time filter (all time)."""
    if p is None or p.kind == "all_time":
        return None
    t = today
    k = p.kind
    if k == "today":
        return DateRange(t, t, "اليوم", "today", "day")
    if k == "yesterday":
        y = t - timedelta(days=1)
        return DateRange(y, y, "أمس", "yesterday", "day")
    if k == "this_week":
        return DateRange(_week_start(t), t, "هذا الأسبوع", "this week", "week")
    if k == "last_week":
        s = _week_start(t) - timedelta(days=7)
        return DateRange(s, s + timedelta(days=6), "الأسبوع الماضي", "last week", "week")
    if k == "this_month":
        return DateRange(date(t.year, t.month, 1), t, "هذا الشهر", "this month", "month")
    if k == "last_month":
        s = _add_months(date(t.year, t.month, 1), -1)
        return DateRange(s, _month_end(s), "الشهر الماضي", "last month", "month")
    if k in ("this_quarter", "last_quarter"):
        qs = date(t.year, 3 * ((t.month - 1) // 3) + 1, 1)
        if k == "this_quarter":
            return DateRange(qs, t, "هذا الربع", "this quarter", "quarter")
        s = _add_months(qs, -3)
        return DateRange(s, qs - timedelta(days=1), "الربع الماضي", "last quarter", "quarter")
    if k == "this_year":
        return DateRange(date(t.year, 1, 1), t, "هذا العام", "this year", "year")
    if k == "last_year":
        return DateRange(date(t.year - 1, 1, 1), date(t.year - 1, 12, 31), "العام الماضي", "last year", "year")
    if k == "last_n_days":
        return DateRange(t - timedelta(days=p.n - 1), t, f"آخر {p.n} أيام", f"last {p.n} days")
    if k == "last_n_weeks":
        return DateRange(t - timedelta(days=7 * p.n - 1), t, f"آخر {p.n} أسابيع", f"last {p.n} weeks")
    if k == "last_n_months":       # full calendar months before the current one
        cur = date(t.year, t.month, 1)
        return DateRange(_add_months(cur, -p.n), cur - timedelta(days=1), f"آخر {p.n} أشهر", f"last {p.n} months")
    if k == "month":
        y = p.year or _latest_year(t, p.month)
        s = date(y, p.month, 1)
        return DateRange(s, min(_month_end(s), t), f"{AR_MONTHS[p.month - 1]} {y}", s.strftime("%B %Y"), "month")
    if k == "quarter":
        y = p.year or (t.year if 3 * (p.quarter - 1) + 1 <= t.month else t.year - 1)
        s = date(y, 3 * (p.quarter - 1) + 1, 1)
        return DateRange(s, min(_add_months(s, 3) - timedelta(days=1), t), f"الربع {p.quarter} من {y}", f"Q{p.quarter} {y}", "quarter")
    if k == "year":
        return DateRange(date(p.year, 1, 1), min(date(p.year, 12, 31), t), f"عام {p.year}", str(p.year), "year")
    if k == "range":
        return DateRange(p.start, p.end, f"من {p.start} إلى {p.end}", f"{p.start} to {p.end}")
    if k == "named":
        if p.name not in named:
            raise ValueError(f"unknown named period '{p.name}'. Known: {sorted(named)}")
        n = named[p.name]
        return DateRange(n["start"], n["end"], n["label"]["ar"], n["label"]["en"])
    raise ValueError(f"unhandled period kind {k}")
