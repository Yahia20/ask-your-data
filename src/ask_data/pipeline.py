"""The assistant: question in, Answer out.

    plan (model) ─┬─ semantic ──> link values -> compile from YAML -> run      ✅ verified
                  ├─ verified ──> fill reviewed SQL -> run                       ✅ verified
                  ├─ sql ───────> model writes N queries -> run all -> majority  ⚠️ voted
                  ├─ clarify ───> ask the manager to choose
                  └─ out_of_scope -> decline

A semantic or verified plan that turns out not to fit (unknown value, a
dimension the metric can't be split by) falls through to the free-SQL path
instead of failing. Numbers in an answer always come from the database.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pandas as pd
import yaml

from . import guard
from .answer import Answer, fmt
from .compare import majority
from .linking import Ambiguous, Linker, NotFound
from .llm import LLM, BudgetExceeded
from .periods import DateRange, resolve
from .planner import Plan, PlanError, parse
from .prompts import EXAMPLES, PLANNER, SQL_WRITER, weekday
from .semantic import Model, SemanticError
from .text import is_arabic, to_western_digits
from .warehouse import Warehouse, connect

TABLES = {"agents", "customers", "destinations", "destination_aliases", "interactions", "interaction_metrics",
          "interaction_analysis", "interaction_destinations", "agent_evaluations", "deals", "follow_ups"}


class Fallthrough(Exception):
    """This route can't answer it; try free SQL."""


class Assistant:
    def __init__(self, settings, warehouse: Warehouse, llm: LLM, schema_sql: str):
        self.s = settings
        self.wh = warehouse
        self.llm = llm
        self.model = Model.load(settings.semantic_file)
        self.verified = {v["id"]: v for v in yaml.safe_load(open(settings.verified_file, encoding="utf-8"))}
        self.values = self._load_values()
        aliases = {"destination": {a: c for c, a in self.wh.run(self.model.dimensions["destination"]["aliases_sql"]).rows}}
        self.linker = Linker(self.values, aliases)
        self.today = settings.current_date()
        self.planner_prompt = self._planner_prompt()
        self.sql_prompt = self._sql_prompt(schema_sql)

    # ------------------------------------------------------------------ setup
    def _load_values(self) -> dict[str, list[str]]:
        out = {}
        for d, spec in self.model.dimensions.items():
            if "values_sql" in spec:
                out[d] = sorted(str(r[0]) for r in self.wh.run(spec["values_sql"]).rows)
            else:
                out[d] = [v for v in spec["values"] if not isinstance(v, bool)]
        return out

    def _planner_prompt(self) -> str:
        verified = "\n".join(f"- {v['id']}: {v['means']} [{', '.join(v.get('params', [])) or 'no params'}]"
                             for v in self.verified.values())
        examples = "\n".join(f"Q: {q}\nA: {json.dumps(a, ensure_ascii=False)}" for q, a in EXAMPLES)
        return PLANNER.format(today=self.today, weekday=weekday(self.today), rules=self._rules(),
                              catalog=self.model.catalog(self.values), verified=verified, examples=examples)

    def _sql_prompt(self, schema_sql: str) -> str:
        lm_end = self.today.replace(day=1) - timedelta(days=1)
        values = "\n".join(f"- {d}: {', '.join(v)}" for d, v in self.values.items() if v)
        return SQL_WRITER.format(today=self.today, weekday=weekday(self.today), schema=schema_sql,
                                 rules=self._rules(), values=values, year_start=self.today.replace(month=1, day=1),
                                 lm_start=lm_end.replace(day=1), lm_end=lm_end)

    def _rules(self) -> str:
        return "\n".join(f"- {r}" for r in self.model.rules)

    def _now_sql(self) -> str:
        return f"'{self.today}'" if self.s.today else "now()"

    # ------------------------------------------------------------------ main
    def ask(self, question: str) -> Answer:
        t0 = time.time()
        spent0 = self.llm.spent()
        lang = "ar" if is_arabic(question) else "en"
        a = Answer(question=question, status="error", lang=lang)
        try:
            self._answer(to_western_digits(question).strip(), a)
        except BudgetExceeded as e:
            a.status, a.text = "error", str(e)
        a.seconds = round(time.time() - t0, 2)
        a.cost_usd = round(self.llm.spent() - spent0, 6)
        self._log(a)
        return a

    def _answer(self, q: str, a: Answer) -> None:
        plan, messages = self._plan(q)
        a.restated = plan.restated
        a.route_trace.append(plan.route)
        try:
            if plan.route == "out_of_scope":
                a.status = "refused"
                a.text = plan.reason or ("ما أقدر أساعد في هذا." if a.lang == "ar" else "I can't help with that.")
                return
            if plan.route == "clarify":
                self._clarify(a, plan.clarify.question, plan.clarify.options)
                return
            if plan.route == "semantic":
                plan = self._link(plan, q, messages, a)
                if a.status == "clarify":
                    return
                self._run_semantic(plan, a)
                return
            if plan.route == "verified":
                self._run_verified(plan, a)
                return
        except Fallthrough as e:
            a.route_trace.append(f"fallthrough: {e}")
        self._run_free_sql(q, plan, a)

    # ------------------------------------------------------------------ planning
    def _plan(self, q: str) -> tuple[Plan, list[dict]]:
        messages = [{"role": "system", "content": self.planner_prompt}, {"role": "user", "content": q}]
        reply = self.llm.chat(messages, temperature=0.0, json_mode=True)
        try:
            return parse(reply.text), messages + [{"role": "assistant", "content": reply.text}]
        except PlanError as e:
            return self._replan(messages + [{"role": "assistant", "content": reply.text}], str(e))

    def _replan(self, messages: list[dict], error: str) -> tuple[Plan, list[dict]]:
        messages = messages + [{"role": "user", "content": f"That plan cannot be used: {error}\nReturn a corrected JSON plan."}]
        reply = self.llm.chat(messages, temperature=0.0, json_mode=True)
        try:
            return parse(reply.text), messages + [{"role": "assistant", "content": reply.text}]
        except PlanError:
            return Plan(route="sql", restated=""), messages

    def _link(self, plan: Plan, q: str, messages: list[dict], a: Answer, retried: bool = False) -> Plan:
        try:
            for f in plan.query.filters:
                f.values = [self.linker.resolve(f.dimension, v) for v in f.values]
            return plan
        except Ambiguous as e:
            ask = "تقصد مين بالضبط؟" if e.dimension == "agent" else f"تقصد أي {e.said}؟"
            self._clarify(a, ask if a.lang == "ar" else f"Which {e.said} do you mean?", e.options)
            return plan
        except NotFound as e:
            if retried:
                raise Fallthrough(f"no stored value for {e.dimension}={e.said}")
            new, msgs = self._replan(messages, f"'{e.said}' is not a stored value of {e.dimension}. "
                                               f"Use one of: {', '.join(e.known[:60])}, or a different route.")
            a.route_trace.append(f"replanned: {new.route}")
            if new.route != "semantic":
                raise Fallthrough(f"replanned as {new.route}")
            return self._link(new, q, msgs, a, retried=True)

    def _clarify(self, a: Answer, question: str, options: list[str]) -> None:
        a.status = "clarify"
        a.text = question
        a.options = options

    # ------------------------------------------------------------------ semantic
    def _run_semantic(self, plan: Plan, a: Answer) -> None:
        q = plan.query
        try:
            rng = resolve(q.period, self.today, self.model.named_periods)
            compiled = self.model.compile(q, rng, self._now_sql())
            df = self._run_compiled(compiled)
            if q.compare_previous:
                if rng is None:
                    raise SemanticError("compare_previous needs a period")
                prev_compiled = self.model.compile(q, rng.previous(), self._now_sql())
                before = self._run_compiled(prev_compiled)
                df = self._merge_previous(df, before, q.metrics, compiled[0].dims)
                compiled += prev_compiled
        except (SemanticError, ValueError) as e:
            raise Fallthrough(str(e)) from e
        except Exception as e:  # noqa: BLE001 - a compiled query the database rejects is a bug; don't guess, fall through
            raise Fallthrough(f"database error: {e}") from e
        a.tier = "semantic"
        a.sql = [c.sql for c in compiled]
        self._fill(a, df, plan, rng)

    def _run_compiled(self, compiled) -> pd.DataFrame:
        frames = []
        for c in compiled:
            df = self.wh.run(c.sql).frame()
            if c.dims:
                df = df.dropna(subset=c.metrics, how="all")
            frames.append((c, df))
        df = frames[0][1]
        for c, other in frames[1:]:
            df = df.merge(other, on=c.dims, how="outer") if c.dims else pd.concat([df, other], axis=1)
        return df

    @staticmethod
    def _merge_previous(cur: pd.DataFrame, prev: pd.DataFrame, metrics: list[str], dims: list[str]) -> pd.DataFrame:
        prev = prev.rename(columns={m: f"{m}__previous" for m in metrics})
        df = cur.merge(prev, on=dims, how="left") if dims else pd.concat([cur, prev], axis=1)
        for m in metrics:
            p = pd.to_numeric(df[f"{m}__previous"], errors="coerce").astype(float)
            c = pd.to_numeric(df[m], errors="coerce").astype(float)
            df[f"{m}__change_pct"] = (c - p) / p.where(p != 0) * 100
        return df

    def _fill(self, a: Answer, df: pd.DataFrame, plan: Plan, rng: DateRange | None) -> None:
        a.status = "answered"
        q = plan.query
        lang = a.lang
        labels, formats = [], []
        for col in df.columns:
            base, _, suffix = col.partition("__")
            if base in self.model.metrics:
                m = self.model.metrics[base]
                label = m.label[lang]
                if suffix == "previous":
                    label += " (الفترة السابقة)" if lang == "ar" else " (previous)"
                    formats.append(m.format)
                elif suffix == "change_pct":
                    label = ("التغيّر %" if lang == "ar" else "change %")
                    formats.append("pct")
                else:
                    formats.append(m.format)
                labels.append(label)
            else:
                spec = self.model.dimensions.get(base, {})
                labels.append(spec.get("label", {}).get(lang) or {"day": "اليوم", "week": "الأسبوع", "month": "الشهر",
                                                                   "quarter": "الربع", "year": "السنة"}.get(base, base))
                formats.append(None)
        a.columns, a.formats = labels, formats
        a.rows = [tuple(None if pd.isna(v) else v for v in r) for r in df.itertuples(index=False)]
        when = (f" — {rng.label_ar} ({rng.start} → {rng.end})" if lang == "ar" else f" — {rng.label_en} ({rng.start} to {rng.end})") if rng else ""
        if len(a.rows) == 1 and not any(c in self.model.dimensions or c in ("day", "week", "month", "quarter", "year")
                                        for c in df.columns):
            parts = []
            for i, col in enumerate(df.columns):
                if "__" in col:
                    continue
                v = fmt(a.rows[0][i], formats[i], lang)
                line = f"{labels[i]}{when}: **{v}**"
                if f"{col}__previous" in df.columns:
                    j = list(df.columns).index(f"{col}__previous")
                    k = list(df.columns).index(f"{col}__change_pct")
                    pv, ch = a.rows[0][j], a.rows[0][k]
                    vs = "مقابل" if lang == "ar" else "vs"
                    line += f" {vs} {fmt(pv, formats[j], lang)}"
                    if ch is not None:
                        line += f" ({ch:+.1f}%)"
                parts.append(line)
            a.text = "\n".join(parts)
        elif q.top and q.top.n == 1 and a.rows:
            first = a.rows[0]
            k = len(q.group_by) + (1 if q.time_grain else 0)
            a.text = f"**{fmt(first[0], None, lang)}** — {labels[k]}: {fmt(first[k], formats[k], lang)}{when}"
        else:
            a.text = (plan.restated or "") + (when if rng and rng.label_ar not in (plan.restated or "") else "")
        a.chart = self._chart(df, q)

    @staticmethod
    def _chart(df: pd.DataFrame, q) -> dict | None:
        if len(df) < 2:
            return None
        if q.time_grain:
            return {"kind": "line", "x": 0, "y": len(q.group_by) + 1}
        if len(q.group_by) == 1 and len(df) <= 25:
            return {"kind": "bar", "x": 0, "y": 1}
        return None

    # ------------------------------------------------------------------ verified
    def _run_verified(self, plan: Plan, a: Answer) -> None:
        call = plan.verified
        spec = self.verified.get(call.id)
        if spec is None:
            raise Fallthrough(f"unknown verified analysis {call.id}")
        try:
            rng = resolve(call.period, self.today, self.model.named_periods)
        except ValueError as e:
            raise Fallthrough(str(e)) from e

        def period(m):
            col = m.group(1)
            return f"{col} >= '{rng.start}' AND {col} < '{rng.end_exclusive}'" if rng else "true"

        sql = re.sub(r"\{period:([^}]+)\}", period, spec["sql"])
        sql = sql.replace("{days_ago:days}", str(self.today - timedelta(days=call.days or 90)))
        sql = sql.replace("{limit}", f"LIMIT {call.limit}" if call.limit else "").strip()
        try:
            res = self.wh.run(sql)
        except Exception as e:  # noqa: BLE001
            raise Fallthrough(f"verified query failed: {e}") from e
        a.tier = "verified"
        a.sql = [sql]
        self._fill_plain(a, res.columns, res.rows, spec["title"][a.lang])

    # ------------------------------------------------------------------ free SQL
    def _run_free_sql(self, q: str, plan: Plan, a: Answer) -> None:
        a.route_trace.append("sql")
        prompt = [{"role": "system", "content": self.sql_prompt},
                  {"role": "user", "content": q + (f"\n(Restated: {plan.restated})" if plan.restated else "")}]
        n = self.s.sql_votes

        def attempt(i):
            reply = self.llm.chat(prompt, temperature=0.0 if i == 0 else 0.8, sample=i)
            m = re.search(r"```sql\s*(.*?)```", reply.text, re.S | re.I)
            sql = (m.group(1) if m else reply.text).strip().rstrip(";")
            try:
                guard.check(sql, TABLES, pinned_today=self.s.today is not None)
                return sql, self.wh.run(sql)
            except Exception as e:  # noqa: BLE001 - a failed attempt is just a lost vote
                return sql, e

        with ThreadPoolExecutor(n) as pool:
            attempts = list(pool.map(attempt, range(n)))
        results = [r.rows if not isinstance(r, Exception) else None for _, r in attempts]
        best, size = majority(results)
        a.sql = [s for s, _ in attempts]
        a.votes = f"{size}/{n}"
        if best is None or size < 2:
            a.status = "unsure"
            a.text = ("ما قدرت أتأكد من إجابة هذا السؤال: المحاولات طلعت أرقام مختلفة. جرّب تعيد صياغته بشكل أدق."
                      if a.lang == "ar" else "I couldn't get a consistent answer. Try asking more specifically.")
            return
        sql, res = attempts[best]
        a.sql = [sql]
        a.tier = "voted"
        self._fill_plain(a, res.columns, res.rows, plan.restated or q)

    def _fill_plain(self, a: Answer, columns: list[str], rows: list[tuple], title: str) -> None:
        a.status = "answered"
        a.columns = list(columns)
        a.rows = [tuple(r) for r in rows]
        a.formats = [None] * len(columns)
        if len(rows) == 1 and len(columns) <= 2:
            a.text = f"{title}: **{'، '.join(fmt(v, None, a.lang) for v in rows[0])}**"
        else:
            a.text = title
        if 2 <= len(rows) <= 25 and len(columns) == 2:
            a.chart = {"kind": "bar", "x": 0, "y": 1}

    # ------------------------------------------------------------------ log
    def _log(self, a: Answer) -> None:
        try:
            self.s.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.s.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "q": a.question,
                                    "status": a.status, "tier": a.tier, "trace": a.route_trace, "votes": a.votes,
                                    "cost_usd": a.cost_usd}, ensure_ascii=False) + "\n")
        except OSError:
            pass


def build(settings) -> Assistant:
    from .config import ROOT

    llm = LLM(settings.llm_api_key, settings.llm_base_url, settings.llm_model, settings.cache_dir, settings.max_spend_usd)
    schema = (ROOT / "data" / "schema.sql").read_text(encoding="utf-8")
    return Assistant(settings, connect(settings), llm, schema)
