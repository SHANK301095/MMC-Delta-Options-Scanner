"""Tests for the chain filters, and the delta band in particular.

Selecting strikes by delta band is the standard way to sell options, and each
of its edge cases can produce a quietly wrong answer: a put's delta is negative,
some rows have no delta at all, and the band can be switched off.
"""

from __future__ import annotations

import pandas as pd
import pytest

from mmc_core import ui_common as ui


def _chain(deltas, **over) -> pd.DataFrame:
    """A minimal enriched chain - only the columns the filter needs."""
    n = len(deltas)
    frame = pd.DataFrame({
        "strike": [90_000.0 + 1000 * i for i in range(n)],
        "delta": deltas,
        "is_call": [d is not None and d > 0 for d in deltas],
        "two_sided": [True] * n,
        "spread_pct": [5.0] * n,
        "oi_contracts": [500.0] * n,
        "volume": [100.0] * n,
        "abs_moneyness_pct": [5.0] * n,
    })
    for key, val in over.items():
        frame[key] = val
    return frame


OPEN = {"max_spread_pct": 100.0, "min_oi": 0.0, "min_volume": 0.0,
        "max_moneyness_pct": 0.0, "require_two_sided": False}


# ------------------------------------------------------------- delta band

def test_band_matches_calls_and_puts_at_the_same_absolute_delta():
    """Asking for 25 must return both the 0.25 call and the -0.25 put."""
    df = _chain([0.25, -0.25, 0.60, -0.60])
    out = ui.apply_liquidity_filter(df, delta_band=(20.0, 30.0), **OPEN)
    assert sorted(out["delta"].tolist()) == [-0.25, 0.25]


def test_band_is_inclusive_at_both_ends():
    df = _chain([0.15, 0.20, 0.25, 0.30, 0.35])
    out = ui.apply_liquidity_filter(df, delta_band=(20.0, 30.0), **OPEN)
    assert out["delta"].round(2).tolist() == [0.20, 0.25, 0.30]


def test_full_range_band_filters_nothing():
    df = _chain([0.05, -0.50, 0.95])
    out = ui.apply_liquidity_filter(df, delta_band=(0.0, 100.0), **OPEN)
    assert len(out) == 3


def test_no_band_filters_nothing():
    df = _chain([0.05, -0.50, 0.95])
    assert len(ui.apply_liquidity_filter(df, delta_band=None, **OPEN)) == 3


def test_reversed_band_is_treated_as_a_range_not_as_empty():
    """Passing (30, 20) means the same thing the user meant by (20, 30)."""
    df = _chain([0.25, 0.60])
    out = ui.apply_liquidity_filter(df, delta_band=(30.0, 20.0), **OPEN)
    assert out["delta"].round(2).tolist() == [0.25]


def test_rows_with_unknown_delta_are_excluded_when_a_band_is_set():
    """Once the choice is made by delta, keeping a "might match" row is wrong."""
    df = _chain([0.25, None, -0.25])
    out = ui.apply_liquidity_filter(df, delta_band=(20.0, 30.0), **OPEN)
    assert len(out) == 2
    assert out["delta"].notna().all()


def test_rows_with_unknown_delta_survive_when_band_is_off():
    df = _chain([0.25, None])
    assert len(ui.apply_liquidity_filter(df, delta_band=(0.0, 100.0), **OPEN)) == 2


def test_band_that_matches_nothing_returns_empty_not_error():
    df = _chain([0.05, 0.95])
    assert ui.apply_liquidity_filter(df, delta_band=(40.0, 60.0), **OPEN).empty


def test_deep_itm_and_deep_otm_are_both_reachable():
    df = _chain([0.02, 0.50, 0.98, -0.02, -0.98])
    otm = ui.apply_liquidity_filter(df, delta_band=(0.0, 5.0), **OPEN)
    itm = ui.apply_liquidity_filter(df, delta_band=(95.0, 100.0), **OPEN)
    assert sorted(otm["delta"].tolist()) == [-0.02, 0.02]
    assert sorted(itm["delta"].tolist()) == [-0.98, 0.98]


def test_band_mask_on_empty_frame_is_safe():
    assert ui.delta_band_mask(pd.DataFrame(), (20.0, 30.0)).empty


def test_band_mask_without_a_delta_column_claims_nothing():
    frame = pd.DataFrame({"strike": [1.0, 2.0]})
    assert ui.delta_band_mask(frame, (20.0, 30.0)).all()


# ------------------------------------------- band + liquidity interaction

def test_delta_band_composes_with_the_liquidity_filters():
    """Being in the band is not enough - the contract must also be tradable."""
    df = _chain([0.25, -0.25], spread_pct=[5.0, 80.0])
    out = ui.apply_liquidity_filter(
        df, delta_band=(20.0, 30.0),
        max_spread_pct=25.0, min_oi=0.0, min_volume=0.0,
        max_moneyness_pct=0.0, require_two_sided=True,
    )
    assert out["delta"].round(2).tolist() == [0.25]


def test_one_sided_book_is_dropped_before_delta_is_even_considered():
    df = _chain([0.25, -0.25], two_sided=[True, False])
    out = ui.apply_liquidity_filter(
        df, delta_band=(20.0, 30.0),
        max_spread_pct=100.0, min_oi=0.0, min_volume=0.0,
        max_moneyness_pct=0.0, require_two_sided=True,
    )
    assert len(out) == 1


def test_filter_never_mutates_the_input_frame():
    df = _chain([0.25, 0.60])
    before = df.copy()
    ui.apply_liquidity_filter(df, delta_band=(20.0, 30.0), **OPEN)
    pd.testing.assert_frame_equal(df, before)


@pytest.mark.parametrize("band", [(0.0, 100.0), (20.0, 30.0), None])
def test_filter_on_empty_chain_is_safe(band):
    assert ui.apply_liquidity_filter(pd.DataFrame(), delta_band=band, **OPEN).empty
