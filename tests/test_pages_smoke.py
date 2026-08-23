"""Streamlit pages ko ek synthetic chain par sach mein chalane wale tests.

Compile check sirf syntax pakadta hai. Ek page column ka naam galat likhne,
format string tod dene, ya widget ko galat tarike se banane par bhi import ho
jaata hai — aur crash tabhi hota hai jab user page kholta hai. Delta ka API
in tests se chhuaa nahi jaata: dono network calls ek deterministic chain se
replace ho jaati hain jo Black-Scholes se khud banti hai, taaki calibration
layer ke paas reprice karne ke liye consistent data ho.
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

# AppTest relative paths ko CALLING file ke against resolve karta hai, test ke
# rootdir ke against nahi - isliye har path repo root se banaya jaata hai.
REPO_ROOT = Path(__file__).resolve().parent.parent

SPOT = 100_000.0
SIGMA = 0.55
STRIKES = [float(k) for k in range(80_000, 120_001, 2_500)]
CONTRACT_VALUE = 0.001


def _expiry() -> datetime:
    """7 din baad, 12:00 UTC — Delta India ka asli settlement waqt."""
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
    """Mark price aur greeks Black-Scholes se — IV percent mein bheji jaati hai.

    Ye consistency zaroori hai: calibration layer IV ko dono tarah se reprice
    karke decide karta hai ki API percent bhej raha hai ya decimal. Random
    numbers bhejne par wo verdict hi meaningless ho jaata."""
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
                "mark_iv": f"{SIGMA * 100:.2f}",          # percent, Delta ki tarah
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
    """Dono network calls ko deterministic data se badal dijiye."""
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
    """Page ka poora point: band ke bahar ka kuch bhi table mein nahi aana chahiye."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=90)
    at.session_state["delta_band_main"] = (20, 30)
    at.run()
    assert not at.exception

    assert at.dataframe, "live rates table render hi nahi hui"
    shown = at.dataframe[0].value
    assert len(shown) > 0, "20-30 delta band khaali aayi - fixture chain shaq mein hai"

    abs_delta = shown["Δ"].abs() * 100.0
    assert abs_delta.between(20, 30).all()
    # Dono sides aani chahiye - band absolute delta par lagta hai.
    assert set(shown["Type"]) == {"CALL", "PUT"}


def test_delta_filter_page_survives_a_band_with_no_matches(offline_chain):
    """Khaali band par page ko samjhaana chahiye, crash nahi karna chahiye."""
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
    """Rendered page se hero ka number nikaaliye, ya None."""
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
    """Fixture chain 55% vol par bani hai, to 40-80 band ke andar aana chahiye."""
    at = AppTest.from_file(str(VOL_PAGE), default_timeout=120)
    at.session_state["vol_regime_band"] = (40, 80)
    at.run()
    assert not at.exception
    assert at.success, "in-regime hone par success banner aana chahiye"


def test_vol_regime_page_warns_when_the_index_is_outside_the_band(offline_chain):
    at = AppTest.from_file(str(VOL_PAGE), default_timeout=120)
    at.session_state["vol_regime_band"] = (5, 10)
    at.run()
    assert not at.exception
    assert at.warning, "band ke bahar hone par warning aani chahiye"
    assert not at.success


def test_vol_regime_headline_is_close_to_the_vol_the_fixture_was_built_from(
        offline_chain):
    """Poore stack ka round trip: BS chain -> tickers -> normalize -> index."""
    at = AppTest.from_file(str(VOL_PAGE), default_timeout=120).run()
    assert not at.exception

    # Headline ab ek hero block hai, native metric nahi — test ka maqsad wahi
    # hai (poore stack ka round trip), sirf padhne ki jagah badli hai.
    value = _hero_value(at)
    assert value is not None, "VIX hero render hi nahi hua"
    assert value == pytest.approx(SIGMA * 100, rel=0.10)


# ------------------------------------------------- auto-refresh & links

def test_auto_refresh_does_not_block_or_break_the_page(offline_chain):
    """Pehle ye `time.sleep(interval)` karta tha — har viewer ka thread poore
    interval ke liye soya rehta tha aur click queue ho jaate the. Ab ek timer
    fragment hai; page normal render hona chahiye."""
    at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=120)
    at.session_state["auto_refresh"] = True
    at.session_state["refresh_seconds"] = 5
    at.run()
    assert not at.exception


def test_a_shared_link_restores_the_view(offline_chain):
    """Link bhejne ka poora point: kholne wale ko wahi screen mile."""
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
    """Kharab param se app default par chale, crash na kare."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=120)
    at.query_params["u"] = "<script>alert(1)</script>"
    at.query_params["fx"] = "abc"
    at.query_params["d"] = "junk"
    at.run()
    assert not at.exception


def test_a_link_naming_an_expiry_that_no_longer_exists_falls_back(offline_chain):
    """Expiry beet jaati hain, par purane link ghoomte rehte hain. Aise link ko
    maujooda expiry par khulna chahiye, tootna nahi."""
    at = AppTest.from_file(str(DELTA_PAGE), default_timeout=120)
    at.query_params["e"] = "01-01-2020"
    at.run()
    assert not at.exception
    assert at.session_state["expiry_api_date"] != "01-01-2020"
