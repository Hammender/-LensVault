from __future__ import annotations

import json
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tests.support.app_loader import load_test_main
from tests.support.contracts import normalize_openapi, ordered_route_table


CONTRACT_DIR = Path(__file__).resolve().parents[1] / "contracts"


def main() -> None:
    module = load_test_main()
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    (CONTRACT_DIR / "openapi.json").write_text(
        json.dumps(normalize_openapi(module.app.openapi()), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (CONTRACT_DIR / "routes.json").write_text(
        json.dumps(ordered_route_table(module.app), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
