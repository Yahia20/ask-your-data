"""Decide whether two query results say the same thing.

Used twice: to see whether independent SQL attempts agree (voting), and to grade
an answer against the expected one. Column names, column order, row order,
extra columns and rounding to 1-2 decimals don't matter; the values do.
"""
from __future__ import annotations

import itertools
import math
import re
from datetime import date, datetime
from decimal import Decimal

_MONTH = re.compile(r"^\d{4}-\d{2}$")


def norm(v):
    if v is None:
        return None
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):   # numpy scalars
        v = v.item()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return float(v)
    if isinstance(v, float):
        return None if math.isnan(v) else v
    if isinstance(v, datetime):
        return v.date().isoformat() if (v.hour, v.minute, v.second) == (0, 0, 0) else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    if _MONTH.match(s):
        return s + "-01"
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]00:00:00", s):
        return s[:10]
    return s


def same_value(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        for x in (a, a * 100, a / 100):           # 0.194 and 19.4% are the same answer
            if abs(x - b) <= max(0.051, abs(b) * 5e-4):
                return True
        return False
    return a == b


def _sort_key(v):
    return (0, "") if v is None else (1, v) if isinstance(v, float) else (2, str(v))


def _same_column(a: list, b: list) -> bool:
    return len(a) == len(b) and all(same_value(x, y) for x, y in zip(sorted(a, key=_sort_key), sorted(b, key=_sort_key)))


def matches(expected: list[tuple], got: list[tuple]) -> bool:
    """Every expected column appears in `got`, row for row. Extra columns in `got` are fine."""
    exp = [tuple(norm(v) for v in r) for r in expected]
    out = [tuple(norm(v) for v in r) for r in got]
    if not exp:
        return not out
    if len(exp) == len(out) and out:
        ecols, ocols = list(zip(*exp)), list(zip(*out))
        candidates = [[j for j, oc in enumerate(ocols) if _same_column(list(ec), list(oc))] for ec in ecols]
        if all(candidates):
            for pick in itertools.islice(itertools.product(*candidates), 200):
                proj = sorted((tuple(r[j] for j in pick) for r in out), key=lambda r: [_sort_key(v) for v in r])
                want = sorted(exp, key=lambda r: [_sort_key(v) for v in r])
                if all(all(same_value(x, y) for x, y in zip(p, w)) for p, w in zip(proj, want)):
                    return True
    # the same numbers laid out differently (two months as two rows instead of two columns).
    # Only when the shapes differ: with equal row counts, rows must line up as checked above.
    if len(exp) == len(out):
        return False
    eflat = [v for r in exp for v in r]
    oflat = [v for r in out for v in r]
    if len(oflat) > 2 * len(eflat) + 2:
        return False
    pool = list(oflat)
    for v in eflat:
        hit = next((i for i, o in enumerate(pool) if same_value(v, o)), None)
        if hit is None:
            return False
        pool.pop(hit)
    return True


def agree(a: list[tuple], b: list[tuple]) -> bool:
    return matches(a, b) and matches(b, a)


def majority(results: list[list[tuple] | None]) -> tuple[int | None, int]:
    """Index of a result in the largest agreeing group, and that group's size."""
    best, size = None, 0
    for i, r in enumerate(results):
        if r is None:
            continue
        n = sum(1 for other in results if other is not None and agree(r, other))
        if n > size:
            best, size = i, n
    return best, size

