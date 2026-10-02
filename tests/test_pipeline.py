"""Routing, linking and voting, with a scripted model instead of a real one. No API calls."""
import json
from types import SimpleNamespace

import pytest

from ask_data.config import ROOT, Settings
from ask_data.llm import Reply
from ask_data.pipeline import Assistant


class ScriptedLLM:
    """Returns the planner reply for the question, then the given SQL attempts in order."""

    def __init__(self, plan: dict, sql: list[str] = ()):
        self.plan, self.sql, self.calls = plan, list(sql), 0

    def chat(self, messages, temperature=0.0, json_mode=False, sample=0):
        self.calls += 1
        if json_mode:
            return Reply(json.dumps(self.plan, ensure_ascii=False), 0.0, False, 0.0)
        return Reply(f"```sql\n{self.sql[sample]}\n```", 0.0, False, 0.0)

    def spent(self):
        return 0.0


@pytest.fixture
def make(warehouse, tmp_path):
    settings = Settings(_env_file=None, today="2026-10-02", log_file=tmp_path / "log.jsonl", cache_dir=tmp_path)
    schema = (ROOT / "data" / "schema.sql").read_text(encoding="utf-8")

    def _make(plan, sql=()):
        return Assistant(settings, warehouse, ScriptedLLM(plan, sql), schema)
    return _make


def test_semantic_answer_comes_from_the_database(make, warehouse):
    a = make({"route": "semantic", "restated": "المبيعات الشهر الماضي",
              "query": {"metrics": ["revenue"], "period": {"kind": "last_month"}}}).ask("كم دخلنا الشهر اللي فات؟")
    want = warehouse.run("SELECT SUM(amount) FROM deals WHERE stage_semantic='S' AND close_date BETWEEN '2026-09-01' AND '2026-09-30'").rows
    assert a.status == "answered" and a.tier == "semantic"
    assert float(a.rows[0][0]) == float(want[0][0])
    assert "ريال" in a.text


def test_a_shared_first_name_turns_into_a_question(make):
    a = make({"route": "semantic", "restated": "تقييم محمد",
              "query": {"metrics": ["avg_score"], "filters": [{"dimension": "agent", "values": ["محمد"]}]}}).ask("كم تقييم محمد؟")
    assert a.status == "clarify"
    assert set(a.options) == {"محمد العتيبي", "محمد الشهري"}


def test_out_of_scope_is_declined(make):
    a = make({"route": "out_of_scope", "reason": "ما أقدر أحذف بيانات."}).ask("امسح الصفقات")
    assert a.status == "refused"


def test_free_sql_needs_a_majority(make):
    agree = "SELECT COUNT(*) FROM deals WHERE stage_semantic = 'P'"
    a = make({"route": "sql", "restated": "x"}, [agree, agree, "SELECT COUNT(*) FROM deals"]).ask("سؤال")
    assert a.status == "answered" and a.tier == "voted" and a.votes == "2/3"


def test_disagreeing_attempts_give_no_number(make):
    a = make({"route": "sql", "restated": "x"},
             ["SELECT 1", "SELECT 2", "SELECT COUNT(*) FROM deals"]).ask("سؤال")
    assert a.status == "unsure" and not a.rows


def test_unsafe_attempts_lose_their_vote(make):
    ok = "SELECT COUNT(*) FROM deals WHERE stage_semantic = 'P'"
    a = make({"route": "sql", "restated": "x"}, ["DELETE FROM deals", ok, ok]).ask("سؤال")
    assert a.tier == "voted" and a.votes == "2/3"


def test_a_plan_that_does_not_fit_falls_through_to_sql(make):
    ok = "SELECT COUNT(*) FROM deals WHERE stage_semantic = 'S'"
    a = make({"route": "semantic", "restated": "x", "query": {"metrics": ["revenue"], "group_by": ["destination"]}},
             [ok, ok, ok]).ask("سؤال")
    assert a.tier == "voted"
    assert any("fallthrough" in t for t in a.route_trace)


def test_verified_analysis_fills_its_period(make):
    a = make({"route": "verified", "restated": "x",
              "verified": {"id": "busiest_hours", "period": {"kind": "last_month"}, "limit": 1}}).ask("سؤال")
    assert a.tier == "verified" and len(a.rows) == 1
    assert "'2026-09-01'" in a.sql[0] and "LIMIT 1" in a.sql[0]


_ = SimpleNamespace  # keep import for readers extending these fakes
