#!/usr/bin/env python3
"""Read-only guard - a CI gate, not part of the pytest suite.

This project makes one security promise: it touches nothing beyond Delta's
public market-data endpoints. No API key, no signing, no order placement. A
single careless commit could break that promise, so CI verifies it by machine on
every push rather than trusting the README.

A non-zero exit fails the build.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Each entry: (regex, what is wrong with it)
FORBIDDEN = [
    (r"\bapi[_-]?secret\b", "reference to an API secret"),
    (r"\bapi[_-]?key\b", "reference to an API key"),
    (r"\bhmac\b", "HMAC signing (used for private endpoints)"),
    (r"\bsignature\s*=", "request signing"),
    (r"requests\.(post|put|delete|patch)\s*\(", "state-changing HTTP call"),
    (r"/v2/orders\b", "orders endpoint"),
    (r"/v2/positions\b", "positions endpoint"),
    (r"/v2/wallet\b", "wallet endpoint"),
    (r"place_order|cancel_order|create_order", "order placement helper"),
]

# This file names the patterns itself, so it is exempt.
SKIP = {Path(__file__).name}


def main() -> int:
    problems = []

    for path in sorted(ROOT.rglob("*.py")):
        if ".venv" in path.parts or path.name in SKIP:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # These words are fine in comments and docstring prose - the README
            # and module docs explain why this code is deliberately absent.
            if stripped.startswith("#"):
                continue
            for pattern, why in FORBIDDEN:
                if re.search(pattern, line, flags=re.IGNORECASE):
                    rel = path.relative_to(ROOT)
                    problems.append(f"  {rel}:{lineno}  [{why}]\n      {stripped}")

    if problems:
        print("READ-ONLY GUARD FAILED - this project reads public market data only:")
        print("\n".join(problems))
        return 1

    print(f"Read-only guard OK - {len(list(ROOT.rglob('*.py')))} files scanned, "
          "no API key, signing or order-placement code found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
