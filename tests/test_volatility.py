"""Tests for the VIX-style volatility index.

The load-bearing test is the one that grips the formula itself: if the chain
was built from a known volatility, the model-free formula must return that same
volatility. It is a round trip - any wrong weight, sign or dK is caught at
once.
"""

from __future__ import annotations

import math

import pytest

from mmc_core import options_math as om
from mmc_core import volatility as vol

S = 100_000.0


def _lognormal_chain(sigma: float, t_years: float, r: float = 0.0,
                     lo: float = 0.3, hi: float = 3.0, step: float = 0.01):
    """A chain built from Black-Scholes, with bid == ask and no spread.

    The wings are wide and the grid fine, because only then does the discrete
    sum approach the true integral. On a narrow range the formula returns a low
    number while remaining correct - that is truncation, not a bug.
    """
    calls, puts = {}, {}
    k = S * lo
    while k <= S * hi:
        c = om.bs_price(S, k, t_years, sigma, True, r)
        p = om.bs_price(S, k, t_years, sigma, False, r)
        calls[k] = {"bid": c, "ask": c}
        puts[k] = {"bid": p, "ask": p}
        k += S * step
    return calls, puts


# ------------------------------------------------- formula round-trip

@pytest.mark.parametrize("sigma", [0.30, 0.55, 0.80, 1.20])
@pytest.mark.parametrize("days", [7, 30, 90])
def test_model_free_formula_recovers_the_volatility_it_was_built_from(sigma, days):
    t = days / 365.0
    calls, puts = _lognormal_chain(sigma, t)
    out = vol.expiry_variance(calls, puts, t)
    assert out["reason"] is None
    assert math.sqrt(out["sigma2"]) == pytest.approx(sigma, rel=0.02)


def test_higher_volatility_gives_a_higher_index():
    t = 30 / 365.0
    prev = 0.0
    for sigma in (0.2, 0.4, 0.6, 0.9):
        calls, puts = _lognormal_chain(sigma, t)
        got = math.sqrt(vol.expiry_variance(calls, puts, t)["sigma2"])
        assert got > prev
        prev = got


# ----------------------------------------------------------- forward

def test_forward_equals_spot_at_zero_rate():
    t = 30 / 365.0
    calls, puts = _lognormal_chain(0.55, t)
    assert vol.forward_level(calls, puts, t)["forward"] == pytest.approx(S, rel=1e-4)


def test_forward_carries_the_rate():
    """An option's reference is the forward, not spot - F must rise with r."""
    t, r = 30 / 365.0, 0.10
    calls, puts = _lognormal_chain(0.55, t, r=r)
    got = vol.forward_level(calls, puts, t, r)["forward"]
    assert got == pytest.approx(S * math.exp(r * t), rel=1e-3)


def test_k0_is_the_first_strike_at_or_below_the_forward():
    calls = {90.0: {"bid": 12.0, "ask": 12.0}, 100.0: {"bid": 5.0, "ask": 5.0},
             110.0: {"bid": 1.0, "ask": 1.0}}
    puts = {90.0: {"bid": 1.0, "ask": 1.0}, 100.0: {"bid": 4.0, "ask": 4.0},
            110.0: {"bid": 11.0, "ask": 11.0}}
    out = vol.forward_level(calls, puts, 0.1)
    assert out["k_star"] == 100.0
    assert out["forward"] == pytest.approx(101.0)
    assert out["k0"] == 100.0


def test_forward_on_a_chain_with_no_two_sided_strike_is_nan():
    calls = {100.0: {"bid": float("nan"), "ask": 5.0}}
    puts = {100.0: {"bid": 4.0, "ask": float("nan")}}
    assert math.isnan(vol.forward_level(calls, puts, 0.1)["forward"])


# --------------------------------------------------------- zero bids

def _sparse_chain(put_bids, call_bids):
    """K0 = 100. Puts below and calls above, with the given bids."""
    calls = {100.0: {"bid": 5.0, "ask": 5.0}}
    puts = {100.0: {"bid": 5.0, "ask": 5.0}}
    for i, bid in enumerate(put_bids):          # 95, 90, 85 ... below K0
        k = 95.0 - 5.0 * i
        puts[k] = {"bid": bid, "ask": bid + 0.5 if bid > 0 else 0.5}
    for i, bid in enumerate(call_bids):         # 105, 110, 115 ... above K0
        k = 105.0 + 5.0 * i
        calls[k] = {"bid": bid, "ask": bid + 0.5 if bid > 0 else 0.5}
    return calls, puts


def test_summation_stops_after_two_consecutive_zero_bids():
    """A junk quote on a dead wing strike inflates the variance."""
    calls, puts = _sparse_chain([3.0, 0.0, 0.0, 9.9], [3.0, 0.0, 0.0, 9.9])
    out = vol.expiry_variance(calls, puts, 0.1)
    # K0 + one put + one call = 3. The 9.9 strike beyond two zeros is excluded.
    assert out["strikes_used"] == 3


def test_a_single_zero_bid_is_skipped_but_does_not_stop_the_walk():
    calls, puts = _sparse_chain([3.0, 0.0, 1.0], [3.0, 0.0, 1.0])
    out = vol.expiry_variance(calls, puts, 0.1)
    assert out["strikes_used"] == 5     # K0 + 2 puts + 2 calls


# ------------------------------------------------------- degenerate

@pytest.mark.parametrize("t", [0.0, -1.0])
def test_expired_expiry_is_refused(t):
    calls, puts = _lognormal_chain(0.5, 0.1)
    assert vol.expiry_variance(calls, puts, t)["reason"] is not None


def test_empty_side_is_refused():
    assert vol.expiry_variance({}, {}, 0.1)["reason"] is not None


def test_too_few_usable_strikes_is_refused_not_guessed():
    calls = {100.0: {"bid": 5.0, "ask": 5.0}}
    puts = {100.0: {"bid": 5.0, "ask": 5.0}}
    out = vol.expiry_variance(calls, puts, 0.1)
    assert out["reason"] is not None
    assert math.isnan(out["sigma2"])


# ----------------------------------------------------- interpolation

def test_interpolation_between_two_equal_vols_returns_that_vol():
    near = {"t_years": 20 / 365.0, "sigma2": 0.36}
    far = {"t_years": 60 / 365.0, "sigma2": 0.36}
    assert vol.interpolate_to_target(near, far) == pytest.approx(0.6)


def test_interpolation_is_on_variance_not_on_volatility():
    """Interpolating sigma directly is a classic and quietly wrong shortcut."""
    near = {"t_years": 20 / 365.0, "sigma2": 0.4 ** 2}
    far = {"t_years": 60 / 365.0, "sigma2": 0.8 ** 2}

    got = vol.interpolate_to_target(near, far, target_days=30.0)

    # The correct answer under total-variance weighting
    assert got == pytest.approx(math.sqrt(0.4), rel=1e-6)
    # The (wrong) answer from interpolating sigma directly
    naive = 0.4 * 0.75 + 0.8 * 0.25
    assert got != pytest.approx(naive, rel=1e-3)


def test_interpolation_result_sits_between_the_two_inputs():
    near = {"t_years": 20 / 365.0, "sigma2": 0.3 ** 2}
    far = {"t_years": 60 / 365.0, "sigma2": 0.9 ** 2}
    got = vol.interpolate_to_target(near, far)
    assert 0.3 < got < 0.9


# ------------------------------------------------------------ index

def _exp(days, sigma):
    return {"t_years": days / 365.0, "sigma2": sigma ** 2, "label": f"{days}d"}


def test_index_is_constant_maturity_when_two_expiries_bracket_30_days():
    out = vol.volatility_index([_exp(20, 0.5), _exp(45, 0.5)])
    assert out["constant_maturity"] is True
    assert out["basis_days"] == 30.0
    assert out["value"] == pytest.approx(50.0, rel=1e-6)
    assert out["note"] is None


def test_index_refuses_to_extrapolate_when_every_expiry_is_short():
    """Producing a 30-day number without 30 days of data is a confident-looking
    falsehood. The maturity that exists is what must be reported."""
    out = vol.volatility_index([_exp(3, 0.9), _exp(10, 0.7)])
    assert out["constant_maturity"] is False
    assert out["basis_days"] == pytest.approx(10.0)
    assert out["value"] == pytest.approx(70.0, rel=1e-6)
    assert "shorter than 30 days" in out["note"]


def test_index_refuses_to_extrapolate_when_every_expiry_is_long():
    out = vol.volatility_index([_exp(60, 0.4), _exp(120, 0.5)])
    assert out["constant_maturity"] is False
    assert out["basis_days"] == pytest.approx(60.0)
    assert "longer than 30 days" in out["note"]


def test_index_picks_the_pair_that_actually_brackets_the_target():
    out = vol.volatility_index([_exp(2, 0.9), _exp(25, 0.5),
                                _exp(40, 0.5), _exp(200, 0.2)])
    assert out["constant_maturity"] is True
    assert out["near"]["label"] == "25d"
    assert out["far"]["label"] == "40d"


@pytest.mark.parametrize("expiries", [
    [],
    [{"t_years": 0.1, "sigma2": float("nan")}],
    [{"t_years": 0.1, "sigma2": -0.2}],
    [{"t_years": 0.0, "sigma2": 0.25}],
])
def test_index_without_usable_input_is_nan_not_zero(expiries):
    out = vol.volatility_index(expiries)
    assert math.isnan(out["value"])
    assert out["note"] is not None


# ----------------------------------------------------- regime gate

@pytest.mark.parametrize("value, expected", [
    (55.0, "inside"), (40.0, "inside"), (80.0, "inside"),
    (39.9, "below"), (80.1, "above"),
])
def test_regime_position(value, expected):
    out = vol.regime_status(value, (40.0, 80.0))
    assert out["position"] == expected
    assert out["in_regime"] is (expected == "inside")


def test_regime_reports_how_far_outside_the_band_it_is():
    assert vol.regime_status(30.0, (40.0, 80.0))["distance"] == pytest.approx(10.0)
    assert vol.regime_status(95.0, (40.0, 80.0))["distance"] == pytest.approx(15.0)


def test_reversed_regime_band_is_read_as_a_range():
    assert vol.regime_status(55.0, (80.0, 40.0))["in_regime"] is True


def test_regime_on_an_unknown_index_never_claims_you_are_in_regime():
    """If the index could not be computed, claiming "conditions are met" is
    dangerous - it authorises a trade with no basis at all."""
    out = vol.regime_status(float("nan"), (40.0, 80.0))
    assert out["in_regime"] is False
    assert out["position"] == "unknown"


# --------------------------------------------------------- coverage

def test_coverage_reports_the_distance_reached_on_each_side():
    out = vol.coverage(k_min=75.0, k_max=130.0, forward=100.0)
    assert out["low_pct"] == pytest.approx(25.0)
    assert out["high_pct"] == pytest.approx(30.0)
    assert out["narrow_side"] is None


@pytest.mark.parametrize("k_min, k_max, expected", [
    (85.0, 130.0, "down"),     # narrow below
    (70.0, 110.0, "up"),       # narrow above
    (90.0, 110.0, "both"),     # narrow on both sides
    (60.0, 150.0, None),       # adequate
])
def test_coverage_names_the_narrow_side(k_min, k_max, expected):
    assert vol.coverage(k_min, k_max, 100.0)["narrow_side"] == expected


def test_coverage_on_a_bad_forward_says_unknown_not_fine():
    assert vol.coverage(80.0, 120.0, float("nan"))["narrow_side"] == "unknown"
    assert vol.coverage(80.0, 120.0, 0.0)["narrow_side"] == "unknown"


def test_a_narrow_chain_understates_the_index():
    """This bias is real, which is why the page shows it rather than hiding it."""
    t = 90 / 365.0
    wide_c, wide_p = _lognormal_chain(0.55, t, lo=0.3, hi=3.0, step=0.02)
    narrow_c, narrow_p = _lognormal_chain(0.55, t, lo=0.85, hi=1.15, step=0.02)

    wide = math.sqrt(vol.expiry_variance(wide_c, wide_p, t)["sigma2"])
    narrow = math.sqrt(vol.expiry_variance(narrow_c, narrow_p, t)["sigma2"])

    assert wide == pytest.approx(0.55, rel=0.02)
    assert narrow < wide * 0.9          # materially lower
    assert vol.expiry_variance(narrow_c, narrow_p, t)["coverage"]["narrow_side"] == "both"
