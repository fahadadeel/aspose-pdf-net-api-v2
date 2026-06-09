"""
scripts/export_openapi.py -- Dump the FastAPI OpenAPI schema to docs/openapi.json.

Run locally:
    python scripts/export_openapi.py

CI runs this on every push and uploads the resulting docs/openapi.json so the
API contract is browsable in the repo.
"""

import json
import sys
from pathlib import Path


def main() -> int:
    # Make project root importable
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root))

    # Loading main triggers MCP mount and all router registration — exactly
    # what we want reflected in the exported schema.
    from main import app

    schema = app.openapi()

    out = repo_root / "docs" / "openapi.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote {out.relative_to(repo_root)}  ({out.stat().st_size:,} bytes)")
    print(f"Endpoints exposed: {len(schema.get('paths', {}))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
