"""Tests for the Delta Exchange API client's parsing and normalization.

No network call happens here - only the layer that turns Delta's mixed-type
JSON into a clean DataFrame is tested. Delta sends large decimals as STRINGS and
timestamps in MICROseconds, so every type assumption is pinned down here.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from mmc_core import delta_api as api

UTC = timezone.utc


# --------------------------------------------------------------- to_float

@pytest.mark.parametrize("raw, expected", [
    ("112500.5", 112500.5),      # Delta sends these as strings
    (42, 42.0),
    (3.5, 3.5),
    ("-0.25", -0.25),
])
def test_to_float_parses_numbers_and_numeric_strings(raw, expected):
    assert api.to_float(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", True, False,
                                 float("nan"), float("inf")])
def test_to_float_rejects_junk(raw):
    assert math.isnan(api.to_float(raw))


def test_to_float_honours_custom_default():
    assert api.to_float(None, default=0.0) == 0.0


# ------------------------------------------------------- symbol decoding

def test_parse_option_symbol_decodes_a_call():
    out = api.parse_option_symbol("C-BTC-95000-310126")
    assert out["is_call"] is True
    assert out["underlying"] == "BTC"
    assert out["strike"] == 95000.0
    assert out["expiry_utc"] == datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


def test_parse_option_symbol_decodes_a_put():
    assert api.parse_option_symbol("P-ETH-3000-010226")["is_call"] is False


def test_expiry_from_symbol_is_1730_ist():
    """Delta India options settle at 17:30 IST, which is 12:00 UTC."""
    expiry = api.parse_option_symbol("C-BTC-95000-310126")["expiry_utc"]
    assert expiry.astimezone(api.IST).strftime("%H:%M") == "17:30"


@pytest.mark.parametrize("symbol", [
    "BTCUSD",                 # a perpetual, not an option
    "X-BTC-95000-310126",     # invalid option type
    "C-BTC-95000",            # parts kam
    "C-BTC-95000-3101266",    # date lamba
    "C-BTC-95000-AB0126",     # non-numeric date
    "C-BTC-abc-310126",       # non-numeric strike
    "",
    None,
])
def test_parse_option_symbol_rejects_malformed_input(symbol):
    assert api.parse_option_symbol(symbol) is None


# ----------------------------------------------------------- timestamps

def test_parse_iso_utc_handles_z_suffix():
    assert api.parse_iso_utc("2026-01-31T12:00:00Z") == \
        datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


def test_parse_iso_utc_assumes_utc_when_no_offset():
    assert api.parse_iso_utc("2026-01-31T12:00:00") == \
        datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


def test_parse_iso_utc_converts_other_offsets_to_utc():
    assert api.parse_iso_utc("2026-01-31T17:30:00+05:30") == \
        datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("raw", [None, "", "not-a-date", 12345])
def test_parse_iso_utc_rejects_junk(raw):
    assert api.parse_iso_utc(raw) is None


@pytest.mark.parametrize("seconds, expected", [
    (0, "EXPIRED"),
    (-5, "EXPIRED"),
    (90, "1m"),
    (3 * 3600 + 12 * 60, "3h 12m"),
    (3 * 86400 + 4 * 3600 + 12 * 60, "3d 04h 12m"),
])
def test_humanize_countdown(seconds, expected):
    assert api.humanize_countdown(seconds) == expected


# ------------------------------------------------------- normalize_chain

def _products() -> pd.DataFrame:
    return pd.DataFrame([
        {"symbol": "C-BTC-100000-310126", "underlying": "BTC",
         "strike": 100000.0, "is_call": True,
         "expiry_utc": datetime(2026, 1, 31, 12, 0, tzinfo=UTC),
         "contract_value": 0.001, "tick_size": 0.1},
        {"symbol": "P-BTC-100000-310126", "underlying": "BTC",
         "strike": 100000.0, "is_call": False,
         "expiry_utc": datetime(2026, 1, 31, 12, 0, tzinfo=UTC),
         "contract_value": 0.001, "tick_size": 0.1},
    ])


def _ticker(symbol="C-BTC-100000-310126", contract_type="call_options",
            bid="95.0", ask="105.0", **over) -> dict:
    t = {
        "symbol": symbol,
        "contract_type": contract_type,
        "mark_price": "100.0",
        "spot_price": "99500.0",
        "mark_iv": "55.0",
        "greeks": {"delta": "0.52", "gamma": "0.00001",
                   "theta": "-12.5", "vega": "8.1", "rho": "0.4"},
        "quotes": {"best_bid": bid, "best_ask": ask,
                   "bid_size": "10", "ask_size": "12"},
        "oi_contracts": "1500",
        "oi_value_usd": "150000",
        "volume": "320",
        "turnover_usd": "32000",
        "timestamp": 1_767_182_400_000_000,   # MICROseconds
    }
    t.update(over)
    return t


def test_normalize_chain_produces_typed_columns():
    df = api.normalize_chain([_ticker()], _products())
    assert len(df) == 1
    row = df.iloc[0]
    assert row["is_call"] is True or row["is_call"] == True  # noqa: E712
    assert row["strike"] == 100000.0
    assert row["mark_price"] == 100.0        # parsed from a string
    assert row["iv_raw"] == 55.0             # stays raw; scale resolved later
    assert row["oi_contracts"] == 1500.0
    assert row["contract_value"] == 0.001


def test_normalize_chain_computes_mid_and_spread_on_two_sided_book():
    row = api.normalize_chain([_ticker(bid="95.0", ask="105.0")],
                              _products()).iloc[0]
    assert row["mid"] == 100.0
    assert row["spread_abs"] == 10.0
    assert row["spread_pct"] == pytest.approx(10.0)


@pytest.mark.parametrize("bid, ask", [
    (None, "105.0"),      # ask only
    ("95.0", None),       # bid only
    ("0", "105.0"),       # zero bid
    ("105.0", "95.0"),    # crossed book
])
def test_one_sided_or_crossed_book_gives_nan_mid_not_zero(bid, ask):
    """A one-sided book is NOT tradable. Treating it as zero is the most
    expensive bug available: the scanner would read it as a perfect strike with
    a 0% spread."""
    row = api.normalize_chain([_ticker(bid=bid, ask=ask)], _products()).iloc[0]
    assert math.isnan(row["mid"])
    assert math.isnan(row["spread_pct"])


def test_normalize_chain_drops_non_option_contracts():
    """A perpetual future must never leak into an options chain."""
    perp = _ticker(symbol="BTCUSD", contract_type="perpetual_futures")
    assert api.normalize_chain([perp], _products()).empty


def test_normalize_chain_skips_rows_without_a_symbol():
    assert api.normalize_chain([{"contract_type": "call_options"}],
                               _products()).empty


def test_normalize_chain_parses_microsecond_timestamps():
    row = api.normalize_chain([_ticker()], _products()).iloc[0]
    assert row["ticker_time_utc"] == datetime.fromtimestamp(
        1_767_182_400_000_000 / 1e6, tz=UTC)


def test_normalize_chain_survives_a_bad_timestamp():
    row = api.normalize_chain([_ticker(timestamp="garbage")],
                              _products()).iloc[0]
    assert row["ticker_time_utc"] is None


def test_normalize_chain_falls_back_to_symbol_when_product_missing():
    """When absent from the products endpoint, specs must come from the symbol."""
    row = api.normalize_chain([_ticker()], pd.DataFrame(columns=["symbol"])).iloc[0]
    assert row["strike"] == 100000.0
    assert math.isnan(row["contract_value"])


def test_normalize_chain_uses_mark_vol_when_mark_iv_absent():
    t = _ticker()
    del t["mark_iv"]
    t["mark_vol"] = "61.0"
    assert api.normalize_chain([t], _products()).iloc[0]["iv_raw"] == 61.0


def test_normalize_chain_falls_back_to_quoted_iv_midpoint():
    t = _ticker()
    del t["mark_iv"]
    t["quotes"]["bid_iv"] = "50.0"
    t["quotes"]["ask_iv"] = "60.0"
    assert api.normalize_chain([t], _products()).iloc[0]["iv_raw"] == 55.0


def test_normalize_chain_on_empty_input():
    assert api.normalize_chain([], _products()).empty


# --------------------------------------------------------------- resolvers

def test_resolve_spot_uses_median_so_one_stale_row_cannot_poison_it():
    tickers = [
        _ticker(symbol="C-BTC-100000-310126", spot_price="99500.0"),
        _ticker(symbol="P-BTC-100000-310126", contract_type="put_options",
                spot_price="99600.0"),
    ]
    df = api.normalize_chain(tickers, _products())
    # Force in a badly stale row - a median makes it harmless.
    df.loc[len(df)] = df.iloc[0].copy()
    df.loc[len(df) - 1, "spot_price"] = 5.0
    assert 99_000.0 < api.resolve_spot(df) < 100_000.0


def test_resolve_spot_on_empty_frame_is_nan():
    assert math.isnan(api.resolve_spot(pd.DataFrame()))


def test_resolve_contract_value_prefers_the_chain():
    df = api.normalize_chain([_ticker()], _products())
    assert api.resolve_contract_value(df, "BTC") == 0.001


@pytest.mark.parametrize("underlying, expected", [
    ("BTC", 0.001), ("ETH", 0.01), ("SOL", 1.0),
])
def test_resolve_contract_value_falls_back_per_underlying(underlying, expected):
    assert api.resolve_contract_value(pd.DataFrame(), underlying) == expected


# ---------------------------------------------------------------- expiries

def test_list_expiries_drops_past_expiries_and_sorts_soonest_first():
    now = datetime.now(UTC)
    products = pd.DataFrame([
        {"symbol": "C-BTC-1-a", "underlying": "BTC", "strike": 1.0, "is_call": True,
         "expiry_utc": now - timedelta(days=1), "contract_value": 0.001,
         "tick_size": 0.1},
        {"symbol": "C-BTC-2-b", "underlying": "BTC", "strike": 2.0, "is_call": True,
         "expiry_utc": now + timedelta(days=7), "contract_value": 0.001,
         "tick_size": 0.1},
        {"symbol": "C-BTC-3-c", "underlying": "BTC", "strike": 3.0, "is_call": True,
         "expiry_utc": now + timedelta(days=2), "contract_value": 0.001,
         "tick_size": 0.1},
    ])
    out = api.list_expiries(products, "BTC")
    assert len(out) == 2                       # beeta hua expiry hat gaya
    assert out[0]["seconds_left"] < out[1]["seconds_left"]
    assert out[0]["api_date"] == (now + timedelta(days=2)).strftime("%d-%m-%Y")


def test_list_expiries_for_unknown_underlying_is_empty():
    assert api.list_expiries(_products(), "DOGE") == []


def test_list_underlyings_puts_btc_and_eth_first():
    products = pd.DataFrame({
        "underlying": ["SOL", "ETH", "BTC", "XRP"],
        "symbol": ["a", "b", "c", "d"],
    })
    assert api.list_underlyings(products)[:2] == ["BTC", "ETH"]
