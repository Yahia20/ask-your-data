"""The one place that talks to the model.

- Every response is cached on disk by (model, messages, temperature, sample),
  so re-running an evaluation costs nothing.
- Spend is recorded in a ledger and checked *before* each call; past the cap,
  calls stop instead of quietly running up a bill.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# USD per 1M tokens at PEAK rates; off-peak calls are charged half (see _is_peak).
PRICES = {
    "deepseek-flash": {"hit": 0.006, "miss": 0.30, "out": 1.20},
    "deepseek-v4-pro": {"hit": 0.044, "miss": 1.32, "out": 3.96},
}


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    cost_usd: float
    cached: bool
    seconds: float


class LLM:
    def __init__(self, api_key: str, base_url: str, model: str, cache_dir: Path, max_spend_usd: float):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=120, max_retries=3)
        self.model = model
        self.cache_dir = Path(cache_dir) / "llm"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Path(cache_dir) / "spend.json"
        self.max_spend = max_spend_usd
        self._lock = threading.Lock()

    def spent(self) -> float:
        try:
            return json.loads(self.ledger.read_text())["usd"]
        except (FileNotFoundError, ValueError, KeyError):
            return 0.0

    def _record(self, usd: float) -> None:
        with self._lock:
            total = self.spent() + usd
            self.ledger.write_text(json.dumps({"usd": round(total, 6)}))

    def chat(self, messages: list[dict], temperature: float = 0.0, json_mode: bool = False,
             sample: int = 0) -> Reply:
        key = hashlib.sha256(json.dumps([self.model, messages, temperature, json_mode, sample],
                                        ensure_ascii=False).encode()).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return Reply(json.loads(path.read_text(encoding="utf-8"))["text"], 0.0, True, 0.0)
        if self.spent() >= self.max_spend:
            raise BudgetExceeded(f"LLM spend cap reached (${self.max_spend:.2f}); raise MAX_SPEND_USD to continue")
        t0 = time.time()
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = self.client.chat.completions.create(model=self.model, messages=messages,
                                                   temperature=temperature, **kwargs)
        text = resp.choices[0].message.content or ""
        cost = self._cost(resp.usage)
        self._record(cost)
        path.write_text(json.dumps({"text": text, "cost_usd": cost}, ensure_ascii=False), encoding="utf-8")
        return Reply(text, cost, False, time.time() - t0)

    def _cost(self, usage) -> float:
        p = PRICES.get(self.model, PRICES["deepseek-v4-pro"])
        hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        miss = getattr(usage, "prompt_cache_miss_tokens", None)
        if miss is None:
            miss = usage.prompt_tokens - hit
        full = (hit * p["hit"] + miss * p["miss"] + usage.completion_tokens * p["out"]) / 1e6
        return full if _is_peak() else full / 2


def _is_peak(now: datetime | None = None) -> bool:
    """DeepSeek peak hours: Mon-Fri 01:00-04:00 and 06:00-10:00 UTC. Everything else is half price."""
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)
