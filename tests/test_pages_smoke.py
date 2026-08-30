"""Tests that actually run the Streamlit pages against a synthetic chain.

A compile check only catches syntax. A page that misnames a column, breaks a
format string or builds a widget incorrectly still imports cleanly - and only
crashes when a user opens it. Delta's API is never touched by these tests: both
network calls are replaced with a deterministic chain generated from
Black-Scholes, so the calibration layer has consistent data to reprice
against.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from mmc_core import delta_api as api
from mmc_core import options_math as om

streamlit_testing = pytest.importorskip("streamlit.testing.v1")
AppTest = streamlit_testing.AppTest

UTC = timezone.utc

# AppTest resolves relative paths against the CALLING file, not the test
# rootdir - so every path is built from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

SPOT = 100_000.0
SIGMA = 0.55
STRIKES = [float(k) for k in range(80_000, 120_001, 2_500)]
CONTRACT_VALUE = 0.001


def _expiry() -> datetime:
    """Seven days out at 12:00 UTC - Delta India's real settlement time."""
    day = (datetime.now(UTC) + timedelta(days=7)).date()
    return datetime(day.year, day.month, day.day, 12, 0, tzinfo=UTC)


def _symbol(strike: float, is_call: bool, expiry: datetime) -> str:
    return (f"{'C' if is_call else 'P'}-BTC-{int(strike)}-"
            f"{expiry.strftime('%d%m%y')}")


def _products() -> pd.DataFrame:
    expiry = _expiry()
    rows = []
    for strike in STRIKES:
        for is_call in (True, False):
            rows.append({
                "symbol": _symbol(strike, is_call, expiry),
                "underlying": "BTC", "strike": strike, "is_call": is_call,
                "expiry_utc": expiry, "contract_value": CONTRACT_VALUE,
                "tick_size": 0.1,
            })
    return pd.DataFrame(rows)


def _tickers() -> list:
    """Mark prices and greeks from Black-Scholes, with IV supplied in percent.

    That consistency matters: the calibration layer decides whether the API
    sends percent or decimal by repricing the IV both ways. Random numbers would
    make its verdict meaningless."""
    expiry = _expiry()
    now = datetime.now(UTC)
    t_years = om.years_to_expiry(now, expiry)
    out = []

    for strike in STRIKES:
        for is_call in (True, False):
            mark = om.bs_price(SPOT, strike, t_years, SIGMA, is_call)
            greeks = om.bs_greeks(SPOT, strike, t_years, SIGMA, is_call)
            spread = max(0.02 * mark, 0.5)
            out.append({
                "symbol": _symbol(strike, is_call, expiry),
                "contract_type": "call_options" if is_call else "put_options",
                "mark_price": f"{mark:.4f}",
                "spot_price": f"{SPOT:.2f}",
                "mark_iv": f"{SIGMA * 100:.2f}",          # percent, as Delta sends it
                "greeks": {k: f"{v:.10f}" for k, v in greeks.items()},
                "quotes": {
                    "best_bid": f"{max(0.01, mark - spread / 2):.4f}",
                    "best_ask": f"{mark + spread / 2:.4f}",
                    "bid_size": "25", "ask_size": "25",
                },
                "oi_contracts": "800", "oi_value_usd": "80000",
                "volume": "150", "turnover_usd": "15000",
                "timestamp": int(now.timestamp() * 1e6),
            })
    return out


@pytest.fixture
def offline_chain(monkeypatch):
    """Replace both network calls with deterministic data."""
    monkeypatch.setattr(api, "fetch_option_products", _products)
    monkeypatch.setattr(api, "fetch_chain_raw",
                        lambda underlying, api_date, cache_bucket: _tickers())
    return None


DELTA_PAGE = REPO_ROOT / "pages" / "6_Delta_Filter.py"

PAGES = [
    "app.py",
    "pages/1_Live_Chain.py",
    "pages/2_Theta_Decay.py",
    "pages/3_IV_Skew.py",
    "pages/4_Payoff_Builder.py",
    "pages/5_Mispricing.py",
    "pages/6_Delta_Filter.py",
    "pages/7_Vol_Regime.py",
]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_exception(page, offline_chain):
    at = AppTest.from_file(str(REPO_ROOT / page), default_timeout=90).run()
    assert not at.exception, f"{page} raised: {at.exception}"


def test_delta_filter_page_shows_only_in_band_contracts(offline_chain):
    """The page's whole purpose: nothing outside the band may reach the table."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=90)
    at.session_state["delta_band_main"] = (20, 30)
    at.run()
    assert not at.exception

    assert at.dataframe, "the live rates table did not render"
    shown = at.dataframe[0].value
    assert len(shown) > 0, "the 20-30 delta band came back empty - suspect the fixture"

    abs_delta = shown["Δ"].abs() * 100.0
    assert abs_delta.between(20, 30).all()
    # Both sides must appear - the band applies to absolute delta.
    assert set(shown["Type"]) == {"CALL", "PUT"}


def test_delta_filter_page_survives_a_band_with_no_matches(offline_chain):
    """On an empty band the page should explain itself, not crash."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=90)
    at.session_state["delta_band_main"] = (99, 100)
    at.run()
    assert not at.exception


def test_widening_the_band_never_shrinks_the_result(offline_chain):
    counts = {}
    for band in ((40, 45), (20, 60), (0, 100)):
        at = AppTest.from_file(str(DELTA_PAGE), default_timeout=90)
        at.session_state["delta_band_main"] = band
        at.run()
        assert not at.exception
        counts[band] = len(at.dataframe[0].value) if at.dataframe else 0

    assert counts[(40, 45)] <= counts[(20, 60)] <= counts[(0, 100)]


# --------------------------------------------------- volatility regime

VOL_PAGE = REPO_ROOT / "pages" / "7_Vol_Regime.py"

_HERO_RE = re.compile(r'class="mmc-hero-value[^"]*">([^<]+)<')


def _hero_value(at):
    """Extract the hero number from the rendered page, or None."""
    for block in at.markdown:
        found = _HERO_RE.search(str(block.value))
        if found:
            text = found.group(1).strip()
            try:
                return float(text)
            except ValueError:
                return None
    return None


def test_vol_regime_page_reports_in_regime_when_the_band_contains_the_index(
        offline_chain):
    """The fixture chain is built at 55% vol, so it falls inside a 40-80 band."""
    at = AppTest.from_file(str(VOL_PAGE), default_timeout=120)
    at.session_state["vol_regime_band"] = (40, 80)
    at.run()
    assert not at.exception
    assert at.success, "an in-regime reading should show a success banner"


def test_vol_regime_page_warns_when_the_index_is_outside_the_band(offline_chain):
    at = AppTest.from_file(str(VOL_PAGE), default_timeout=120)
    at.session_state["vol_regime_band"] = (5, 10)
    at.run()
    assert not at.exception
    assert at.warning, "a reading outside the band should show a warning"
    assert not at.success


def test_vol_regime_headline_is_close_to_the_vol_the_fixture_was_built_from(
        offline_chain):
    """A round trip through the whole stack: BS chain -> tickers -> normalize -> index."""
    at = AppTest.from_file(str(VOL_PAGE), default_timeout=120).run()
    assert not at.exception

    # The headline is now a hero block rather than a native metric - the test's
    # purpose is unchanged, only where it reads the value from.
    value = _hero_value(at)
    assert value is not None, "the volatility hero did not render"
    assert value == pytest.approx(SIGMA * 100, rel=0.10)


# ------------------------------------------------- auto-refresh & links

def test_auto_refresh_does_not_block_or_break_the_page(offline_chain):
    """This used to call `time.sleep(interval)`, which slept each viewer's
    thread for the whole interval and queued their clicks. It is now a timer
    fragment; the page should render normally."""
    at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=120)
    at.session_state["auto_refresh"] = True
    at.session_state["refresh_seconds"] = 5
    at.run()
    assert not at.exception


def test_a_shared_link_restores_the_view(offline_chain):
    """The whole point of sending a link: the recipient sees the same screen."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=120)
    at.query_params["u"] = "BTC"
    at.query_params["p"] = "mark"
    at.query_params["fx"] = "91"
    at.query_params["d"] = "40-60"
    at.run()
    assert not at.exception
    assert tuple(at.session_state["delta_band_main"]) == (40, 60)
    assert at.session_state["price_mode"] == "Mark"
    assert at.session_state["usdinr"] == 91.0


def test_a_link_with_junk_params_still_opens(offline_chain):
    """A bad param should fall back to the default, not crash."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=120)
    at.query_params["u"] = "<script>alert(1)</script>"
    at.query_params["fx"] = "abc"
    at.query_params["d"] = "junk"
    at.run()
    assert not at.exception


def test_a_link_naming_an_expiry_that_no_longer_exists_falls_back(offline_chain):
    """Expiries pass, but old links keep circulating. Such a link should open
    on a current expiry rather than break."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=120)
    at.query_params["e"] = "01-01-2020"
    at.run()
    assert not at.exception
    assert at.session_state["expiry_api_date"] != "01-01-2020"
