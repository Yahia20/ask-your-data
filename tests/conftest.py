import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

DEMO = ROOT / "data" / "demo.duckdb"


@pytest.fixture(scope="session")
def warehouse():
    if not DEMO.exists():
        pytest.skip("demo warehouse not built - run: python data/generate.py")
    from ask_data.warehouse import DuckDBWarehouse

    return DuckDBWarehouse(DEMO, "Asia/Riyadh")


@pytest.fixture(scope="session")
def model():
    from ask_data.semantic import Model

    return Model.load(ROOT / "semantic" / "model.yaml")
