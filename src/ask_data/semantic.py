"""The semantic layer: load semantic/model.yaml and compile a query choice into SQL.

The model picks names (metrics, dimensions, filter values, a period). Everything
that decides what a number *means* - which rows count, which date column, which
joins - lives in the YAML and is applied here, the same way every time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from .periods import DateRange, Period


class SemanticError(ValueError):
    """The question can't be expressed with the catalog (the caller falls back to free SQL)."""


class Filter(BaseModel):
    dimension: str
    values: list[str | bool]
    exclude: bool = False


class Top(BaseModel):
    n: int = Field(ge=1, le=100)
    order: Literal["desc", "asc"] = "desc"


class Having(BaseModel):
    metric: str
    op: Literal[">", ">=", "<", "<=", "="]
    value: float


class SemanticQuery(BaseModel):
    metrics: list[str] = Field(min_length=1)
    group_by: list[str] = []
    filters: list[Filter] = []
    period: Period | None = None
    compare_previous: bool = False
    time_grain: Literal["day", "week", "month", "quarter", "year"] | None = None
    top: Top | None = None
    having: Having | None = None


@dataclass
class Metric:
    id: str
    entity: str
    sql: str
    time: str | None          # resolved time expression, or None for snapshots
    joins: list[str]
    format: str
    fanout_safe: bool
    label: dict
    means: str


@dataclass
class Entity:
    id: str
    from_: str
    time: str
    joins: dict[str, str]
    required: list[str]
    where: str | None
    dimensions: dict[str, dict]


@dataclass
class Compiled:
    sql: str
    metrics: list[str]
    dims: list[str]           # output column ids, in order (time grain first if any)


@dataclass
class Model:
    raw: dict
    entities: dict[str, Entity] = field(default_factory=dict)
    metrics: dict[str, Metric] = field(default_factory=dict)

    @classmethod
    def load(cls, path) -> Model:
        raw = yaml.safe_load(open(path, encoding="utf-8"))
        m = cls(raw)
        for eid, e in raw["entities"].items():
            m.entities[eid] = Entity(eid, e["from"], e["time"], e.get("joins") or {}, e.get("required", []),
                                     e.get("where"), e["dimensions"])
        for mid, x in raw["metrics"].items():
            ent = m.entities[x["entity"]]
            time = x["time"] if "time" in x else ent.time
            m.metrics[mid] = Metric(mid, x["entity"], x["sql"], time, x.get("joins", []), x["format"],
                                    x.get("fanout_safe", True), x["label"], x["means"])
        return m

    @property
    def rules(self) -> list[str]:
        return self.raw["rules"]

    @property
    def dimensions(self) -> dict:
        return self.raw["dimensions"]

    @property
    def named_periods(self) -> dict:
        return self.raw["named_periods"]

    # ------------------------------------------------------------------ compile
    def compile(self, q: SemanticQuery, rng: DateRange | None, now_sql: str) -> list[Compiled]:
        """One SQL statement per (entity, time column) group of metrics."""
        unknown = [x for x in q.metrics if x not in self.metrics]
        if unknown:
            raise SemanticError(f"unknown metrics {unknown}")
        groups: dict[tuple[str, str | None], list[str]] = {}
        for mid in q.metrics:
            m = self.metrics[mid]
            groups.setdefault((m.entity, m.time), []).append(mid)
        if q.having and q.having.metric not in q.metrics:
            raise SemanticError("having must use one of the selected metrics")
        if q.time_grain and any(t is None for _, t in groups):
            raise SemanticError("a snapshot metric cannot be split over time")
        return [self._compile_group(eid, time, mids, q, rng, now_sql) for (eid, time), mids in groups.items()]

    def _compile_group(self, eid, time, mids, q, rng, now_sql) -> Compiled:
        ent = self.entities[eid]
        joins = list(ent.required)
        select, dims, group_not_null = [], [], []

        def need(js):
            for j in js:
                if j not in joins:
                    joins.append(j)

        def dim(d):
            if d not in ent.dimensions:
                raise SemanticError(f"dimension '{d}' is not available for {eid} metrics")
            return ent.dimensions[d]

        if q.time_grain:
            select.append(f"date_trunc('{q.time_grain}', {time})::date AS {q.time_grain}")
            dims.append(q.time_grain)
        for d in q.group_by:
            spec = dim(d)
            if spec.get("fanout") and any(not self.metrics[m].fanout_safe for m in mids):
                raise SemanticError(f"grouping by {d} would double count {mids}")
            need(spec.get("joins", []))
            select.append(f"{spec['sql']} AS {d}")
            dims.append(d)
            # rows with nothing to group by (a chat that named no destination) are left out,
            # or "(blank)" can come top of a ranking
            group_not_null.append(f"{spec['sql']} IS NOT NULL")
        for mid in mids:
            m = self.metrics[mid]
            need(m.joins)
            select.append(f"{m.sql.replace('{now}', now_sql)} AS {mid}")

        where = ([ent.where] if ent.where else []) + group_not_null
        for f in q.filters:
            spec = dim(f.dimension)
            where.append(self._filter_sql(f, spec, need))
        if rng and time:
            where.append(f"{time} >= '{rng.start}' AND {time} < '{rng.end_exclusive}'")

        sql = f"SELECT {', '.join(select)}\nFROM {ent.from_}"
        for j in self._ordered(ent, joins):
            sql += f"\n{ent.joins[j]}"
        if where:
            sql += "\nWHERE " + "\n  AND ".join(where)
        if dims:
            sql += "\nGROUP BY " + ", ".join(str(i + 1) for i in range(len(dims)))
        if q.having:
            m = self.metrics[q.having.metric]
            sql += f"\nHAVING {m.sql.replace('{now}', now_sql)} {q.having.op} {q.having.value}"
        if q.top:            # "which month had the most": rank the periods instead of listing them
            sql += f"\nORDER BY {mids[0]} {q.top.order.upper()} NULLS LAST LIMIT {q.top.n}"
        elif q.time_grain:
            sql += "\nORDER BY 1"
        elif dims:
            sql += f"\nORDER BY {mids[0]} DESC NULLS LAST"
        return Compiled(sql, mids, dims)

    @staticmethod
    def _ordered(ent: Entity, joins: list[str]) -> list[str]:
        return [j for j in ent.joins if j in joins]     # YAML order respects join dependencies

    @staticmethod
    def _filter_sql(f: Filter, spec: dict, need) -> str:
        vals = f.values
        if spec.get("fanout"):       # filter without multiplying rows: EXISTS on the trip legs
            need(spec["joins"][:1])
            listed = ", ".join(_lit(v) for v in vals)
            clause = (f"EXISTS (SELECT 1 FROM interaction_destinations fx JOIN destinations fd "
                      f"ON fd.destination_id = fx.destination_id WHERE fx.analysis_id = {spec['analysis_key']} "
                      f"AND fx.role = 'destination' AND fd.canonical_name IN ({listed}))")
            return f"NOT {clause}" if f.exclude else clause
        need(spec.get("joins", []))
        if all(isinstance(v, bool) for v in vals) and len(vals) == 1:
            return f"{spec['sql']} = {'true' if vals[0] != f.exclude else 'false'}"
        listed = ", ".join(_lit(v) for v in vals)
        return f"{spec['sql']} {'NOT IN' if f.exclude else 'IN'} ({listed})"

    # ------------------------------------------------------------------ prompt text
    def catalog(self, values: dict[str, list[str]]) -> str:
        """The catalog as the model sees it."""
        out = ["METRICS (id: meaning [entity, dated by])"]
        for m in self.metrics.values():
            basis = m.time or "snapshot, ignores the period"
            out.append(f"- {m.id}: {m.means} [{m.entity}, {basis}]")
        out.append("\nDIMENSIONS available per entity (for group_by and filters)")
        for e in self.entities.values():
            out.append(f"- {e.id}: {', '.join(e.dimensions)}")
        out.append("\nDIMENSION VALUES (filters must use these exact spellings)")
        for d, spec in self.dimensions.items():
            vals = values.get(d) or spec.get("values") or []
            out.append(f"- {d}: {', '.join(str(v) for v in vals)}")
        out.append("\nNAMED PERIODS")
        for k, v in self.named_periods.items():
            out.append(f"- {k}: {v['label']['en']} ({v['start']} to {v['end']})")
        return "\n".join(out)


def _lit(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return "'" + str(v).replace("'", "''") + "'"
