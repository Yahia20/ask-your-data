"""Run a question set through the assistant and grade every answer against the expected SQL.

    python eval/run_eval.py --set dev                       # tuning
    python eval/run_eval.py --set test                      # the frozen exam, run once
    python eval/run_eval.py --set test --model deepseek-v4-pro

Grading is done by code, never by a model: the expected SQL runs on the same
warehouse and the two results are compared value by value (src/ask_data/compare.py).

How an answer is scored:
  expect answer  -> correct if answered and the numbers match; "clarify"/"unsure" = not answered (no guess)
  expect clarify -> correct if the assistant asked a follow-up
  expect refuse  -> correct if it declined
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ask_data.compare import matches  # noqa: E402
from ask_data.config import settings  # noqa: E402
from ask_data.pipeline import build  # noqa: E402


def grade(item, ans, wh) -> tuple[str, str]:
    """-> (verdict, note). verdict: correct | wrong | abstained"""
    expect = item.get("expect", "answer")
    if expect == "clarify":
        return ("correct", "") if ans.status == "clarify" else ("wrong", f"expected a follow-up, got {ans.status}")
    if expect == "refuse":
        return ("correct", "") if ans.status == "refused" else ("wrong", f"expected a refusal, got {ans.status}")
    if ans.status in ("clarify", "unsure"):
        return "abstained", ans.status
    if ans.status != "answered":
        return "wrong", f"status {ans.status}: {ans.text[:120]}"
    gold = wh.run(item["sql"]).rows
    if matches(gold, ans.rows):
        return "correct", ""
    return "wrong", f"expected {gold[:3]} got {ans.rows[:3]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=["dev", "test"], default="dev")
    ap.add_argument("--model", default=None)
    ap.add_argument("--only", nargs="*", help="question ids")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.model:
        settings.llm_model = args.model
    assistant = build(settings)
    items = yaml.safe_load(open(ROOT / "eval" / f"{args.set}_set.yaml", encoding="utf-8"))
    if args.only:
        items = [i for i in items if i["id"] in args.only]

    t0 = time.time()
    spent0 = assistant.llm.spent()

    def run(item):
        ans = assistant.ask(item["q"])
        verdict, note = grade(item, ans, assistant.wh)
        return item, ans, verdict, note

    rows = []
    with ThreadPoolExecutor(args.workers) as pool:
        for item, ans, verdict, note in pool.map(run, items):
            mark = {"correct": "✅", "wrong": "❌", "abstained": "⏸️"}[verdict]
            print(f"{mark} {item['id']} [{item['cat']}] {ans.tier or ans.status} {ans.votes or ''} {item['q']}"
                  + (f"\n     {note}" if verdict != "correct" else ""), flush=True)
            rows.append({"id": item["id"], "cat": item["cat"], "q": item["q"], "expect": item.get("expect", "answer"),
                         "verdict": verdict, "note": note, "status": ans.status, "tier": ans.tier, "votes": ans.votes,
                         "trace": ans.route_trace, "sql": ans.sql, "rows": [list(map(str, r)) for r in ans.rows[:10]],
                         "text": ans.text, "seconds": ans.seconds, "cost_usd": ans.cost_usd})

    summary = summarise(rows)
    summary.update(model=settings.llm_model, set=args.set, questions=len(rows),
                   wall_seconds=round(time.time() - t0, 1), llm_spend_usd=round(assistant.llm.spent() - spent0, 4),
                   warehouse=assistant.wh.name)
    out = ROOT / "eval" / "results" / f"{args.set}_{settings.llm_model}_{assistant.wh.name}.json"
    out.write_text(json.dumps({"summary": summary, "rows": sorted(rows, key=lambda r: r["id"])},
                              ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def summarise(rows):
    ans = [r for r in rows if r["expect"] == "answer"]
    answered = [r for r in ans if r["verdict"] != "abstained"]
    by_tier = defaultdict(lambda: [0, 0])
    for r in answered:
        by_tier[r["tier"] or r["status"]][0] += r["verdict"] == "correct"
        by_tier[r["tier"] or r["status"]][1] += 1
    trusted = [r for r in answered if r["tier"] in ("semantic", "verified")]
    by_cat = defaultdict(lambda: [0, 0])
    for r in rows:
        by_cat[r["cat"]][0] += r["verdict"] == "correct"
        by_cat[r["cat"]][1] += 1

    def pct(a, b):
        return round(100 * a / b, 1) if b else None

    secs = sorted(r["seconds"] for r in rows)
    return {
        "accuracy_trusted_answers": pct(sum(r["verdict"] == "correct" for r in trusted), len(trusted)),
        "trusted_answers": len(trusted),
        "accuracy_all_answers": pct(sum(r["verdict"] == "correct" for r in answered), len(answered)),
        "coverage": pct(len(answered), len(ans)),
        "correct_of_answerable": pct(sum(r["verdict"] == "correct" for r in ans), len(ans)),
        "abstained": len(ans) - len(answered),
        "clarify_correct": pct(*by_cat["ambiguous"]),
        "refuse_correct": pct(*by_cat["oos"]),
        "by_tier": {k: f"{c}/{n} ({pct(c, n)}%)" for k, (c, n) in by_tier.items()},
        "by_category": {k: f"{c}/{n} ({pct(c, n)}%)" for k, (c, n) in by_cat.items()},
        "median_seconds": secs[len(secs) // 2] if secs else None,
        "p90_seconds": secs[int(len(secs) * 0.9)] if secs else None,
        "avg_cost_usd_per_question": round(sum(r["cost_usd"] for r in rows) / max(len(rows), 1), 6),
    }


if __name__ == "__main__":
    main()
