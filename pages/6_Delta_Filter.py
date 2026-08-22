"""
MMC Delta Scanner — Delta Filter + Live Rates
=============================================
Ek hi sawaal ka jawab: "mujhe X delta ke options chahiye — abhi ke rate kya hain?"

Traders strike ko delta se chunte hain, strike price se nahi. "25 delta put
bech do" apne aap mein ek poora instruction hai, aur wo har expiry par alag
strike ban jaata hai. Ye page delta ko primary control banata hai aur strike
ko result.

Band ABSOLUTE delta par lagta hai — 25 maangne par 0.25 delta call aur −0.25
delta put dono aate hain, kyunki wahi market convention hai.

WHY THE PRICES HERE ARE NOT MARK PRICE
--------------------------------------
Har row "Buy @" aur "Sell @" dikhata hai — sidebar ke price basis se. Default
Realistic hai: kharidte waqt ASK, bechte waqt BID. Mark price par koi fill
nahi hota, aur is chain par spreads chaude hain.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import delta_api as api
from mmc_core import ui_common as ui

ui.page_setup(
    "Delta Filter",
    "Delta band se strike chuniye · live bid/ask · fees aur spread ke baad",
    icon="📐",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)

# Delta control is page ka main control hai, isliye page par hai, sidebar mein
# nahi — aur sidebar wala band off kar diya taaki do jagah ek hi filter na ho.
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

st.markdown("### 📐 Kaunsa Delta chahiye")

# Quick-picks pehle chalne chahiye: ye slider ki value session_state mein set
# karte hain, aur Streamlit widget ko uske banne ke BAAD set karna allowed
# nahi hai.
PRESETS = {
    "Deep OTM · 5–15Δ": (5, 15),
    "Classic short · 15–25Δ": (15, 25),
    "Aggressive · 25–40Δ": (25, 40),
    "ATM · 40–60Δ": (40, 60),
    "Directional · 60–85Δ": (60, 85),
    "Sab dikhao · 0–100Δ": (0, 100),
}

if "delta_band_main" not in st.session_state:
    st.session_state["delta_band_main"] = (15, 25)

st.caption("Jaldi ke liye ek preset dabaiye, ya neeche slider se apni range banaiye.")
cols = st.columns(len(PRESETS))
for col, (label, rng) in zip(cols, PRESETS.items()):
    with col:
        if st.button(label, width="stretch", key=f"preset_{rng[0]}_{rng[1]}"):
            st.session_state["delta_band_main"] = rng
            st.rerun()

band = st.slider(
    "Delta band  (|Δ| × 100)", 0, 100, key="delta_band_main",
    help="Absolute delta. 25 maangne par 0.25 call aur −0.25 put dono aayenge.",
)

liq["delta_band"] = (float(band[0]), float(band[1]))

filtered = ui.apply_liquidity_filter(df, **liq)

# --------------------------------------------------------------------------
# Kya mila
# --------------------------------------------------------------------------

in_band_before_liquidity = int(ui.delta_band_mask(df, liq["delta_band"]).sum())
dropped_by_liquidity = in_band_before_liquidity - len(filtered)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Band mein contracts", f"{len(filtered)}")
k2.metric("Liquidity ne hataye", f"{dropped_by_liquidity}",
          help="Ye contracts delta band mein the lekin spread / OI / two-sided "
               "book ke filter mein fail ho gaye.")
k3.metric("Band", f"{band[0]}Δ – {band[1]}Δ")
k4.metric("Snapshot", api.fmt_ist(context["now"]).replace(" IST", ""),
          help="Sidebar ke refresh window par update hota hai.")

if filtered.empty:
    if in_band_before_liquidity == 0:
        st.warning(
            f"Is expiry par **{band[0]}Δ – {band[1]}Δ** ka koi contract hai hi nahi. "
            "Chain ka delta range neeche wale chart mein dekh lijiye — aksar "
            "near-expiry par delta ekdam 0 se 100 par kood jaata hai aur "
            "beech ki values milti hi nahi."
        )
    else:
        st.warning(
            f"Band mein **{in_band_before_liquidity}** contracts the, lekin "
            "sab liquidity filter mein nikal gaye. Sidebar mein spread limit "
            "badhaiye ya two-sided requirement hataiye — par yaad rahe, wo "
            "contracts practically tradable nahi hain."
        )
    ui.render_diagnostics(context, df, settings)
    ui.maybe_auto_refresh(settings)
    st.stop()

# --------------------------------------------------------------------------
# Live rates table
# --------------------------------------------------------------------------

st.markdown("### 💹 Live Rates")

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
    width="stretch", height=460,
)

st.caption(
    f"1 lot = {cv:g} {settings['underlying']} · ₹ conversion @ {usdinr:.2f} · "
    f"Price basis: **{settings['price_mode']}** · "
    "**Net θ %/day** = ek din ka decay minus ek round-trip ka fee+spread. "
    "Yahi wo number hai jo batata hai ki premium bechna faayde ka hai ya nahi."
)

neg = tbl[tbl["Net θ %/day"] < 0]
if not neg.empty:
    st.error(
        f"⚠️ **{len(neg)} contracts par net theta negative hai.** Ek din ka decay "
        "round-trip cost se kam hai — in par premium bechna pehle din se hi "
        "ghaata hai, chahe delta band bilkul aapki pasand ka ho."
    )

stale = work[work["is_stale"].fillna(False)]
if not stale.empty:
    st.warning(f"⏱️ **{len(stale)}** contracts ki quote 2 minute se purani hai. "
               "Unke 'live' rate abhi live nahi hain.")

# --------------------------------------------------------------------------
# Band chain par kahan baitha hai
# --------------------------------------------------------------------------

st.markdown("### 🗺️ Band chain par kahan hai")
st.caption("Delta ek abstract number hai — ye chart batata hai ki aapki range "
           "spot se kitni door padti hai, aur wahan contracts hain bhi ya nahi.")

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
# Har side ka closest strike
# --------------------------------------------------------------------------

target = (band[0] + band[1]) / 2.0
st.markdown(f"### 🎯 {target:.0f}Δ ke sabse kareeb (band ka madhya)")

pick_cols = st.columns(2)
for col, is_call, name in ((pick_cols[0], True, "CALL"), (pick_cols[1], False, "PUT")):
    side = work[work["is_call"] == is_call]
    with col:
        if side.empty:
            st.info(f"Band mein koi {name} nahi.")
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
    "🧠 **Delta ko probability samajhne ki galti mat kijiye.** 25Δ ka matlab "
    "*lagbhag* 25% chance hai ki option ITM expire hoga — ye ek approximation "
    "hai, guarantee nahi, aur skew wale chain par ye aur bhi dheeli padti hai. "
    "Aur jitna kam delta, utna kam premium — lekin round-trip cost premium ke "
    "percent mein utna hi bada. Isliye **Net θ %/day** column hi asli faisla "
    "karne wala number hai, delta nahi."
)

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
