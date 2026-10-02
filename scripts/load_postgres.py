"""Copy the demo data into a Postgres that already has the production schema.

This is how the "same SQL runs on the real database" claim was checked: the
production migrations were applied to an empty Postgres, this script filled it
with the demo data, and the test set was re-run against it.

    python scripts/load_postgres.py postgresql://postgres:demo@localhost:55433/c360

Columns the production tables require but the demo doesn't have (prompt
versions, schema versions...) get a placeholder of the right type.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import psycopg

ROOT = Path(__file__).resolve().parents[1]
ORDER = ["agents", "customers", "deals", "destinations", "destination_aliases", "interactions", "interaction_metrics",
         "interaction_analysis", "interaction_destinations", "agent_evaluations", "follow_ups"]
# Demo columns production only accepts together with fields the demo doesn't model
# (an AI outcome must name when and from what it was assessed). No question uses them.
SKIP = {"deals": {"ai_outcome"}}


def placeholder(cur, col):
    name, dtype, udt = col
    if dtype == "USER-DEFINED":
        cur.execute("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = %s ORDER BY enumsortorder LIMIT 1", (udt,))
        return cur.fetchone()[0]
    return {"boolean": False, "integer": 0, "bigint": 0, "numeric": 0, "jsonb": "{}", "date": "2026-01-01",
            "timestamp with time zone": "2026-01-01T00:00:00+03:00"}.get(dtype, "demo")


def main(url: str):
    src = duckdb.connect(str(ROOT / "data" / "demo.duckdb"), read_only=True)
    with psycopg.connect(url) as pg, pg.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(ORDER) + " CASCADE")
        for table in ORDER:
            ours = [r[0] for r in src.execute(f"DESCRIBE {table}").fetchall()]
            cur.execute("""SELECT column_name, is_nullable, column_default, data_type, udt_name, is_generated
                           FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s""", (table,))
            theirs = {r[0]: r for r in cur.fetchall()}
            cols = [c for c in ours if c in theirs and theirs[c][5] != "ALWAYS" and c not in SKIP.get(table, ())]
            extra = [(c, placeholder(cur, (c, r[3], r[4]))) for c, r in theirs.items()
                     if c not in cols and r[1] == "NO" and r[2] is None and r[5] != "ALWAYS"]
            rows = src.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            names = cols + [c for c, _ in extra]
            if table == "destination_aliases":
                # production keeps one row per folded spelling ('إسطنبول' and 'اسطنبول' are one alias)
                cur.executemany(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(names))}) "
                                "ON CONFLICT DO NOTHING", [list(r) + [v for _, v in extra] for r in rows])
            else:
                with cur.copy(f"COPY {table} ({', '.join(names)}) FROM STDIN") as cp:
                    for r in rows:
                        cp.write_row(list(r) + [v for _, v in extra])
            print(f"{table:26s} {len(rows):>6}  placeholders: {[c for c, _ in extra] or '-'}")
        pg.commit()


if __name__ == "__main__":
    main(sys.argv[1])
