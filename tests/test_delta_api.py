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
import requests

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


# ================================================================== HTTP layer
#
# Nothing below touches the network: requests.get is replaced, and the retry
# loop's sleep and clock are replaced too, so a test that exercises a 30-second
# budget still runs in microseconds.


class _FakeResponse:
    """The slice of requests.Response that _attempt actually reads."""

    def __init__(self, status_code=200, payload=None, headers=None,
                 bad_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"success": True,
                                                             "result": []}
        self.headers = headers or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def no_sleep(monkeypatch):
    """Run the retry loop on a fake clock; record what it would have slept."""
    slept = []
    clock = {"t": 0.0}

    def fake_sleep(seconds):
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(api, "_sleep", fake_sleep)
    monkeypatch.setattr(api, "_now", lambda: clock["t"])
    return slept, clock


def _responder(monkeypatch, *outcomes):
    """Serve one outcome per call; an Exception instance is raised, else returned.

    The last outcome repeats, so a test can say "fails forever" with one entry.
    """
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params})
        item = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(api.requests, "get", fake_get)
    return calls


# ---------------------------------------------------------------- happy path

def test_get_returns_payload_and_hits_the_expected_url(monkeypatch, no_sleep):
    calls = _responder(monkeypatch,
                       _FakeResponse(payload={"success": True, "result": [1]}))

    data = api._get("/v2/products", {"states": "live"})

    assert data == {"success": True, "result": [1]}
    assert calls[0]["url"] == api.BASE_URL + "/v2/products"
    assert calls[0]["params"] == {"states": "live"}
    assert len(calls) == 1, "a successful call must not be retried"


# ------------------------------------------------------ permanent failures
#
# These must NOT be retried. Retrying a 429 in particular makes the very
# problem it reports worse.

def test_rate_limit_is_not_retried_and_says_when_the_quota_resets(monkeypatch,
                                                                  no_sleep):
    calls = _responder(monkeypatch, _FakeResponse(
        status_code=429, headers={"X-RATE-LIMIT-RESET": "4200"}))

    with pytest.raises(api.DeltaApiError) as err:
        api._get("/v2/tickers")

    assert len(calls) == 1, "retrying a rate limit would deepen the problem"
    assert "429" in str(err.value)
    assert "4200" in str(err.value)


def test_cdn_block_is_not_retried(monkeypatch, no_sleep):
    calls = _responder(monkeypatch, _FakeResponse(status_code=403))

    with pytest.raises(api.DeltaApiError, match="403"):
        api._get("/v2/products")

    assert len(calls) == 1


def test_unexpected_status_is_not_retried(monkeypatch, no_sleep):
    calls = _responder(monkeypatch, _FakeResponse(status_code=418))

    with pytest.raises(api.DeltaApiError, match="418"):
        api._get("/v2/products")

    assert len(calls) == 1


def test_malformed_json_is_not_retried(monkeypatch, no_sleep):
    calls = _responder(monkeypatch, _FakeResponse(bad_json=True))

    with pytest.raises(api.DeltaApiError, match="valid JSON"):
        api._get("/v2/products")

    assert len(calls) == 1


def test_api_level_error_surfaces_delta_s_own_code(monkeypatch, no_sleep):
    calls = _responder(monkeypatch, _FakeResponse(
        payload={"success": False, "error": {"code": "bad_symbol"}}))

    with pytest.raises(api.DeltaApiError, match="bad_symbol"):
        api._get("/v2/tickers")

    assert len(calls) == 1


def test_api_level_error_handles_a_non_dict_error_field(monkeypatch, no_sleep):
    _responder(monkeypatch,
               _FakeResponse(payload={"success": False, "error": "boom"}))

    with pytest.raises(api.DeltaApiError, match="boom"):
        api._get("/v2/tickers")


# ------------------------------------------------------- transient failures

@pytest.mark.parametrize("failure, expected", [
    (requests.exceptions.ConnectTimeout(), "connect timeout"),
    (requests.exceptions.ReadTimeout(), "read timeout"),
    (requests.exceptions.ConnectionError(), "Network error"),
])
def test_network_failures_are_retried_then_reported_in_plain_language(
        monkeypatch, no_sleep, failure, expected):
    calls = _responder(monkeypatch, failure)

    with pytest.raises(api.DeltaApiError) as err:
        api._get("/v2/products")

    assert len(calls) == api.MAX_ATTEMPTS
    assert expected in str(err.value)
    assert f"tried {api.MAX_ATTEMPTS} times" in str(err.value)


def test_server_error_is_retried(monkeypatch, no_sleep):
    calls = _responder(monkeypatch, _FakeResponse(status_code=503))

    with pytest.raises(api.DeltaApiError, match="503"):
        api._get("/v2/products")

    assert len(calls) == api.MAX_ATTEMPTS


def test_a_blip_recovers_without_the_caller_ever_seeing_it(monkeypatch,
                                                           no_sleep):
    """The whole point of the retry: one bad response must not fail the page."""
    calls = _responder(
        monkeypatch,
        _FakeResponse(status_code=502),
        _FakeResponse(payload={"success": True, "result": ["recovered"]}),
    )

    data = api._get("/v2/products")

    assert data["result"] == ["recovered"]
    assert len(calls) == 2


def test_backoff_grows_between_attempts(monkeypatch, no_sleep):
    slept, _ = no_sleep
    _responder(monkeypatch, _FakeResponse(status_code=500))

    with pytest.raises(api.DeltaApiError):
        api._get("/v2/products")

    assert slept == list(api.RETRY_BACKOFF_SECONDS[:api.MAX_ATTEMPTS - 1])
    assert slept == sorted(slept), "backoff must not shrink"


def test_retry_stops_when_the_time_budget_is_spent(monkeypatch, no_sleep):
    """A slow failure must not be retried into a minute of dead UI.

    Each attempt here burns a full read timeout, so the budget runs out before
    the attempt cap does and the loop gives up early - by design.
    """
    slept, clock = no_sleep

    def slow_get(url, params=None, headers=None, timeout=None):
        clock["t"] += api.TIMEOUT[1]        # this attempt took a read timeout
        raise requests.exceptions.ReadTimeout()

    monkeypatch.setattr(api.requests, "get", slow_get)

    with pytest.raises(api.DeltaApiError):
        api._get("/v2/products")

    assert clock["t"] <= api.RETRY_BUDGET_SECONDS + api.TIMEOUT[1], (
        "the user must never wait longer than the budget plus one attempt")
    assert slept == [], "no retry should have been started at all"


# ============================================== product catalogue pagination
#
# Delta pages /v2/products with an opaque 'after' cursor. The loop that follows
# it is the one place where a silently truncated catalogue would poison every
# downstream number, so its cursor handling and its infinite-loop guard are
# pinned down here. _get is replaced, so no network call happens.

def _product(symbol, strike, call=True, underlying="BTC",
             settlement="2030-01-31T12:00:00Z", contract_value="0.001"):
    return {
        "symbol": symbol,
        "contract_type": "call_options" if call else "put_options",
        "strike_price": str(strike),
        "settlement_time": settlement,
        "underlying_asset": {"symbol": underlying},
        "contract_value": contract_value,
        "tick_size": "0.1",
    }


def _pages(monkeypatch, *pages):
    """Serve /v2/products pages in order; record the params of each call."""
    seen = []

    def fake_get(path, params=None):
        seen.append(params or {})
        return pages[min(len(seen) - 1, len(pages) - 1)]

    monkeypatch.setattr(api, "_get", fake_get)
    return seen


def _fetch_products():
    """Call through the cache decorator so each test starts cold."""
    api.fetch_option_products.clear()
    return api.fetch_option_products()


def test_products_follows_the_after_cursor_across_pages(monkeypatch):
    seen = _pages(
        monkeypatch,
        {"result": [_product("C-BTC-90000-310130", 90000)],
         "meta": {"after": "cursor-1"}},
        {"result": [_product("C-BTC-95000-310130", 95000)],
         "meta": {"after": None}},
    )

    df = _fetch_products()

    assert len(df) == 2
    assert sorted(df["strike"]) == [90000.0, 95000.0]
    assert "after" not in seen[0], "the first page must not send a cursor"
    assert seen[1]["after"] == "cursor-1", "page 2 must send page 1's cursor"


def test_products_stops_on_an_empty_page(monkeypatch):
    seen = _pages(
        monkeypatch,
        {"result": [_product("C-BTC-90000-310130", 90000)],
         "meta": {"after": "cursor-1"}},
        {"result": [], "meta": {"after": "cursor-2"}},
    )

    df = _fetch_products()

    assert len(df) == 1
    assert len(seen) == 2, "an empty page ends the walk even with a cursor"


def test_products_cannot_loop_forever_on_a_repeating_cursor(monkeypatch):
    """A server bug that always returns the same cursor must still terminate.

    The fake server refuses to answer past a hard ceiling well above the page
    cap. Without the cap this test fails on that refusal instead of hanging:
    a test that detects a runaway loop by running forever is useless in CI,
    because it burns the whole job timeout rather than reporting anything.
    """
    ceiling = 100
    calls = {"n": 0}

    def endless_get(path, params=None):
        calls["n"] += 1
        if calls["n"] > ceiling:
            raise AssertionError(
                f"fetch_option_products asked for more than {ceiling} pages - "
                "the page cap that stops an endless cursor is gone")
        return {"result": [_product("C-BTC-90000-310130", 90000)],
                "meta": {"after": "same-cursor-every-time"}}

    monkeypatch.setattr(api, "_get", endless_get)

    df = _fetch_products()

    assert calls["n"] == 40, "the page cap must stop an endless cursor"
    assert len(df) == 1, "duplicate symbols collapse to one row"


def test_products_skips_contracts_with_no_usable_expiry(monkeypatch):
    """Without an expiry there is no time to expiry, so the row is useless."""
    _pages(monkeypatch, {
        "result": [
            _product("C-BTC-90000-310130", 90000),
            {"symbol": "JUNK-NO-EXPIRY", "contract_type": "call_options",
             "strike_price": "1", "settlement_time": None,
             "underlying_asset": {"symbol": "BTC"}},
        ],
        "meta": {"after": None},
    })

    df = _fetch_products()

    assert list(df["symbol"]) == ["C-BTC-90000-310130"]


def test_products_skips_entries_with_no_symbol(monkeypatch):
    _pages(monkeypatch, {
        "result": [_product("C-BTC-90000-310130", 90000), {"strike_price": "1"}],
        "meta": {"after": None},
    })

    assert len(_fetch_products()) == 1


def test_products_marks_puts_correctly(monkeypatch):
    _pages(monkeypatch, {
        "result": [_product("P-BTC-90000-310130", 90000, call=False)],
        "meta": {"after": None},
    })

    df = _fetch_products()

    assert bool(df.iloc[0]["is_call"]) is False


def test_products_raises_a_readable_error_when_nothing_comes_back(monkeypatch):
    _pages(monkeypatch, {"result": [], "meta": {}})

    with pytest.raises(api.DeltaApiError, match="no live option contracts"):
        _fetch_products()


def test_products_requests_live_options_only(monkeypatch):
    seen = _pages(monkeypatch, {
        "result": [_product("C-BTC-90000-310130", 90000)],
        "meta": {"after": None},
    })

    _fetch_products()

    assert seen[0]["states"] == "live"
    assert seen[0]["contract_types"] == "call_options,put_options"


# ------------------------------------------------------------- chain tickers

def test_chain_raw_asks_for_both_sides_of_one_expiry(monkeypatch):
    seen = {}

    def fake_get(path, params=None):
        seen["path"] = path
        seen["params"] = params
        return {"result": [{"symbol": "C-BTC-90000-310130"}]}

    monkeypatch.setattr(api, "_get", fake_get)
    api.fetch_chain_raw.clear()

    rows = api.fetch_chain_raw("BTC", "31-01-2030", 1)

    assert rows == [{"symbol": "C-BTC-90000-310130"}]
    assert seen["path"] == "/v2/tickers"
    assert seen["params"]["underlying_asset_symbols"] == "BTC"
    assert seen["params"]["expiry_date"] == "31-01-2030"
    assert seen["params"]["contract_types"] == "call_options,put_options"


def test_chain_raw_returns_an_empty_list_when_delta_sends_no_result(monkeypatch):
    monkeypatch.setattr(api, "_get", lambda path, params=None: {"result": None})
    api.fetch_chain_raw.clear()

    assert api.fetch_chain_raw("BTC", "31-01-2030", 1) == []


def test_cache_bucket_rolls_over_with_the_refresh_window(monkeypatch):
    """The bucket is the cache key; it must change once per refresh window.

    Windows are aligned to absolute time, not to the first call, so the clock
    here starts exactly on a boundary. That alignment is deliberate: it means
    two browser tabs opened seconds apart share a bucket and therefore share
    one fetch, instead of each keeping its own offset schedule and doubling
    the request rate against Delta's quota.
    """
    window = 15
    fake = {"t": float(window * 67)}        # exactly on a boundary
    monkeypatch.setattr(api.time, "time", lambda: fake["t"])

    first = api.make_cache_bucket(window)

    fake["t"] += window - 1
    assert api.make_cache_bucket(window) == first, "same window, same bucket"

    fake["t"] += 2
    assert api.make_cache_bucket(window) == first + 1, "next window, next bucket"


def test_cache_bucket_never_divides_by_zero(monkeypatch):
    """A refresh interval of 0 must clamp, not raise."""
    assert isinstance(api.make_cache_bucket(0), int)
