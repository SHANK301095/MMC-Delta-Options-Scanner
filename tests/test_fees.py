"""Tests for the Delta India fee model.

The central claim here: fees are charged on NOTIONAL, not on premium - but
capped at a percentage of the premium. Invert that relationship and the scanner
will rank dead OTM strikes as the "best theta yield", which is precisely the bug
this module exists to prevent.
"""

from __future__ import annotations

import math

import pytest

from mmc_core import fees as fx

# Delta India BTC options
CV = 0.001            # 1 lot = 0.001 BTC
INDEX = 100_000.0     # notional per lot = $100

ATM_PREMIUM = 3_000.0   # USD per BTC -> $3.00 per lot
OTM_PREMIUM = 4.0       # USD per BTC -> $0.004 per lot

CFG = fx.FeeConfig()    # maker 0.01%, taker 0.03%, cap 3.5%, GST 18%


# ------------------------------------------------------------- single leg

def test_notional_rate_binds_on_expensive_atm_option():
    """At the money the premium is large enough that the cap never binds."""
    fee = fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, CFG, is_maker=False)
    expected = (1.0 * CV * INDEX) * CFG.taker_rate * (1 + CFG.gst)
    assert fee == pytest.approx(expected)
    assert not fx.cap_binds(ATM_PREMIUM, INDEX, CV, CFG, is_maker=False)


def test_premium_cap_binds_on_cheap_otm_option():
    """On a cheap OTM strike the cap is the real fee - it is what makes them
    tradable at all."""
    fee = fx.leg_fee_usd(OTM_PREMIUM, INDEX, 1.0, CV, CFG, is_maker=False)
    expected = (1.0 * CV * OTM_PREMIUM) * CFG.premium_cap_pct * (1 + CFG.gst)
    assert fee == pytest.approx(expected)
    assert fx.cap_binds(OTM_PREMIUM, INDEX, CV, CFG, is_maker=False)
    # Without the cap, the fee would exceed the premium itself.
    assert fee < CV * OTM_PREMIUM


def test_fee_is_always_the_smaller_of_notional_and_cap():
    for premium in (0.5, 4.0, 50.0, 500.0, 3_000.0, 20_000.0):
        fee = fx.leg_fee_usd(premium, INDEX, 1.0, CV, CFG, is_maker=False)
        notional_fee = CV * INDEX * CFG.taker_rate * (1 + CFG.gst)
        cap_fee = CV * premium * CFG.premium_cap_pct * (1 + CFG.gst)
        assert fee == pytest.approx(min(notional_fee, cap_fee))


def test_gst_is_applied_on_top_of_the_fee():
    no_gst = fx.FeeConfig(gst=0.0)
    with_gst = fx.FeeConfig(gst=0.18)
    a = fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, no_gst, is_maker=False)
    b = fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, with_gst, is_maker=False)
    assert b == pytest.approx(a * 1.18)


def test_maker_is_cheaper_than_taker():
    maker = fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, CFG, is_maker=True)
    taker = fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, CFG, is_maker=False)
    assert maker < taker


def test_fee_scales_linearly_with_lots():
    one = fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, CFG)
    ten = fx.leg_fee_usd(ATM_PREMIUM, INDEX, 10.0, CV, CFG)
    assert ten == pytest.approx(one * 10.0)


@pytest.mark.parametrize("lots", [0.0, -1.0])
def test_no_position_means_no_fee(lots):
    assert fx.leg_fee_usd(ATM_PREMIUM, INDEX, lots, CV, CFG) == 0.0


@pytest.mark.parametrize("bad", [None, float("nan")])
def test_bad_inputs_return_nan_not_crash(bad):
    assert math.isnan(fx.leg_fee_usd(bad, INDEX, 1.0, CV, CFG))
    assert math.isnan(fx.leg_fee_usd(ATM_PREMIUM, bad, 1.0, CV, CFG))


# --------------------------------------------------------------- round trip

def test_round_trip_uses_entry_and_exit_maker_flags_separately():
    cfg = fx.FeeConfig(entry_is_maker=True, exit_is_maker=False)
    rt = fx.round_trip_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, cfg)
    expected = (fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, cfg, is_maker=True)
                + fx.leg_fee_usd(ATM_PREMIUM, INDEX, 1.0, CV, cfg, is_maker=False))
    assert rt == pytest.approx(expected)


def test_decayed_exit_price_lowers_the_exit_fee_when_cap_binds():
    """In a decay analysis the honest exit price is lower, so the cap binds lower."""
    full = fx.round_trip_fee_usd(OTM_PREMIUM, INDEX, 1.0, CV, CFG)
    decayed = fx.round_trip_fee_usd(OTM_PREMIUM, INDEX, 1.0, CV, CFG,
                                    exit_price=OTM_PREMIUM * 0.25)
    assert decayed < full


def test_round_trip_cost_hurts_cheap_otm_far_more_than_atm():
    """The README's core claim: on cheap OTM the round trip eats much of the
    premium."""
    atm_pct = fx.fee_as_pct_of_premium(ATM_PREMIUM, INDEX, CV, CFG)
    otm_pct = fx.fee_as_pct_of_premium(OTM_PREMIUM, INDEX, CV, CFG)
    assert otm_pct > atm_pct * 2
    # The cap binds on both sides -> 2 x cap x (1 + GST)
    assert otm_pct == pytest.approx(
        2 * CFG.premium_cap_pct * (1 + CFG.gst) * 100.0)


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
def test_fee_pct_of_worthless_option_is_nan(bad):
    assert math.isnan(fx.fee_as_pct_of_premium(bad, INDEX, CV, CFG))


# ---------------------------------------------------- execution price basis

def test_realistic_basis_buys_the_ask_and_sells_the_bid():
    assert fx.execution_price(100.0, 95.0, 105.0, is_buy=True) == 105.0
    assert fx.execution_price(100.0, 95.0, 105.0, is_buy=False) == 95.0


def test_mid_basis_is_the_book_midpoint():
    assert fx.execution_price(100.0, 95.0, 105.0, True, mode="mid") == 100.0
    assert fx.execution_price(100.0, 90.0, 110.0, False, mode="mid") == 100.0


def test_mark_basis_ignores_the_book():
    assert fx.execution_price(100.0, 95.0, 105.0, True, mode="mark") == 100.0


@pytest.mark.parametrize("bid, ask", [
    (float("nan"), 105.0),   # one-sided book
    (95.0, float("nan")),
    (0.0, 105.0),            # zero bid
    (None, None),
])
def test_missing_book_falls_back_to_mark(bid, ask):
    """On a one-sided strike an ask/bid basis is meaningless - only mark remains."""
    assert fx.execution_price(100.0, bid, ask, is_buy=True) == 100.0


def test_slippage_is_the_full_spread_as_pct_of_mark():
    assert fx.slippage_cost_pct(95.0, 105.0, 100.0) == pytest.approx(10.0)


@pytest.mark.parametrize("bid, ask, mark", [
    (float("nan"), 105.0, 100.0),
    (95.0, 105.0, 0.0),
    (None, 105.0, 100.0),
])
def test_slippage_on_bad_book_is_nan(bid, ask, mark):
    assert math.isnan(fx.slippage_cost_pct(bid, ask, mark))
