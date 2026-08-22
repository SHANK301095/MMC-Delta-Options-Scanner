"""Black-Scholes engine ke tests.

Har test ek aisi property check karta hai jo galat hone par scanner ke
numbers chup-chaap galat ho jayenge (crash nahi hoga) — yahi sabse
khatarnak class of bug hai ek options tool mein.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from mmc_core import options_math as om

UTC = timezone.utc

# Ek typical BTC option: spot 100k, 30 din, 60% vol.
S = 100_000.0
T30 = 30.0 / 365.0
SIG = 0.60


# ---------------------------------------------------------------- pricing

def test_put_call_parity_holds_at_zero_rate():
    """C - P = S - K jab r = 0. Pricing mein koi bhi sign flip yahan pakda jayega."""
    for K in (80_000.0, 100_000.0, 125_000.0):
        call = om.bs_price(S, K, T30, SIG, is_call=True)
        put = om.bs_price(S, K, T30, SIG, is_call=False)
        assert call - put == pytest.approx(S - K, abs=1e-6)


def test_put_call_parity_holds_with_nonzero_rate():
    r = 0.05
    K = 105_000.0
    call = om.bs_price(S, K, T30, SIG, True, r)
    put = om.bs_price(S, K, T30, SIG, False, r)
    assert call - put == pytest.approx(S - K * math.exp(-r * T30), abs=1e-6)


def test_price_never_below_intrinsic():
    for K in (60_000.0, 100_000.0, 140_000.0):
        for is_call in (True, False):
            price = om.bs_price(S, K, T30, SIG, is_call)
            intrinsic = max(0.0, S - K) if is_call else max(0.0, K - S)
            assert price >= intrinsic - 1e-9


def test_price_increases_with_volatility():
    K = 100_000.0
    prices = [om.bs_price(S, K, T30, sig, True) for sig in (0.2, 0.4, 0.8, 1.2)]
    assert prices == sorted(prices)


@pytest.mark.parametrize("T", [0.0, -1.0, om.MIN_T_YEARS / 2])
def test_expired_option_collapses_to_intrinsic(T):
    assert om.bs_price(S, 90_000.0, T, SIG, True) == pytest.approx(10_000.0)
    assert om.bs_price(S, 90_000.0, T, SIG, False) == pytest.approx(0.0)


def test_zero_vol_collapses_to_intrinsic():
    assert om.bs_price(S, 90_000.0, T30, 0.0, True) == pytest.approx(10_000.0)


@pytest.mark.parametrize("S_, K_", [(0.0, 100.0), (100.0, 0.0), (-5.0, 100.0)])
def test_degenerate_inputs_return_nan_not_crash(S_, K_):
    """Live chain mein junk rows aate hain — scanner unpar crash nahi karna chahiye."""
    assert math.isnan(om.bs_price(S_, K_, T30, SIG, True))


# ----------------------------------------------------------------- greeks

def test_delta_bounds():
    for K in (50_000.0, 100_000.0, 200_000.0):
        c = om.bs_greeks(S, K, T30, SIG, True)["delta"]
        p = om.bs_greeks(S, K, T30, SIG, False)["delta"]
        assert 0.0 <= c <= 1.0
        assert -1.0 <= p <= 0.0
        # Delta ki parity: call delta - put delta = 1 (r = 0 par)
        assert c - p == pytest.approx(1.0, abs=1e-9)


def test_delta_matches_finite_difference():
    """Analytic delta == numerical dPrice/dSpot. Formula typo yahan pakdi jayegi."""
    K, h = 105_000.0, 1.0
    for is_call in (True, False):
        up = om.bs_price(S + h, K, T30, SIG, is_call)
        dn = om.bs_price(S - h, K, T30, SIG, is_call)
        numeric = (up - dn) / (2 * h)
        assert om.bs_greeks(S, K, T30, SIG, is_call)["delta"] == pytest.approx(
            numeric, abs=1e-6)


def test_gamma_matches_finite_difference():
    K, h = 105_000.0, 10.0
    up = om.bs_price(S + h, K, T30, SIG, True)
    mid = om.bs_price(S, K, T30, SIG, True)
    dn = om.bs_price(S - h, K, T30, SIG, True)
    numeric = (up - 2 * mid + dn) / (h * h)
    assert om.bs_greeks(S, K, T30, SIG, True)["gamma"] == pytest.approx(
        numeric, rel=1e-3)


def test_vega_is_per_vol_point_not_per_unit_vol():
    """vega = premium change per 1% IV move. /100 chhoot jaaye to 100x error."""
    K = 100_000.0
    vega = om.bs_greeks(S, K, T30, SIG, True)["vega"]
    numeric = om.bs_price(S, K, T30, SIG + 0.01, True) - om.bs_price(S, K, T30, SIG, True)
    assert vega == pytest.approx(numeric, rel=1e-2)
    # Calls aur puts ka vega same hota hai.
    assert vega == pytest.approx(om.bs_greeks(S, K, T30, SIG, False)["vega"], abs=1e-9)


def test_theta_is_per_day_and_negative_for_long_options():
    """theta = USD per DAY. /365 chhoot jaaye to 365x error — chart bekaar."""
    K = 100_000.0
    theta = om.bs_greeks(S, K, T30, SIG, True)["theta"]
    assert theta < 0
    one_day = 1.0 / 365.0
    numeric = om.bs_price(S, K, T30 - one_day, SIG, True) - om.bs_price(S, K, T30, SIG, True)
    assert theta == pytest.approx(numeric, rel=0.05)


def test_greeks_at_expiry_are_step_function():
    g_itm = om.bs_greeks(S, 90_000.0, 0.0, SIG, True)
    assert g_itm["delta"] == 1.0
    assert g_itm["gamma"] == 0.0 and g_itm["theta"] == 0.0 and g_itm["vega"] == 0.0
    assert om.bs_greeks(S, 110_000.0, 0.0, SIG, False)["delta"] == -1.0


# ------------------------------------------------------------------ decay

def test_decay_between_equals_repriced_difference():
    K = 100_000.0
    t_end = T30 - 1.0 / 365.0
    burn = om.decay_between(S, K, SIG, True, T30, t_end)
    expected = om.bs_price(S, K, T30, SIG, True) - om.bs_price(S, K, t_end, SIG, True)
    assert burn == pytest.approx(expected)
    assert burn > 0  # seller ke favour mein


def test_decay_between_clamps_reversed_timestamps():
    """t_end > t_start bheja jaaye to 0 aana chahiye, negative burn nahi."""
    K = 100_000.0
    assert om.decay_between(S, K, SIG, True, T30, T30 * 2) == pytest.approx(0.0)


def test_decay_accelerates_near_expiry():
    """Aakhri din ka burn pehle din ke burn se bada hona chahiye."""
    K, day = 100_000.0, 1.0 / 365.0
    far = om.decay_between(S, K, SIG, True, T30, T30 - day)
    near = om.decay_between(S, K, SIG, True, day, 0.0)
    assert near > far


def test_decay_schedule_spans_full_life_without_exploding():
    """Lambi expiry par step auto-widen hona chahiye, truncate nahi."""
    sched = om.decay_schedule(S, 100_000.0, SIG, True, 180.0 / 365.0,
                              step_seconds=3600.0, max_steps=100)
    assert len(sched) <= 100
    assert sched[-1]["t_years"] == pytest.approx(0.0, abs=1e-12)
    # cum_decay monotonically badhna chahiye
    cums = [s["cum_decay"] for s in sched]
    assert cums == sorted(cums)


def test_decay_schedule_on_expired_option_is_empty():
    assert om.decay_schedule(S, 100_000.0, SIG, True, 0.0) == []


# --------------------------------------------------------------------- IV

def test_implied_vol_round_trip():
    K = 105_000.0
    for true_sig in (0.25, 0.60, 1.50):
        price = om.bs_price(S, K, T30, true_sig, True)
        assert om.implied_vol(price, S, K, T30, True) == pytest.approx(
            true_sig, abs=1e-4)


def test_implied_vol_returns_nan_below_intrinsic():
    """Stale quote jo arbitrage dikhata hai — NaN aana chahiye, junk number nahi."""
    assert math.isnan(om.implied_vol(1.0, S, 50_000.0, T30, True))


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_implied_vol_rejects_bad_prices(bad):
    assert math.isnan(om.implied_vol(bad, S, 100_000.0, T30, True))


# ------------------------------------------------------- auto-calibration

def _samples(divisor: float) -> list:
    """Synthetic chain jahan IV known scale mein bheji gayi hai."""
    out = []
    for K in (95_000.0, 100_000.0, 105_000.0):
        for is_call in (True, False):
            mark = om.bs_price(S, K, T30, SIG, is_call)
            out.append({"S": S, "K": K, "T": T30, "iv_raw": SIG * divisor,
                        "is_call": is_call, "mark_price": mark})
    return out


def test_detect_iv_scale_spots_percent_api():
    assert om.detect_iv_scale(_samples(100.0))["divisor"] == 100.0


def test_detect_iv_scale_spots_decimal_api():
    assert om.detect_iv_scale(_samples(1.0))["divisor"] == 1.0


def test_detect_iv_scale_on_empty_input_is_safe():
    assert om.detect_iv_scale([])["n"] == 0


def _greek_samples(scale: float) -> list:
    out = []
    for K in (95_000.0, 100_000.0, 105_000.0):
        for is_call in (True, False):
            ours = om.bs_theta_per_day(S, K, T30, SIG, is_call)
            out.append({"S": S, "K": K, "T": T30, "sigma": SIG,
                        "is_call": is_call, "api_theta": ours * scale})
    return out


def test_detect_greek_scale_per_unit():
    assert om.detect_greek_scale(_greek_samples(1.0), 0.001)["basis"] == "per_unit"


def test_detect_greek_scale_per_lot():
    assert om.detect_greek_scale(_greek_samples(0.001), 0.001)["basis"] == "per_lot"


def test_detect_greek_scale_unknown_on_no_samples():
    assert om.detect_greek_scale([], 0.001)["basis"] == "unknown"


# ------------------------------------------------------------ break-evens

def test_breakevens_on_simple_v_shape():
    spots = [float(x) for x in range(90, 111)]
    payoff = [abs(s - 100.0) - 5.0 for s in spots]   # crosses at 95 aur 105
    be = om.find_breakevens(spots, payoff)
    assert len(be) == 2
    assert be[0] == pytest.approx(95.0, abs=1e-6)
    assert be[1] == pytest.approx(105.0, abs=1e-6)


def test_breakeven_exactly_on_grid_point_is_not_double_counted():
    """Straddle ke break-even aksar round numbers par girte hain — dedupe zaroori."""
    spots = [90.0, 95.0, 100.0, 105.0, 110.0]
    payoff = [-5.0, 0.0, 5.0, 0.0, -5.0]
    assert len(om.find_breakevens(spots, payoff)) == 2


def test_flat_zero_segment_yields_one_breakeven_not_many():
    """Capped structure jo poore range mein exactly zero par baithi hai."""
    spots = [90.0, 95.0, 100.0, 105.0, 110.0]
    payoff = [-5.0, 0.0, 0.0, 0.0, 5.0]
    assert len(om.find_breakevens(spots, payoff)) == 1


def test_breakevens_on_never_crossing_payoff_is_empty():
    spots = [90.0, 100.0, 110.0]
    assert om.find_breakevens(spots, [1.0, 2.0, 3.0]) == []


def test_breakevens_ignores_nan_rows():
    spots = [90.0, 100.0, 110.0]
    assert om.find_breakevens(spots, [-1.0, float("nan"), 1.0]) == []


# ------------------------------------------------------------------- time

def test_years_to_expiry_uses_exact_seconds_not_whole_days():
    """Expiry din par whole-days rounding se premium ~8x overstate hota hai."""
    now = datetime(2026, 1, 31, 9, 0, tzinfo=UTC)
    expiry = now + timedelta(hours=3)
    assert om.years_to_expiry(now, expiry) == pytest.approx(3 * 3600 / om.SECONDS_PER_YEAR)


def test_time_to_expiry_never_negative():
    now = datetime(2026, 1, 31, 15, 0, tzinfo=UTC)
    assert om.seconds_to_expiry(now, now - timedelta(hours=5)) == 0.0


# ------------------------------------------------------------- tail risk

def _payoff(spots, legs, credit: float) -> list:
    """legs = [(strike, is_call, sign)] ; sign +1 = long, -1 = short."""
    out = []
    for s in spots:
        v = 0.0
        for K, is_call, sign in legs:
            v += sign * (max(0.0, s - K) if is_call else max(0.0, K - s))
        out.append(v + credit)
    return out


GRID = [float(x) for x in range(50_000, 150_001, 500)]


def test_short_straddle_reports_unlimited_loss_not_unlimited_profit():
    """Sabse khatarnak galti: short straddle ka max loss finite dikhana."""
    p = _payoff(GRID, [(100_000.0, True, -1), (100_000.0, False, -1)], 8_000.0)
    tail = om.payoff_tail_risk(p)
    assert tail["unlimited_loss"] is True
    assert tail["unlimited_profit"] is False


def test_long_straddle_reports_unlimited_profit_not_unlimited_loss():
    """Iska ulta: long straddle ka loss capped hai (paid premium)."""
    p = _payoff(GRID, [(100_000.0, True, 1), (100_000.0, False, 1)], -8_000.0)
    tail = om.payoff_tail_risk(p)
    assert tail["unlimited_profit"] is True
    assert tail["unlimited_loss"] is False


def test_short_call_unlimited_loss_lives_on_the_UPSIDE():
    """Sirf left edge dekhne wala check ise miss kar deta hai."""
    tail = om.payoff_tail_risk(_payoff(GRID, [(105_000.0, True, -1)], 3_000.0))
    assert tail["unlimited_loss"] is True
    assert tail["unlimited_profit"] is False


def test_short_put_unlimited_loss_lives_on_the_DOWNSIDE():
    tail = om.payoff_tail_risk(_payoff(GRID, [(95_000.0, False, -1)], 3_000.0))
    assert tail["unlimited_loss"] is True
    assert tail["unlimited_profit"] is False


def test_long_call_is_unlimited_profit_capped_loss():
    tail = om.payoff_tail_risk(_payoff(GRID, [(105_000.0, True, 1)], -3_000.0))
    assert tail["unlimited_profit"] is True
    assert tail["unlimited_loss"] is False


def test_iron_condor_is_bounded_on_both_sides():
    """Defined-risk structure par koi bhi 'Unlimited' badge galat hai."""
    legs = [(110_000.0, True, -1), (120_000.0, True, 1),
            (90_000.0, False, -1), (80_000.0, False, 1)]
    tail = om.payoff_tail_risk(_payoff(GRID, legs, 2_000.0))
    assert tail["unlimited_profit"] is False
    assert tail["unlimited_loss"] is False


def test_bull_call_spread_is_bounded_on_both_sides():
    legs = [(100_000.0, True, 1), (110_000.0, True, -1)]
    tail = om.payoff_tail_risk(_payoff(GRID, legs, -3_000.0))
    assert tail["unlimited_profit"] is False
    assert tail["unlimited_loss"] is False


def test_long_strangle_is_unlimited_profit_both_edges():
    legs = [(110_000.0, True, 1), (90_000.0, False, 1)]
    tail = om.payoff_tail_risk(_payoff(GRID, legs, -4_000.0))
    assert tail["unlimited_profit"] is True
    assert tail["unlimited_loss"] is False


@pytest.mark.parametrize("payoff", [None, [], [1.0], [1.0, 2.0]])
def test_tail_risk_on_degenerate_input_claims_nothing(payoff):
    tail = om.payoff_tail_risk(payoff)
    assert tail == {"unlimited_profit": False, "unlimited_loss": False}


def test_tail_risk_tolerance_scales_with_payoff_size():
    """Lakhs-scale flat payoff par floating-point noise 'Unlimited' na banaye."""
    flat = [250_000.0] * 401
    tail = om.payoff_tail_risk(flat)
    assert tail["unlimited_profit"] is False
    assert tail["unlimited_loss"] is False
