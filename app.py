"""
MMC Delta Scanner — Home
========================
Run with:  streamlit run app.py

A read-only scanner for Delta Exchange India's BTC and ETH options.
No API key, no secret, no order-placement code - anywhere.

This page does one job: show the state of the selected expiry at a glance so
you can move to the right module. That is why there are few numbers here, and
why each one is tied to a decision.
"""

from __future__ import annotations

import math

import streamlit as st

from mmc_core import theme
from mmc_core import ui_common as ui

ui.page_setup(
    "Home",
    "Delta Exchange India · BTC & ETH options · live · read-only",
    icon="🏠",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)
df, context = ui.load_enriched_chain(products, settings)

if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

# --------------------------------------------------------------------------
# Expiry snapshot
# --------------------------------------------------------------------------

calls = df[df["is_call"]]
puts = df[~df["is_call"]]

call_oi = float(calls["oi_contracts"].fillna(0).sum())
put_oi = float(puts["oi_contracts"].fillna(0).sum())
pcr = (put_oi / call_oi) if call_oi > 0 else float("nan")

spot = context["spot"]
atm_strike = float("nan")
if not df.empty:
    nearest = df.iloc[(df["strike"] - spot).abs().argsort()[:1]]
    atm_strike = float(nearest["strike"].iloc[0])

atm_pair = (df[df["strike"] == atm_strike]
            if not math.isnan(atm_strike) else df.iloc[0:0])
atm_iv = float(atm_pair["iv_pct"].mean()) if not atm_pair.empty else float("nan")

liquid = df[df["two_sided"] & (df["spread_pct"] <= 25)]
health_pct = (len(liquid) / len(df) * 100.0) if len(df) else 0.0

if health_pct >= 50:
    health_tone, health_word = "good", "CHAIN HEALTHY"
elif health_pct >= 20:
    health_tone, health_word = "warn", "THIN CHAIN"
else:
    health_tone, health_word = "critical", "VERY ILLIQUID"

st.markdown(theme.section("Expiry snapshot",
                          f"{len(liquid)} of {len(df)} contracts tradable"),
            unsafe_allow_html=True)

st.markdown(theme.stat_row([
    theme.stat("ATM strike",
               f"{atm_strike:,.0f}" if not math.isnan(atm_strike) else "—"),
    theme.stat("ATM IV", f"{atm_iv:.1f}%" if not math.isnan(atm_iv) else "—",
               sub="average of both sides"),
    theme.stat("Put/Call OI", f"{pcr:.2f}" if not math.isnan(pcr) else "—",
               sub="above 1 = put-heavy"),
    theme.stat("Total OI", f"{call_oi + put_oi:,.0f}", sub="contracts"),
]), unsafe_allow_html=True)

st.markdown(
    theme.badge(health_word, health_tone)
    + f'<span style="color:{theme.INK_3};font-size:0.82rem">'
    f'contracts with a two-sided book and under 25% spread: '
    f'<b style="color:{theme.INK_2}">{health_pct:.0f}%</b></span>',
    unsafe_allow_html=True,
)

if health_pct < 20:
    st.warning(
        "Liquidity is very thin on this expiry. On a chain like this the "
        "scanner's 'opportunities' are not real - the spread takes them the "
        "moment an order goes in. Try the nearest weekly or daily expiry."
    )

# --------------------------------------------------------------------------
# Modules
# --------------------------------------------------------------------------

st.markdown(theme.section("Modules", "switch from the left sidebar"),
            unsafe_allow_html=True)

st.markdown(theme.card_grid([
    theme.nav_card("📈", "Live Chain",
                   "Calls and puts side by side, dead strikes auto-hidden, an "
                   "OI profile and a full cost-of-trading breakdown."),
    theme.nav_card("⏳", "Theta Decay",
                   "Repricing-based burn ranking, an hour-by-hour curve and a "
                   "multi-leg basket - all net of fees."),
    theme.nav_card("🌊", "IV Skew",
                   "The volatility smile, 25Δ risk reversal and butterfly, and "
                   "the ATM IV curve across expiries."),
    theme.nav_card("🎯", "Payoff Builder",
                   "Eight preset strategies, executable fills, expiry and T+0 "
                   "curves, break-evens and net greeks."),
    theme.nav_card("🔎", "Mispricing",
                   "Put-call parity, vertical bounds, butterfly convexity and "
                   "box spreads - model-free and fee-adjusted."),
    theme.nav_card("📐", "Delta Filter",
                   "Pick strikes by delta band, with live bid/ask and "
                   "net-of-cost theta."),
    theme.nav_card("🌡️", "Vol Regime",
                   "A VIX-style index at 30-day constant maturity, with a "
                   "regime gate that says whether your condition is met."),
]), unsafe_allow_html=True)

st.caption("Settings are shared across every page, and your current view is "
           "kept in the URL - bookmark it to come back to it.")

ui.render_diagnostics(context, df, settings)

st.caption(
    "MMC Delta Scanner · Data: api.india.delta.exchange public endpoints · "
    "Read-only · This tool displays market data, not trading advice."
)

ui.maybe_auto_refresh(settings)
