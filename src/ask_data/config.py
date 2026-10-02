"""Runtime configuration, read from env / .env so keys and paths are never hardcoded."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root = three levels up from this file (src/ask_data/config.py)
ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Any OpenAI-compatible endpoint. Built and measured on DeepSeek.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-flash"
    max_spend_usd: float = 0.75       # cumulative, across runs, tracked in .cache/spend.json
    sql_votes: int = 3                # free-SQL answers need a majority of this many attempts

    # Unset = the bundled demo warehouse. Set = a live Postgres (use a read-only user).
    database_url: str | None = None
    demo_db: Path = ROOT / "data" / "demo.duckdb"

    # Pinned for the demo, whose data stops on 2026-10-01. Leave unset on live data.
    today: date | None = None
    timezone: str = "Asia/Riyadh"

    semantic_file: Path = ROOT / "semantic" / "model.yaml"
    verified_file: Path = ROOT / "semantic" / "verified.yaml"
    cache_dir: Path = ROOT / ".cache"
    log_file: Path = ROOT / "logs" / "questions.jsonl"

    def current_date(self) -> date:
        return self.today or datetime.now(ZoneInfo(self.timezone)).date()


settings = Settings()
