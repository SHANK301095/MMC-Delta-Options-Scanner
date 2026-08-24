"""
MMC Delta Scanner - Delta Exchange India API Client (READ ONLY)
===============================================================
This module ONLY touches public market-data endpoints. There is no API key,
no secret, no signing code anywhere in this project. It is structurally
incapable of placing an order.

Endpoints used (both public, no auth):
    GET /v2/products   -> contract specs: settlement_time, contract_value, tick_size
    GET /v2/tickers    -> live mark price, IV, greeks, OI, bid/ask

Rate limit budget (Delta: 10,000 weight per rolling 5-minute window):
    /v2/products  = weight 3   (cached 30 min -> ~8 calls/hour max)
    /v2/tickers   = weight 3   (cached per refresh bucket)
    At a 10-second refresh that is 30 calls/min = 90 weight/min = 450 per
    5-min window. Roughly 4.5% of the free quota. Comfortable headroom.
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

BASE_URL = "https://api.india.delta.exchange"

# Delta's CDN rejects requests with no User-Agent ("Request blocked by CDN").
# requests sets one by default, but we send an explicit identifiable string.
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "MMC-Delta-Scanner/1.0 python-requests",
}

# (connect timeout, read timeout) in seconds
TIMEOUT = (6, 25)

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


class DeltaApiError(RuntimeError):
    """Raised for any non-recoverable API problem, with a human-readable message."""


# --------------------------------------------------------------------------
# Low-level HTTP
# --------------------------------------------------------------------------

def _get(path: str, params: dict | None = None) -> dict:
    """Single GET with explicit, readable failure messages.

    Every failure mode is translated into plain language because the person
    running this scanner is a trader, not a backend engineer staring at a
    raw requests traceback at 3 AM.
    """
    url = BASE_URL + path
    try:
        resp = requests.get(url, params=params or {},
                            headers=HEADERS, timeout=TIMEOUT)
    except requests.exceptions.ConnectTimeout as exc:
        raise DeltaApiError(
            "Could not connect to Delta (connect timeout). "
            "Check your internet connection, or Delta may be down."
        ) from exc
    except requests.exceptions.ReadTimeout as exc:
        raise DeltaApiError(
            "Delta did not respond within 25 seconds (read timeout). "
            "Increase the refresh interval and try again."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise DeltaApiError(
            "Network error - could not reach api.india.delta.exchange. "
            "Check your WiFi, VPN or firewall."
        ) from exc

    if resp.status_code == 429:
        reset_ms = resp.headers.get("X-RATE-LIMIT-RESET", "?")
        raise DeltaApiError(
            f"Rate limit hit (HTTP 429). Delta's quota is per 5-minute window. "
            f"Resets in ~{reset_ms} ms. Increase the refresh interval in the "
            f"sidebar."
        )
    if resp.status_code == 403:
        raise DeltaApiError(
            "HTTP 403 - the request was blocked by the CDN. "
            "If you are running through a VPN or proxy, turn it off and retry."
        )
    if resp.status_code >= 500:
        raise DeltaApiError(
            f"Delta server error (HTTP {resp.status_code}). "
            "This is an issue on their side - try again shortly."
        )
    if resp.status_code != 200:
        raise DeltaApiError(f"Unexpected HTTP {resp.status_code} from {path}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise DeltaApiError(f"{path} did not return valid JSON.") from exc

    if not data.get("success", False):
        err = data.get("error", {})
        code = err.get("code") if isinstance(err, dict) else err
        raise DeltaApiError(f"Delta API returned an error: {code}")

    return data


# --------------------------------------------------------------------------
# Safe parsing helpers
# --------------------------------------------------------------------------

def to_float(value, default=float("nan")) -> float:
    """Delta sends big decimals as STRINGS to preserve precision. Convert safely."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(out) or math.isinf(out):
        return default
    return out


def parse_iso_utc(value) -> datetime | None:
    """Parse Delta's ISO timestamps into timezone-aware UTC datetimes."""
    if not value or not isinstance(value, str):
        return None
    txt = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(txt, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_option_symbol(symbol: str) -> dict | None:
    """Decode C-BTC-95000-310126 into its parts.

    Delta option symbol format: <C|P>-<UNDERLYING>-<STRIKE>-<DDMMYY>
    Expiry is at 12:00:00 UTC (17:30 IST) on that date.

    This is the FALLBACK path. settlement_time from /v2/products is
    authoritative and is preferred whenever it is available.
    """
    if not symbol or not isinstance(symbol, str):
        return None
    parts = symbol.split("-")
    if len(parts) != 4:
        return None

    opt_type, underlying, strike_txt, ddmmyy = parts
    if opt_type not in ("C", "P"):
        return None
    if len(ddmmyy) != 6 or not ddmmyy.isdigit():
        return None

    try:
        strike = float(strike_txt)
        day = int(ddmmyy[0:2])
        month = int(ddmmyy[2:4])
        year = 2000 + int(ddmmyy[4:6])
        expiry = datetime(year, month, day, 12, 0, 0, tzinfo=UTC)
    except (ValueError, TypeError):
        return None

    return {
        "is_call": opt_type == "C",
        "underlying": underlying,
        "strike": strike,
        "expiry_utc": expiry,
    }


def fmt_ist(dt: datetime | None) -> str:
    """Render a UTC datetime in IST for display."""
    if dt is None:
        return "-"
    return dt.astimezone(IST).strftime("%d-%b-%Y %H:%M IST")


def humanize_countdown(seconds: float) -> str:
    """3d 04h 12m style countdown."""
    if seconds is None or seconds <= 0:
        return "EXPIRED"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


# --------------------------------------------------------------------------
# Products (contract specs) - slow-moving, cached 30 minutes
# --------------------------------------------------------------------------

@st.cache_data(ttl=1800, show_spinner=False, max_entries=4)
def fetch_option_products() -> pd.DataFrame:
    """All LIVE option contracts with their specs.

    Returns a DataFrame indexed by symbol with:
        underlying, strike, is_call, expiry_utc, contract_value, tick_size

    Paginated: Delta returns 100 per page by default; we request 500 and
    follow the 'after' cursor until exhausted (hard-capped at 40 pages so a
    cursor bug can never become an infinite loop).
    """
    rows = []
    after = None

    for _ in range(40):
        params = {
            "contract_types": "call_options,put_options",
            "states": "live",
            "page_size": 500,
        }
        if after:
            params["after"] = after

        data = _get("/v2/products", params)
        result = data.get("result") or []
        if not result:
            break

        for p in result:
            symbol = p.get("symbol")
            if not symbol:
                continue

            parsed = parse_option_symbol(symbol) or {}

            expiry = parse_iso_utc(p.get("settlement_time")) or parsed.get("expiry_utc")
            if expiry is None:
                continue  # cannot compute time-to-expiry -> useless for decay math

            underlying_obj = p.get("underlying_asset") or {}
            underlying = (underlying_obj.get("symbol")
                          or parsed.get("underlying") or "")

            contract_value = to_float(p.get("contract_value"), default=float("nan"))
            strike = to_float(p.get("strike_price"),
                              default=parsed.get("strike", float("nan")))
            is_call = p.get("contract_type") == "call_options"

            rows.append({
                "symbol": symbol,
                "underlying": underlying,
                "strike": strike,
                "is_call": is_call,
                "expiry_utc": expiry,
                "contract_value": contract_value,
                "tick_size": to_float(p.get("tick_size")),
            })

        meta = data.get("meta") or {}
        after = meta.get("after")
        if not after:
            break

    if not rows:
        raise DeltaApiError(
            "Delta returned no live option contracts. "
            "That is unusual - check the Delta status page."
        )

    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["symbol"]).reset_index(drop=True)


def list_underlyings(products: pd.DataFrame) -> list:
    """Underlyings that actually have live options right now."""
    vals = sorted({u for u in products["underlying"].dropna().tolist() if u})
    preferred = [u for u in ("BTC", "ETH") if u in vals]
    return preferred + [u for u in vals if u not in preferred]


def list_expiries(products: pd.DataFrame, underlying: str) -> list:
    """Future expiries for one underlying, soonest first.

    Each entry: {expiry_utc, api_date (DD-MM-YYYY), label, strikes, seconds_left}
    """
    now = datetime.now(UTC)
    subset = products[products["underlying"] == underlying]
    if subset.empty:
        return []

    out = []
    for expiry, grp in subset.groupby("expiry_utc"):
        seconds_left = (expiry - now).total_seconds()
        if seconds_left <= 0:
            continue
        out.append({
            "expiry_utc": expiry,
            "api_date": expiry.astimezone(UTC).strftime("%d-%m-%Y"),
            "strikes": int(grp["strike"].nunique()),
            "seconds_left": seconds_left,
            "label": (f"{expiry.astimezone(IST).strftime('%d-%b-%Y')}  "
                      f"({humanize_countdown(seconds_left)} left, "
                      f"{int(grp['strike'].nunique())} strikes)"),
        })

    return sorted(out, key=lambda x: x["seconds_left"])


# --------------------------------------------------------------------------
# Tickers (live chain) - fast-moving, cached per refresh bucket
# --------------------------------------------------------------------------

@st.cache_data(ttl=600, show_spinner=False, max_entries=40)
def fetch_chain_raw(underlying: str, api_date: str, cache_bucket: int) -> list:
    """Raw ticker list for one underlying + one expiry.

    cache_bucket is int(time.time() // refresh_seconds). It is not used inside
    the function - its only job is to change the cache key when the refresh
    window rolls over. That gives us a user-adjustable refresh interval
    without hammering Delta on every widget interaction.
    """
    _ = cache_bucket  # intentionally unused - cache key only
    params = {
        "contract_types": "call_options,put_options",
        "underlying_asset_symbols": underlying,
        "expiry_date": api_date,
    }
    data = _get("/v2/tickers", params)
    return data.get("result") or []


def make_cache_bucket(refresh_seconds: int) -> int:
    """Current refresh window index."""
    refresh_seconds = max(1, int(refresh_seconds))
    return int(time.time() // refresh_seconds)


# --------------------------------------------------------------------------
# Normalization - turn Delta's mixed-type JSON into one clean DataFrame
# --------------------------------------------------------------------------

def _pick_iv_raw(ticker: dict) -> float:
    """Delta has used both 'mark_iv' and 'mark_vol' across versions/endpoints.

    Try mark_iv first, then mark_vol, then fall back to the midpoint of the
    quoted bid_iv / ask_iv. Whatever we find is still RAW - the percent vs
    decimal question is settled later by detect_iv_scale().
    """
    for key in ("mark_iv", "mark_vol"):
        val = to_float(ticker.get(key))
        if not math.isnan(val) and val > 0:
            return val

    quotes = ticker.get("quotes") or {}
    bid_iv = to_float(quotes.get("bid_iv"))
    ask_iv = to_float(quotes.get("ask_iv"))
    valid = [v for v in (bid_iv, ask_iv) if not math.isnan(v) and v > 0]
    if valid:
        return sum(valid) / len(valid)
    return float("nan")


def normalize_chain(raw_tickers: list, products: pd.DataFrame) -> pd.DataFrame:
    """Flatten raw tickers into a typed DataFrame and attach contract specs.

    Output columns:
        symbol, is_call, strike, expiry_utc, contract_value,
        mark_price, spot_price, iv_raw,
        api_delta, api_gamma, api_theta, api_vega, api_rho,
        best_bid, best_ask, bid_size, ask_size, mid, spread_abs, spread_pct,
        oi_contracts, oi_value_usd, volume, turnover_usd, ticker_time_utc
    """
    if not raw_tickers:
        return pd.DataFrame()

    spec = products.set_index("symbol") if not products.empty else pd.DataFrame()
    rows = []

    for t in raw_tickers:
        symbol = t.get("symbol")
        if not symbol:
            continue

        contract_type = t.get("contract_type")
        if contract_type not in ("call_options", "put_options"):
            continue  # defensive: never let a perp leak into an options chain

        parsed = parse_option_symbol(symbol) or {}

        # Contract specs: products endpoint wins, symbol parsing is the fallback.
        if not spec.empty and symbol in spec.index:
            row_spec = spec.loc[symbol]
            expiry = row_spec["expiry_utc"]
            contract_value = to_float(row_spec["contract_value"])
            strike = to_float(row_spec["strike"])
        else:
            expiry = parsed.get("expiry_utc")
            contract_value = float("nan")
            strike = parsed.get("strike", float("nan"))

        if math.isnan(strike):
            strike = to_float(t.get("strike_price"))
        if expiry is None:
            continue

        greeks = t.get("greeks") or {}
        quotes = t.get("quotes") or {}

        best_bid = to_float(quotes.get("best_bid"))
        best_ask = to_float(quotes.get("best_ask"))

        # A one-sided book is NOT tradable. Treat it as missing, not as zero.
        if not math.isnan(best_bid) and not math.isnan(best_ask) \
                and best_bid > 0 and best_ask > 0 and best_ask >= best_bid:
            mid = 0.5 * (best_bid + best_ask)
            spread_abs = best_ask - best_bid
            spread_pct = (spread_abs / mid * 100.0) if mid > 0 else float("nan")
        else:
            mid = spread_abs = spread_pct = float("nan")

        # Delta reports API timestamps in MICROseconds.
        ts_raw = t.get("timestamp")
        ticker_time = None
        if ts_raw:
            try:
                ticker_time = datetime.fromtimestamp(float(ts_raw) / 1e6, tz=UTC)
            except (ValueError, OSError, OverflowError):
                ticker_time = None

        oi_contracts = to_float(t.get("oi_contracts"))
        if math.isnan(oi_contracts):
            oi_contracts = to_float(t.get("oi"))

        rows.append({
            "symbol": symbol,
            "is_call": contract_type == "call_options",
            "strike": strike,
            "expiry_utc": expiry,
            "contract_value": contract_value,
            "mark_price": to_float(t.get("mark_price")),
            "spot_price": to_float(t.get("spot_price")),
            "iv_raw": _pick_iv_raw(t),
            "api_delta": to_float(greeks.get("delta")),
            "api_gamma": to_float(greeks.get("gamma")),
            "api_theta": to_float(greeks.get("theta")),
            "api_vega": to_float(greeks.get("vega")),
            "api_rho": to_float(greeks.get("rho")),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "bid_size": to_float(quotes.get("bid_size")),
            "ask_size": to_float(quotes.get("ask_size")),
            "mid": mid,
            "spread_abs": spread_abs,
            "spread_pct": spread_pct,
            "oi_contracts": oi_contracts,
            "oi_value_usd": to_float(t.get("oi_value_usd")),
            "volume": to_float(t.get("volume")),
            "turnover_usd": to_float(t.get("turnover_usd")),
            "ticker_time_utc": ticker_time,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    return df.sort_values(["strike", "is_call"]).reset_index(drop=True)


def resolve_spot(df: pd.DataFrame) -> float:
    """One spot price for the whole chain.

    Uses the MEDIAN of every row's spot_price rather than the first row:
    a single stale strike cannot then poison every downstream greek.
    """
    if df.empty or "spot_price" not in df.columns:
        return float("nan")
    vals = df["spot_price"].dropna()
    vals = vals[vals > 0]
    if vals.empty:
        return float("nan")
    return float(vals.median())


def resolve_contract_value(df: pd.DataFrame, underlying: str) -> float:
    """Contract multiplier, with a hard-coded fallback per Delta's spec sheet."""
    if not df.empty and "contract_value" in df.columns:
        vals = df["contract_value"].dropna()
        vals = vals[vals > 0]
        if not vals.empty:
            return float(vals.mode().iloc[0])
    return {"BTC": 0.001, "ETH": 0.01}.get(underlying, 1.0)
