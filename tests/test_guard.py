import pytest

from ask_data.guard import UnsafeSQL, check

TABLES = {"deals", "agents"}


def ok(sql, pinned=True):
    check(sql, TABLES, pinned_today=pinned)


def test_plain_and_cte_selects_pass():
    ok("SELECT COUNT(*) FROM deals d WHERE d.stage_semantic = 'S'")
    ok("WITH w AS (SELECT agent_id FROM deals) SELECT a.full_name FROM agents a JOIN w USING (agent_id)")


@pytest.mark.parametrize("sql", [
    "DELETE FROM deals",
    "DROP TABLE deals",
    "UPDATE deals SET amount = 0",
    "INSERT INTO deals (deal_id) VALUES ('x')",
    "SELECT 1; DROP TABLE deals",
    "SELECT * FROM pg_user",
    "SELECT * FROM salaries",
])
def test_anything_else_is_refused(sql):
    with pytest.raises(UnsafeSQL):
        ok(sql)


def test_clock_functions_are_refused_while_today_is_pinned():
    with pytest.raises(UnsafeSQL):
        ok("SELECT COUNT(*) FROM deals WHERE close_date > now() - interval '7 days'")
    with pytest.raises(UnsafeSQL):
        ok("SELECT COUNT(*) FROM deals WHERE close_date = CURRENT_DATE")
    ok("SELECT COUNT(*) FROM deals WHERE close_date > now() - interval '7 days'", pinned=False)
