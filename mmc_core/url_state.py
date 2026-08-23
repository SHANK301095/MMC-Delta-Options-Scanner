"""
MMC Delta Scanner — View state in the URL
=========================================
Jo aap dekh rahe hain wo URL mein likha rehta hai. Iska matlab:

  * Page reload karne par wahi view wapas aata hai
  * Link bookmark kar sakte hain — "BTC, agli expiry, 15-25Δ" ek URL ban jaata hai
  * Wahi link kisi aur ko bhej dijiye, unhe bilkul wahi screen dikhegi

Ye ek server-side settings file se behtar hai, khaas kar deployed app par. Ek
Streamlit app ek hi process hota hai jise sab visitors share karte hain, to
server par "save" kiya gaya setting sabka setting ban jaata hai. URL har
browser ka apna hai — koi kisi ka view nahi badal sakta.

URL PARAMS BAHAR SE AATE HAIN
-----------------------------
Koi bhi kuch bhi type kar ke bhej sakta hai. Isliye har value validate hoti
hai aur galat value CHUP-CHAAP GIRA DI jaati hai, guess nahi ki jaati:
`?u=<script>` par app default underlying par chalta hai, kuch fatta nahi.
Numbers apni haddon mein clamp hote hain.
"""

from __future__ import annotations

import math

# Short keys jaan-boojh kar — URL padhne aur bhejne layak rehna chahiye.
KEY_UNDERLYING = "u"
KEY_EXPIRY = "e"
KEY_PRICE_MODE = "p"
KEY_USDINR = "fx"
KEY_DELTA_BAND = "d"
KEY_VOL_BAND = "v"

# URL par chhote codes, session_state mein poore labels.
PRICE_CODES = {"realistic": "Realistic (buy ask / sell bid)",
               "mid": "Mid",
               "mark": "Mark"}
PRICE_LABELS = {v: k for k, v in PRICE_CODES.items()}

USDINR_MIN, USDINR_MAX = 50.0, 150.0


def _clean_symbol(value) -> str | None:
    """Underlying jaisa ek chhota alphanumeric symbol, ya None."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if not text or len(text) > 12 or not text.isalnum():
        return None
    return text


def _clean_expiry(value) -> str | None:
    """DD-MM-YYYY — wahi shakl jo Delta ka API leta hai."""
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
    """"15-25" -> (15.0, 25.0). Ulta diya ho to seedha kar deta hai.

    Negative values jaan-boojh kar reject hote hain, clamp nahi. Jin sliders ko
    ye band feed karta hai wo 0-100 par hain, to "-50" ka koi matlab hi nahi —
    aur "-50-500" jaisi string do tarah se padhi ja sakti hai. Do matlab wali
    input ko guess karne se behtar hai use gira dena.
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
    """URL params se session_state ke updates.

    Sirf wahi keys lautati hai jo valid hain — baaki chhod di jaati hain, taaki
    ek galat param poore view ko na bigaade.
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
    """session_state se URL params.

    Sirf wahi likhta hai jo maujood aur samajh mein aata ho, taaki URL
    `?u=&e=&p=` jaise khaali kachre se na bhare.
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
