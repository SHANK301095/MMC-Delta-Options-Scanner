#!/usr/bin/env python3
"""Read-only guard — CI gate, pytest ka hissa nahi.

Is project ka ek hi security promise hai: ye Delta ke public market-data
endpoints ke alawa kuch nahi chhoota. Koi API key, koi signing, koi order
placement. Wo promise ek accidental commit se toot sakta hai, isliye CI har
push par ise machine se verify karta hai — README ke bharose nahi.

Non-zero exit = build fail.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Har pattern: (regex, kya galat hai)
FORBIDDEN = [
    (r"\bapi[_-]?secret\b", "API secret ka reference"),
    (r"\bapi[_-]?key\b", "API key ka reference"),
    (r"\bhmac\b", "HMAC signing (private endpoints ke liye hota hai)"),
    (r"\bsignature\s*=", "request signing"),
    (r"requests\.(post|put|delete|patch)\s*\(", "state-changing HTTP call"),
    (r"/v2/orders\b", "orders endpoint"),
    (r"/v2/positions\b", "positions endpoint"),
    (r"/v2/wallet\b", "wallet endpoint"),
    (r"place_order|cancel_order|create_order", "order placement helper"),
]

# Ye file khud in patterns ko naam se mention karti hai.
SKIP = {Path(__file__).name}


def main() -> int:
    problems = []

    for path in sorted(ROOT.rglob("*.py")):
        if ".venv" in path.parts or path.name in SKIP:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # Comments aur docstring prose mein in shabdon ka aana theek hai —
            # README aur module docs khud samjhate hain ki ye code kyun NAHI hai.
            if stripped.startswith("#"):
                continue
            for pattern, why in FORBIDDEN:
                if re.search(pattern, line, flags=re.IGNORECASE):
                    rel = path.relative_to(ROOT)
                    problems.append(f"  {rel}:{lineno}  [{why}]\n      {stripped}")

    if problems:
        print("READ-ONLY GUARD FAIL — ye project sirf public market data padhta hai:")
        print("\n".join(problems))
        return 1

    print(f"Read-only guard OK — {len(list(ROOT.rglob('*.py')))} files scanned, "
          "koi API key / signing / order-placement code nahi mila.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
