"""Write the OpenAPI schema for the frontend type generator: `uv run python export_openapi.py`."""

import json
import sys
from pathlib import Path
from typing import Any

from main import app


def strip_discriminators(node: Any) -> Any:
    # Boolean discriminators (is_anonymous) become string enums in openapi-typescript; the plain
    # oneOf union of `const: true | false` literals narrows correctly in TypeScript on its own.
    if isinstance(node, dict):
        return {k: strip_discriminators(v) for k, v in node.items() if k != "discriminator"}
    if isinstance(node, list):
        return [strip_discriminators(v) for v in node]
    return node


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "../frontend/src/types/openapi.json")
    out.write_text(json.dumps(strip_discriminators(app.openapi()), indent=1) + "\n")
    print(f"wrote {out}")
