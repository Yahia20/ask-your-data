"""Ask from the terminal.

    python -m ask_data "كم دخلنا الشهر اللي فات؟"
    python -m ask_data            # interactive
"""
from __future__ import annotations

import sys

from .answer import fmt
from .config import settings
from .pipeline import build


def show(a) -> None:
    print(f"\n{a.text}")
    if a.options:
        print("   " + " | ".join(a.options))
    if a.status == "answered" and len(a.rows) > 1:
        print("   " + " | ".join(a.columns))
        for r in a.rows[:25]:
            print("   " + " | ".join(fmt(v, f, a.lang) for v, f in zip(r, a.formats or [None] * len(r))))
    tier = {"semantic": "verified definitions", "verified": "verified analysis", "voted": f"model-written SQL, {a.votes} agreed"}
    print(f"   [{a.status}{' · ' + tier[a.tier] if a.tier else ''} · {a.seconds}s · ${a.cost_usd:.4f}]\n")


def main() -> None:
    bot = build(settings)
    if len(sys.argv) > 1:
        show(bot.ask(" ".join(sys.argv[1:])))
        return
    while True:
        try:
            q = input("سؤالك > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q:
            show(bot.ask(q))


if __name__ == "__main__":
    main()
