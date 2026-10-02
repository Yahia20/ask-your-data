"""The compiled SQL is checked against hand-written SQL on the demo warehouse."""
from datetime import date

import pytest

from ask_data.periods import Period, resolve
from ask_data.semantic import SemanticError, SemanticQuery

TODAY = date(2026, 10, 2)


def run(model, warehouse, **query):
    q = SemanticQuery(**query)
    rng = resolve(q.period, TODAY, model.named_periods)
    [c] = model.compile(q, rng, "'2026-10-02'")
    return warehouse.run(c.sql).rows


def test_revenue_is_won_deals_by_close_date(model, warehouse):
    got = run(model, warehouse, metrics=["revenue"], period=Period(kind="last_month"))
    want = warehouse.run("SELECT SUM(amount) FROM deals WHERE stage_semantic = 'S' "
                         "AND close_date BETWEEN '2026-09-01' AND '2026-09-30'").rows
    assert float(got[0][0]) == float(want[0][0])


def test_quality_excludes_unusable_evaluations_and_the_bot(model, warehouse):
    got = run(model, warehouse, metrics=["avg_score"], group_by=["agent"])
    names = {r[0] for r in got}
    assert "بوت الاستقبال" not in names
    want = warehouse.run("SELECT AVG(final_score) FROM agent_evaluations e JOIN agents a USING (agent_id) "
                         "WHERE a.full_name = 'سارة القحطاني' AND contract_status = 'ok' AND gradeable "
                         "AND final_score IS NOT NULL").rows[0][0]
    assert dict(got)["سارة القحطاني"] == pytest.approx(float(want))


def test_destination_filter_does_not_double_count(model, warehouse):
    got = run(model, warehouse, metrics=["conversations"],
              filters=[{"dimension": "destination", "values": ["Istanbul", "Trabzon"]}])
    want = warehouse.run("""SELECT COUNT(DISTINCT ia.interaction_id) FROM interaction_analysis ia
        JOIN interaction_destinations x ON x.analysis_id = ia.analysis_id AND x.role = 'destination'
        JOIN destinations d USING (destination_id) WHERE d.canonical_name IN ('Istanbul', 'Trabzon')""").rows
    assert got[0][0] == want[0][0]


def test_averages_cannot_be_split_by_destination(model):
    with pytest.raises(SemanticError):
        model.compile(SemanticQuery(metrics=["avg_budget_sar"], group_by=["destination"]), None, "now()")


def test_a_dimension_the_entity_lacks_is_refused(model):
    with pytest.raises(SemanticError):
        model.compile(SemanticQuery(metrics=["revenue"], group_by=["destination"]), None, "now()")


def test_snapshot_metric_ignores_the_period(model, warehouse):
    a = run(model, warehouse, metrics=["overdue_followups"])
    b = run(model, warehouse, metrics=["overdue_followups"], period=Period(kind="last_month"))
    assert a == b and a[0][0] > 0


def test_metrics_with_different_date_columns_become_separate_queries(model):
    q = SemanticQuery(metrics=["deals_created", "deals_won"], period=Period(kind="last_month"))
    compiled = model.compile(q, resolve(q.period, TODAY, model.named_periods), "now()")
    assert len(compiled) == 2
    assert "created_at_src" in compiled[0].sql and "close_date" in compiled[1].sql


def test_filter_values_are_quoted_safely(model):
    q = SemanticQuery(metrics=["conversations"], filters=[{"dimension": "agent", "values": ["x'); DROP TABLE deals; --"]}])
    [c] = model.compile(q, None, "now()")
    assert "'x''); DROP TABLE deals; --'" in c.sql
