"""
MMC Delta Scanner - Settings Persistence
========================================
Streamlit forgets everything when the process restarts. For a tool you open
every trading day that is a small but constant tax: re-typing the USD/INR
rate, re-picking the underlying, re-setting the fee assumptions.

This module writes those choices to a plain JSON file next to the app.

WHY THIS IS OFF BY DEFAULT
--------------------------
A Streamlit app is ONE process shared by every visitor. On a deployed app a
"save" written to the server is therefore not your setting - it is everyone's.
One person changing the USD/INR rate would change it for every other viewer,
and the file would vanish on the next reboot anyway.

So the file store only runs when MMC_LOCAL_SETTINGS=1 is set, which the local
launcher scripts do and a cloud deployment does not. Everywhere else the view
lives in the URL instead (see url_state.py), which is per-browser, survives a
reload, and can be shared as a link.

Deliberately NOT stored: anything secret. There is nothing secret in this
project - it is read-only market data only - and this file must stay that way.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parent.parent / "mmc_settings.json"

# Launcher scripts ise set karte hain; cloud deployment nahi karta.
LOCAL_ENV_FLAG = "MMC_LOCAL_SETTINGS"


def is_enabled() -> bool:
    """File store sirf tab jab app single-user local run ho."""
    return os.environ.get(LOCAL_ENV_FLAG, "").strip() == "1"


def disabled_reason() -> str:
    return ("Ye app ek shared process hai, isliye server par save karna sabka "
            "setting badal deta. Aapka view URL mein hai — bookmark kar lijiye.")

# Only these keys are ever persisted. An unknown key in the file is ignored,
# so a stale settings file from an older version can never crash the app.
PERSISTED_KEYS = {
    "underlying",
    "refresh_seconds",
    "usdinr",
    "risk_free",
    "iv_scale_mode",
    "greeks_source",
    "price_mode",
    "fee_maker_rate",
    "fee_taker_rate",
    "fee_premium_cap",
    "fee_gst",
    "fee_entry_maker",
    "fee_exit_maker",
}

# Never persist a value that is not one of these plain types.
_SAFE_TYPES = (str, int, float, bool)


def load_settings() -> dict:
    """Read saved settings. Any problem returns {} - never raises."""
    if not is_enabled():
        return {}
    try:
        if not SETTINGS_FILE.exists():
            return {}
        with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return {k: v for k, v in data.items()
                if k in PERSISTED_KEYS and isinstance(v, _SAFE_TYPES)}
    except (OSError, ValueError, TypeError):
        return {}


def save_settings(values: dict) -> bool:
    """Write settings atomically. Returns False on any failure - never raises.

    Atomic write (temp file + replace) so that a crash mid-write cannot leave
    a half-written JSON file that breaks the next startup.
    """
    if not is_enabled():
        return False
    try:
        clean = {k: v for k, v in values.items()
                 if k in PERSISTED_KEYS and isinstance(v, _SAFE_TYPES)}
        tmp = SETTINGS_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(clean, fh, indent=2, sort_keys=True)
        os.replace(tmp, SETTINGS_FILE)
        return True
    except (OSError, ValueError, TypeError):
        return False


def clear_settings() -> bool:
    """Delete the settings file, returning to factory defaults."""
    if not is_enabled():
        return False
    try:
        if SETTINGS_FILE.exists():
            SETTINGS_FILE.unlink()
        return True
    except OSError:
        return False


def settings_path_display() -> str:
    return str(SETTINGS_FILE)
