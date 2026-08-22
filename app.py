"""
MMC Delta Scanner — Home
========================
Run with:  streamlit run app.py

Delta Exchange India ke BTC/ETH options ka read-only scanner.
Koi API key, koi secret, koi order-placement code — kahin nahi.

Ye page ek hi kaam karta hai: chuni hui expiry ki halat ek nazar mein dikhana,
taaki aap sahi module par jaayein. Isliye yahan number kam hain, aur har number
ek faisle se juda hai.
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
    atm_strike = float(df.iloc[(df["strike"] - spot).abs().argsort()[:1]]["strike"].iloc[0])

atm_pair = df[df["strike"] == atm_strike] if not math.isnan(atm_strike) else df.iloc[0:0]
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
               sub="dono sides ka average"),
    theme.stat("Put/Call OI", f"{pcr:.2f}" if not math.isnan(pcr) else "—",
               sub="1 se upar = put-heavy"),
    theme.stat("Total OI", f"{call_oi + put_oi:,.0f}", sub="contracts"),
]), unsafe_allow_html=True)

st.markdown(
    theme.badge(health_word, health_tone)
    + f'<span style="color:{theme.INK_3};font-size:0.82rem">'
    f'two-sided book aur 25% se kam spread wale contracts: '
    f'<b style="color:{theme.INK_2}">{health_pct:.0f}%</b></span>',
    unsafe_allow_html=True,
)

if health_pct < 20:
    st.warning(
        "Is expiry par liquidity bahut kam hai. Aisi chain par scanner ke "
        "'opportunities' real nahi hote — order daalte hi spread kha jaata hai. "
        "Nearest weekly ya daily expiry try karein."
    )

# --------------------------------------------------------------------------
# Modules
# --------------------------------------------------------------------------

st.markdown(theme.section("Modules", "left sidebar se switch kijiye"),
            unsafe_allow_html=True)

st.markdown(theme.card_grid([
    theme.nav_card("📈", "Live Chain",
                   "Call/Put chain side by side, dead strikes auto-hidden, "
                   "OI profile aur poora cost-of-trading breakdown."),
    theme.nav_card("⏳", "Theta Decay",
                   "Repricing-based burn ranking, ghanta-ba-ghanta curve, "
                   "aur multi-leg basket — sab net of fees."),
    theme.nav_card("🌊", "IV Skew",
                   "Volatility smile, 25Δ risk reversal aur butterfly, "
                   "aur expiries ke aar-paar ATM IV curve."),
    theme.nav_card("🎯", "Payoff Builder",
                   "8 preset strategies, executable fills, expiry + T+0 "
                   "curves, break-evens aur net greeks."),
    theme.nav_card("🔎", "Mispricing",
                   "Put-call parity, vertical bounds, butterfly convexity "
                   "aur box spreads — model-free aur fee-adjusted."),
    theme.nav_card("📐", "Delta Filter",
                   "Delta band se strike chuniye, live bid/ask aur "
                   "net-of-cost theta ke saath."),
    theme.nav_card("🌡️", "Vol Regime",
                   "VIX-style index, 30-din constant maturity, aur ek "
                   "regime gate jo batata hai ki aapki condition poori hai ya nahi."),
]), unsafe_allow_html=True)

st.caption("Saari settings har page par same rehti hain — ek baar set karke "
           "sidebar mein **Save** dabaiye.")

ui.render_diagnostics(context, df, settings)

st.caption(
    "MMC Delta Scanner · Data: api.india.delta.exchange public endpoints · "
    "Read-only · Ye tool sirf market data dikhata hai, trading advice nahi."
)

ui.maybe_auto_refresh(settings)
