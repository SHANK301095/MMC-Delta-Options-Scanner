"""
MMC Delta Scanner - Delta Filter + Live Rates
=============================================
Answers one question: "I want options around X delta - what are they trading
at right now?"

Traders pick a strike by delta, not by strike price. "Sell the 25 delta put" is
a complete instruction on its own, and it lands on a different strike every
expiry. This page makes delta the primary control and the strike the result.

The band applies to ABSOLUTE delta - asking for 25 returns both the 0.25 delta
call and the -0.25 delta put, because that is the market convention.

WHY THE PRICES HERE ARE NOT MARK PRICE
--------------------------------------
Every row shows "Buy @" and "Sell @" from the sidebar's price basis. The
default is Realistic: the ASK when buying, the BID when selling. Nothing fills
at the mark price, and spreads on this chain are wide.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import delta_api as api
from mmc_core import theme
from mmc_core import ui_common as ui

ui.page_setup(
    "Delta Filter",
    "Pick strikes by delta band · live bid/ask · net of fees and spread",
    icon="📐",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)

# The delta control is this page's primary control, so it lives on the page
# rather than the sidebar - and the sidebar's band is switched off so the same
# filter does not appear twice.
liq = ui.render_liquidity_controls(prefix="dband", include_delta=False)

df, context = ui.load_enriched_chain(products, settings)
if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

spot = context["spot"]
cv = context["contract_value"]

# --------------------------------------------------------------------------
# Delta band control
# --------------------------------------------------------------------------

st.markdown(
    theme.section("Which delta do you want", "the band applies to absolute |Δ|"),
            unsafe_allow_html=True)

# The quick-picks must run first: they set the slider's value in session_state,
# and Streamlit does not allow setting a widget's value AFTER it is created.
PRESETS = {
    "Deep OTM · 5–15Δ": (5, 15),
    "Classic short · 15–25Δ": (15, 25),
    "Aggressive · 25–40Δ": (25, 40),
    "ATM · 40–60Δ": (40, 60),
    "Directional · 60–85Δ": (60, 85),
    "Show all · 0–100Δ": (0, 100),
}

if "delta_band_main" not in st.session_state:
    st.session_state["delta_band_main"] = (15, 25)

st.caption("Use a preset for speed, or set your own range with the slider below.")
cols = st.columns(len(PRESETS))
for col, (label, rng) in zip(cols, PRESETS.items(), strict=True):
    with col:
        if st.button(label, width="stretch", key=f"preset_{rng[0]}_{rng[1]}"):
            st.session_state["delta_band_main"] = rng
            st.rerun()

band = st.slider(
    "Delta band  (|Δ| × 100)", 0, 100, key="delta_band_main",
    help="Absolute delta. Asking for 25 returns both the 0.25 call and the "
         "-0.25 put.",
)

liq["delta_band"] = (float(band[0]), float(band[1]))

# The band is set after the sidebar on this page, so re-sync the URL.
ui.sync_url()

filtered = ui.apply_liquidity_filter(df, **liq)

# --------------------------------------------------------------------------
# What matched
# --------------------------------------------------------------------------

in_band_before_liquidity = int(ui.delta_band_mask(df, liq["delta_band"]).sum())
dropped_by_liquidity = in_band_before_liquidity - len(filtered)

st.markdown(theme.stat_row([
    theme.stat("Contracts in band", f"{len(filtered)}",
               sub=f"{band[0]}Δ – {band[1]}Δ", accent=True),
    theme.stat("Removed by liquidity", f"{dropped_by_liquidity}",
               sub="in band, but not tradable",
               tone="down" if dropped_by_liquidity > len(filtered) else ""),
    theme.stat("Price basis", settings["price_mode"].split(" (")[0],
               sub=f"1 lot = {cv:g} {settings['underlying']}"),
    theme.stat("Snapshot", api.fmt_ist(context["now"]).replace(" IST", ""),
               sub=f"every {settings['refresh_seconds']}s"),
]), unsafe_allow_html=True)

if filtered.empty:
    if in_band_before_liquidity == 0:
        st.markdown(theme.empty_state(
            "🎯", f"No contract exists between {band[0]}Δ and {band[1]}Δ",
            "Widen the band, or pick a different expiry. Near expiry, delta "
            "often jumps straight from 0 to 100 with nothing in between - the "
            "chart below shows this."
        ), unsafe_allow_html=True)
    else:
        st.markdown(theme.empty_state(
            "💧", f"{in_band_before_liquidity} were in band, all removed by the filter",
            "The delta was right; the liquidity was not. Raise the spread limit "
            "in the sidebar or drop the two-sided requirement - but remember "
            "those contracts are not practically tradable."
        ), unsafe_allow_html=True)
    ui.render_diagnostics(context, df, settings)
    ui.maybe_auto_refresh(settings)
    st.stop()

# --------------------------------------------------------------------------
# Live rates table
# --------------------------------------------------------------------------

st.markdown(
    theme.section("Live rates", "Buy @ / Sell @ follow the sidebar price basis"),
            unsafe_allow_html=True)

usdinr = settings["usdinr"]
work = filtered.copy()
work["abs_delta_pct"] = work["delta"].abs() * 100.0

tbl = pd.DataFrame({
    "Type": work["is_call"].map({True: "CALL", False: "PUT"}),
    "Strike": work["strike"],
    "Δ×100": work["abs_delta_pct"],
    "Δ": work["delta"],
    "Moneyness %": work["moneyness_pct"],
    "IV %": work["iv_pct"],
    "Bid $": work["best_bid"],
    "Ask $": work["best_ask"],
    "Mark $": work["mark_price"],
    "Buy @ $": work["buy_price"],
    "Sell @ $": work["sell_price"],
    "Premium ₹/lot": work["premium_lot_inr"],
    "Spread %": work["spread_pct"],
    "θ ₹/lot/day": work["theta_lot_inr"],
    "Cost % (fee+slip)": work["total_cost_pct"],
    "Net θ %/day": work["net_theta_pct_day"],
    "OI": work["oi_contracts"],
    "Quote age s": work["quote_age_sec"],
}).sort_values(["Type", "Δ×100"], ascending=[True, False]).reset_index(drop=True)

st.dataframe(
    tbl.style.format({
        "Strike": "{:,.0f}", "Δ×100": "{:.1f}", "Δ": "{:+.3f}",
        "Moneyness %": "{:+.1f}", "IV %": "{:.1f}",
        "Bid $": "${:,.2f}", "Ask $": "${:,.2f}", "Mark $": "${:,.2f}",
        "Buy @ $": "${:,.2f}", "Sell @ $": "${:,.2f}",
        "Premium ₹/lot": "₹{:,.2f}", "Spread %": "{:.1f}",
        "θ ₹/lot/day": "₹{:,.2f}", "Cost % (fee+slip)": "{:.2f}%",
        "Net θ %/day": "{:+.2f}%", "OI": "{:,.0f}", "Quote age s": "{:,.0f}",
    }, na_rep="—"),
    width="stretch", height=theme.table_height(len(tbl)), hide_index=True)

st.caption(
    f"1 lot = {cv:g} {settings['underlying']} · ₹ conversion @ {usdinr:.2f} · "
    f"Price basis: **{settings['price_mode']}** · "
    "**Net θ %/day** is one day's decay minus one round trip of fees and "
    "spread. That is the number that decides whether selling premium pays."
)

neg = tbl[tbl["Net θ %/day"] < 0]
if not neg.empty:
    st.error(
        f"⚠️ **Net theta is negative on {len(neg)} contracts.** One day's decay "
        "is smaller than the round-trip cost, so selling premium on them loses "
        "money from day one - however well the delta band suits you."
    )

stale = work[work["is_stale"].fillna(False)]
if not stale.empty:
    st.warning(f"⏱️ **{len(stale)}** contracts have quotes older than 2 minutes. "
               "Their 'live' rates are not currently live.")

# --------------------------------------------------------------------------
# Where the band sits on the chain
# --------------------------------------------------------------------------

st.markdown(theme.section("Where the band sits on the chain"), unsafe_allow_html=True)
st.caption("Delta is an abstract number - this chart shows how far from spot "
           "your range actually lands, and whether contracts exist there.")

valid = df[df["delta"].notna()].copy()
valid["abs_delta_pct"] = valid["delta"].abs() * 100.0
c_side = valid[valid["is_call"]].sort_values("strike")
p_side = valid[~valid["is_call"]].sort_values("strike")

st.plotly_chart(
    ch.delta_profile(c_side["strike"].tolist(), c_side["abs_delta_pct"].tolist(),
                     p_side["strike"].tolist(), p_side["abs_delta_pct"].tolist(),
                     spot, band=liq["delta_band"]),
    width="stretch",
)

# --------------------------------------------------------------------------
# Closest strike on each side
# --------------------------------------------------------------------------

target = (band[0] + band[1]) / 2.0
st.markdown(theme.section(f"Closest to {target:.0f}Δ",
                          "the middle of your band"), unsafe_allow_html=True)

pick_cols = st.columns(2)
for col, is_call, name in ((pick_cols[0], True, "CALL"), (pick_cols[1], False, "PUT")):
    side = work[work["is_call"] == is_call]
    with col:
        if side.empty:
            st.info(f"No {name} in the band.")
            continue
        best = side.iloc[(side["abs_delta_pct"] - target).abs().argsort()[:1]].iloc[0]
        st.markdown(f"**{name} {best['strike']:,.0f}**")
        st.markdown(
            f"- Δ **{best['delta']:+.3f}** ({best['abs_delta_pct']:.1f}Δ)\n"
            f"- Bid **${best['best_bid']:,.2f}** / Ask **${best['best_ask']:,.2f}**"
            f"  ·  spread {best['spread_pct']:.1f}%\n"
            f"- Premium **₹{best['premium_lot_inr']:,.2f}** per lot\n"
            f"- θ **₹{best['theta_lot_inr']:,.2f}** /lot/day\n"
            f"- Round-trip cost **{best['total_cost_pct']:.2f}%** of premium\n"
            f"- Net θ **{best['net_theta_pct_day']:+.2f}%** /day"
        )

st.download_button(
    "⬇️ Download in-band contracts as CSV",
    data=tbl.to_csv(index=False).encode("utf-8"),
    file_name=(f"MMC_delta_{band[0]}-{band[1]}_{settings['underlying']}_"
               f"{settings['expiry']['api_date']}.csv"),
    mime="text/csv",
)

st.info(
    "🧠 **Do not mistake delta for probability.** 25Δ means *roughly* a 25% "
    "chance of expiring in the money - an approximation, not a guarantee, and a "
    "looser one on a skewed chain. And the lower the delta, the smaller the "
    "premium, while the round-trip cost grows as a percentage of it. That is "
    "why the **Net θ %/day** column, not delta, is the deciding number."
)

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
