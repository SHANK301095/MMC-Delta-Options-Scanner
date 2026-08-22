"""
MMC Delta Scanner — Home
========================
Run with:  streamlit run app.py

Read-only scanner for Delta Exchange India BTC/ETH options.
No API key. No secrets. No order placement code anywhere in this project.
"""

from __future__ import annotations

import math

import streamlit as st

from mmc_core import delta_api as api
from mmc_core import ui_common as ui

ui.page_setup(
    "Home",
    "Delta Exchange India · BTC & ETH options · live market data · read-only",
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

st.markdown("---")

# --------------------------------------------------------------------------
# Snapshot of the selected expiry
# --------------------------------------------------------------------------

calls = df[df["is_call"]]
puts = df[~df["is_call"]]

call_oi = float(calls["oi_contracts"].fillna(0).sum())
put_oi = float(puts["oi_contracts"].fillna(0).sum())
pcr = (put_oi / call_oi) if call_oi > 0 else float("nan")

spot = context["spot"]
atm_row = df.iloc[(df["strike"] - spot).abs().argsort()[:1]] if not df.empty else None
atm_strike = float(atm_row["strike"].iloc[0]) if atm_row is not None and len(atm_row) else float("nan")

atm_pair = df[df["strike"] == atm_strike] if not math.isnan(atm_strike) else df.iloc[0:0]
atm_iv = float(atm_pair["iv_pct"].mean()) if not atm_pair.empty else float("nan")

st.markdown("### 📌 Expiry Snapshot")
s1, s2, s3, s4 = st.columns(4)
s1.metric("ATM Strike", f"{atm_strike:,.0f}" if not math.isnan(atm_strike) else "—")
s2.metric("ATM IV", f"{atm_iv:.1f}%" if not math.isnan(atm_iv) else "—")
s3.metric("Put/Call OI Ratio", f"{pcr:.2f}" if not math.isnan(pcr) else "—")
s4.metric("Total OI (contracts)", f"{call_oi + put_oi:,.0f}")

liquid = df[df["two_sided"] & (df["spread_pct"] <= 25)]
health_pct = (len(liquid) / len(df) * 100.0) if len(df) else 0.0

if health_pct >= 50:
    badge = '<span class="mmc-pill mmc-ok">CHAIN HEALTHY</span>'
elif health_pct >= 20:
    badge = '<span class="mmc-pill mmc-warn">THIN CHAIN</span>'
else:
    badge = '<span class="mmc-pill mmc-bad">VERY ILLIQUID</span>'

st.markdown(
    f"{badge} {len(liquid)} of {len(df)} contracts have a two-sided book "
    f"with spread under 25% (**{health_pct:.0f}%**).",
    unsafe_allow_html=True,
)

if health_pct < 20:
    st.warning(
        "Is expiry par liquidity bahut kam hai. Aise chain par scanner ke "
        "'opportunities' real nahi hote — order daalte hi spread kha jaata hai. "
        "Nearest weekly/daily expiry try karein."
    )

st.markdown("---")

# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------

st.markdown("### 🧭 Modules")

n1, n2 = st.columns(2)
with n1:
    st.markdown(
        "#### 📈 Live Chain + Liquidity Filter\n"
        "Call/Put side-by-side chain, dead strikes auto-hidden, "
        "OI profile, aur poora **cost of trading** breakdown."
    )
    st.markdown(
        "#### ⏳ Theta Decay Calculator\n"
        "Repricing-based burn ranking, hour-by-hour curve, "
        "multi-leg basket — sab **net of fees**."
    )
    st.markdown(
        "#### 🌊 IV Skew & Term Structure\n"
        "Volatility smile, 25Δ risk reversal / butterfly, "
        "aur expiries ke aar-paar ATM IV curve."
    )
with n2:
    st.markdown(
        "#### 🎯 Payoff Builder\n"
        "8 preset strategies, executable fills (ask/bid), "
        "expiry + T+0 curves, break-evens, net greeks."
    )
    st.markdown(
        "#### 🔎 Mispricing Scanner\n"
        "Put-call parity, vertical bounds, butterfly convexity, "
        "box spreads — model-free aur fee-adjusted."
    )
    st.markdown(
        "#### ⚙️ Sidebar\n"
        "Price basis, fee model, auto-refresh, "
        "aur **Save** se settings agli baar bhi yaad rahengi."
    )

st.info("Left sidebar se page switch kijiye. Saari settings har page par "
        "same rehti hain — ek baar set karke **💾 Save** dabaiye.")

ui.render_diagnostics(context, df, settings)

st.markdown("---")
st.caption(
    "MMC Delta Scanner v2.0 · Data: api.india.delta.exchange public endpoints "
    "· Read-only · Ye tool sirf market data dikhata hai, trading advice nahi."
)

ui.maybe_auto_refresh(settings)
