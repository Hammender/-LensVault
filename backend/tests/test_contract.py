from __future__ import annotations

import json
from pathlib import Path

from tests.support.app_loader import load_test_main
from tests.support.contracts import normalize_openapi, ordered_route_table


CONTRACT_DIR = Path(__file__).parent / "contracts"


def test_openapi_contract_matches_baseline() -> None:
    module = load_test_main()
    expected = json.loads((CONTRACT_DIR / "openapi.json").read_text(encoding="utf-8"))
    assert normalize_openapi(module.app.openapi()) == expected


def test_ordered_route_table_matches_baseline() -> None:
    module = load_test_main()
    expected = json.loads((CONTRACT_DIR / "routes.json").read_text(encoding="utf-8"))
    assert ordered_route_table(module.app) == expected
