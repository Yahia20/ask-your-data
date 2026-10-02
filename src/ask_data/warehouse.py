"""Where queries run. Every query is written in Postgres SQL.

- PostgresWarehouse runs it as-is on the live database, in a read-only transaction.
- DuckDBWarehouse runs the same SQL on the bundled demo file, translated by sqlglot.

Both open the data read-only and set the business timezone, so "September"
means September in Riyadh on either one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd
import sqlglot

MAX_ROWS = 1000


@dataclass
class Result:
    columns: list[str]
    rows: list[tuple]

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows, columns=self.columns)


class Warehouse(Protocol):
    name: str

    def run(self, sql: str) -> Result: ...


class DuckDBWarehouse:
    name = "duckdb"

    def __init__(self, path, timezone: str):
        import duckdb

        self.con = duckdb.connect(str(path), read_only=True)
        self.con.execute(f"SET TimeZone = '{timezone}'")

    def run(self, sql: str) -> Result:
        translated = sqlglot.transpile(sql, read="postgres", write="duckdb")[0]
        cur = self.con.cursor()
        cur.execute(translated)
        return Result([d[0] for d in cur.description], cur.fetchmany(MAX_ROWS))


class PostgresWarehouse:
    name = "postgres"

    def __init__(self, url: str, timezone: str, statement_timeout_ms: int = 15000):
        import psycopg

        self.con = psycopg.connect(url, autocommit=True)
        with self.con.cursor() as cur:
            cur.execute("SET default_transaction_read_only = on")
            cur.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
            cur.execute("SELECT set_config('TimeZone', %s, false)", (timezone,))

    def run(self, sql: str) -> Result:
        with self.con.cursor() as cur:
            cur.execute(sql)
            return Result([d.name for d in cur.description], cur.fetchmany(MAX_ROWS))


def connect(settings) -> Warehouse:
    if settings.database_url:
        return PostgresWarehouse(settings.database_url, settings.timezone)
    if not settings.demo_db.exists():
        raise FileNotFoundError(f"{settings.demo_db} is missing - run: python data/generate.py")
    return DuckDBWarehouse(settings.demo_db, settings.timezone)
