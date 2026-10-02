"""Refuse any SQL that is not a single read-only SELECT over the allowed tables.

The database user should be read-only anyway. This is the second lock: it
stops a bad query before it reaches the database at all.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command,
             exp.Merge, exp.Copy, exp.Grant, exp.TruncateTable, exp.Set, exp.Transaction)
CLOCK_FUNCTIONS = ("now", "current_date", "current_timestamp", "localtimestamp", "clock_timestamp")


class UnsafeSQL(ValueError):
    pass


def check(sql: str, allowed_tables: set[str], pinned_today: bool) -> None:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQL(f"does not parse: {e}") from e
    if len(statements) != 1:
        raise UnsafeSQL("exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise UnsafeSQL(f"only SELECT is allowed, got {type(tree).__name__}")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN):
            raise UnsafeSQL(f"{type(node).__name__} is not allowed")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    used = {t.name for t in tree.find_all(exp.Table)} - ctes
    unknown = used - allowed_tables
    if unknown:
        raise UnsafeSQL(f"unknown tables: {sorted(unknown)}")
    if pinned_today:
        # the demo's "today" is fixed; the database clock would silently disagree with it
        for f in tree.find_all(exp.Func):
            name = (f.sql_name() or "").lower()
            if name in CLOCK_FUNCTIONS or isinstance(f, (exp.CurrentDate, exp.CurrentTimestamp)):
                raise UnsafeSQL("use the literal dates given, not the database clock")
