"""
MMC Delta Scanner - View state in the URL
=========================================
Whatever you are looking at is written into the URL. That means:

  * Reloading the page returns you to the same view
  * A link can be bookmarked - "BTC, next expiry, 15-25 delta" becomes a URL
  * Send that link to someone and they see exactly the same screen

This is better than a server-side settings file, especially on a deployed app.
A Streamlit app is a single process shared by every visitor, so a setting
"saved" on the server becomes everyone's setting. The URL belongs to each
browser - nobody can change anyone else's view.

URL PARAMS COME FROM OUTSIDE
----------------------------
Anyone can type anything into them. So every value is validated and a bad one
is DROPPED SILENTLY rather than guessed at: `?u=<script>` simply opens on the
default underlying, and nothing breaks. Numbers are clamped to their range.
"""

from __future__ import annotations

import math

# Short keys, deliberately - the URL should stay readable and shareable.
KEY_UNDERLYING = "u"
KEY_EXPIRY = "e"
KEY_PRICE_MODE = "p"
KEY_USDINR = "fx"
KEY_DELTA_BAND = "d"
KEY_VOL_BAND = "v"

# Short codes in the URL, full labels in session_state.
PRICE_CODES = {"realistic": "Realistic (buy ask / sell bid)",
               "mid": "Mid",
               "mark": "Mark"}
PRICE_LABELS = {v: k for k, v in PRICE_CODES.items()}

USDINR_MIN, USDINR_MAX = 50.0, 150.0


def _clean_symbol(value) -> str | None:
    """A short alphanumeric symbol like an underlying, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if not text or len(text) > 12 or not text.isalnum():
        return None
    return text


def _clean_expiry(value) -> str | None:
    """DD-MM-YYYY - the shape Delta's API expects."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split("-")
    if len(parts) != 3:
        return None
    day, month, year = parts
    if not (len(day) == 2 and len(month) == 2 and len(year) == 4):
        return None
    if not all(p.isdigit() for p in parts):
        return None
    if not (1 <= int(day) <= 31 and 1 <= int(month) <= 12):
        return None
    return f"{day}-{month}-{year}"


def _clean_float(value, lo: float, hi: float) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return min(hi, max(lo, out))


def _clean_band(value, lo: float = 0.0, hi: float = 100.0) -> tuple | None:
    """"15-25" -> (15.0, 25.0). A reversed pair is read as a range.

    Negative values are rejected rather than clamped, deliberately. The sliders
    this band feeds are 0-100, so "-50" has no meaning - and a string like
    "-50-500" can be parsed two different ways. An input with two readings is
    better dropped than guessed at.
    """
    if not isinstance(value, str):
        return None
    parts = value.split("-")
    if len(parts) != 2:
        return None
    a = _clean_float(parts[0], lo, hi)
    b = _clean_float(parts[1], lo, hi)
    if a is None or b is None:
        return None
    return (min(a, b), max(a, b))


def decode(params: dict) -> dict:
    """Turn URL params into session_state updates.

    Only valid keys are returned; the rest are left out, so one bad param
    cannot spoil the whole view.
    """
    out = {}
    if not isinstance(params, dict):
        return out

    underlying = _clean_symbol(params.get(KEY_UNDERLYING))
    if underlying:
        out["underlying"] = underlying

    expiry = _clean_expiry(params.get(KEY_EXPIRY))
    if expiry:
        out["expiry_api_date"] = expiry

    code = params.get(KEY_PRICE_MODE)
    if isinstance(code, str) and code.strip().lower() in PRICE_CODES:
        out["price_mode"] = PRICE_CODES[code.strip().lower()]

    fx = _clean_float(params.get(KEY_USDINR), USDINR_MIN, USDINR_MAX)
    if fx is not None:
        out["usdinr"] = fx

    band = _clean_band(params.get(KEY_DELTA_BAND))
    if band is not None:
        out["delta_band_main"] = (int(band[0]), int(band[1]))

    vol = _clean_band(params.get(KEY_VOL_BAND))
    if vol is not None:
        out["vol_regime_band"] = (int(vol[0]), int(vol[1]))

    return out


def encode(state: dict) -> dict:
    """Turn session_state into URL params.

    Only writes values that are present and understood, so the URL does not
    fill with empty noise like `?u=&e=&p=`.
    """
    out = {}
    if not isinstance(state, dict):
        return out

    underlying = _clean_symbol(state.get("underlying"))
    if underlying:
        out[KEY_UNDERLYING] = underlying

    expiry = _clean_expiry(state.get("expiry_api_date"))
    if expiry:
        out[KEY_EXPIRY] = expiry

    label = state.get("price_mode")
    if label in PRICE_LABELS:
        out[KEY_PRICE_MODE] = PRICE_LABELS[label]

    fx = _clean_float(state.get("usdinr"), USDINR_MIN, USDINR_MAX)
    if fx is not None:
        out[KEY_USDINR] = f"{fx:g}"

    for key, url_key in (("delta_band_main", KEY_DELTA_BAND),
                         ("vol_regime_band", KEY_VOL_BAND)):
        band = state.get(key)
        if isinstance(band, (tuple, list)) and len(band) == 2:
            cleaned = _clean_band(f"{band[0]}-{band[1]}")
            if cleaned is not None:
                out[url_key] = f"{cleaned[0]:g}-{cleaned[1]:g}"

    return out
