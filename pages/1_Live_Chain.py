"""
MMC Delta Scanner — Live Chain + Liquidity Filter
=================================================
Call/Put side-by-side chain for one Delta Exchange India expiry, with the
untradable strikes filtered out before they ever reach your eyes.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import delta_api as api
from mmc_core import ui_common as ui

ui.page_setup(
    "Live Chain",
    "Two-sided book, real spreads, Greeks in ₹ per lot — dead strikes removed",
    icon="📈",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)
liq = ui.render_liquidity_controls(prefix="chain")

df, context = ui.load_enriched_chain(products, settings)
if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

spot = context["spot"]
filtered = ui.apply_liquidity_filter(
    df,
    max_spread_pct=liq["max_spread_pct"],
    min_oi=liq["min_oi"],
    min_volume=liq["min_volume"],
    max_moneyness_pct=liq["max_moneyness_pct"],
    require_two_sided=liq["require_two_sided"],
)

removed = len(df) - len(filtered)
st.caption(f"🧹 Liquidity filter ne **{removed}** untradable contracts hataye · "
           f"**{len(filtered)}** bache")

if filtered.empty:
    st.warning("Filter ke baad kuch nahi bacha. Sidebar mein spread limit badhaiye "
               "ya strike range widen kijiye.")
    ui.render_diagnostics(context, df, settings)
    st.stop()

# --------------------------------------------------------------------------
# Build the side-by-side chain
# --------------------------------------------------------------------------

SIDE_COLS = [
    "oi_contracts", "volume", "iv_pct", "delta",
    "theta_lot_inr", "best_bid", "best_ask", "spread_pct", "mark_price",
]

calls = filtered[filtered["is_call"]][["strike"] + SIDE_COLS].copy()
puts = filtered[~filtered["is_call"]][["strike"] + SIDE_COLS].copy()

calls = calls.rename(columns={c: f"C_{c}" for c in SIDE_COLS})
puts = puts.rename(columns={c: f"P_{c}" for c in SIDE_COLS})

chain = pd.merge(calls, puts, on="strike", how="outer").sort_values("strike")
chain = chain.reset_index(drop=True)

# ATM = strike closest to spot among the rows actually displayed.
if not chain.empty:
    atm_idx = int((chain["strike"] - spot).abs().idxmin())
    atm_strike = float(chain.loc[atm_idx, "strike"])
else:
    atm_idx, atm_strike = None, float("nan")

display = chain[[
    "C_oi_contracts", "C_volume", "C_iv_pct", "C_delta", "C_theta_lot_inr",
    "C_best_bid", "C_best_ask", "C_spread_pct",
    "strike",
    "P_spread_pct", "P_best_bid", "P_best_ask",
    "P_theta_lot_inr", "P_delta", "P_iv_pct", "P_volume", "P_oi_contracts",
]].copy()

# Column names MUST be unique - pandas Styler refuses to apply row styling to a
# frame with duplicate columns, and a call/put chain naturally wants to repeat
# every header. C/P prefixes solve both problems and read better anyway.
display.columns = [
    "C OI", "C Vol", "C IV%", "C Δ", "C θ₹",
    "C Bid", "C Ask", "C Spr%",
    "STRIKE",
    "P Spr%", "P Bid", "P Ask",
    "P θ₹", "P Δ", "P IV%", "P Vol", "P OI",
]

st.markdown("### 📊 Option Chain  ·  ⬅️ CALLS  |  PUTS ➡️")


def _highlight(row):
    """Tint the ATM row and shade the ITM side of each wing."""
    styles = [""] * len(row)
    strike = row["STRIKE"]
    if pd.isna(strike):
        return styles

    if not math.isnan(atm_strike) and abs(strike - atm_strike) < 1e-9:
        return ["background-color: #1f3d5c; color: #ffffff; font-weight: 600"] * len(row)

    n = len(row)
    strike_pos = list(row.index).index("STRIKE")
    if strike < spot:
        # Calls are ITM on this row -> shade the left block.
        for i in range(0, strike_pos):
            styles[i] = "background-color: #14261c"
    else:
        # Puts are ITM on this row -> shade the right block.
        for i in range(strike_pos + 1, n):
            styles[i] = "background-color: #14261c"
    return styles


fmt = {}
for side in ("C", "P"):
    fmt[f"{side} OI"] = "{:,.0f}"
    fmt[f"{side} Vol"] = "{:,.0f}"
    fmt[f"{side} IV%"] = "{:.1f}"
    fmt[f"{side} Δ"] = "{:.3f}"
    fmt[f"{side} θ₹"] = "{:,.2f}"
    fmt[f"{side} Bid"] = "{:,.1f}"
    fmt[f"{side} Ask"] = "{:,.1f}"
    fmt[f"{side} Spr%"] = "{:.1f}"
fmt["STRIKE"] = "{:,.0f}"

styled = display.style.apply(_highlight, axis=1).format(fmt, na_rep="—")
st.dataframe(styled, width='stretch', height=560)

st.caption(
    "θ ₹/lot = ek lot ek din mein kitna premium khoyega (negative = buyer ka "
    f"loss / seller ka gain). 1 lot = {context['contract_value']:g} "
    f"{settings['underlying']}. Spr% = (Ask − Bid) ÷ Mid."
)

# --------------------------------------------------------------------------
# Open Interest profile
# --------------------------------------------------------------------------

st.markdown("### 🏔️ Open Interest Profile")

oi_frame = chain[["strike", "C_oi_contracts", "P_oi_contracts"]].fillna(0)
st.plotly_chart(
    ch.oi_profile(oi_frame["strike"].tolist(),
                  oi_frame["C_oi_contracts"].tolist(),
                  oi_frame["P_oi_contracts"].tolist(), spot),
    width="stretch",
)

c_oi = filtered[filtered["is_call"]]["oi_contracts"].fillna(0)
p_oi = filtered[~filtered["is_call"]]["oi_contracts"].fillna(0)

m1, m2, m3 = st.columns(3)
if not c_oi.empty and c_oi.sum() > 0:
    top_call = filtered[filtered["is_call"]].loc[c_oi.idxmax(), "strike"]
    m1.metric("Max Call OI strike", f"{top_call:,.0f}",
              help="Aksar resistance / upper pin ke roop mein dekha jaata hai.")
if not p_oi.empty and p_oi.sum() > 0:
    top_put = filtered[~filtered["is_call"]].loc[p_oi.idxmax(), "strike"]
    m2.metric("Max Put OI strike", f"{top_put:,.0f}",
              help="Aksar support / lower pin ke roop mein dekha jaata hai.")
pcr = (p_oi.sum() / c_oi.sum()) if c_oi.sum() > 0 else float("nan")
m3.metric("PCR (filtered)", f"{pcr:.2f}" if not math.isnan(pcr) else "—")

# --------------------------------------------------------------------------
# Data-quality warnings that actually matter for trading
# --------------------------------------------------------------------------

st.markdown("### ⚠️ Watch-outs on this chain")

warn_rows = []

stale = filtered[filtered["is_stale"].fillna(False)]
if not stale.empty:
    warn_rows.append(f"**{len(stale)}** contracts ki quote 2 minute se purani hai — "
                     "inka mark price ghost data ho sakta hai.")

wide = filtered[filtered["spread_pct"] > 15]
if not wide.empty:
    warn_rows.append(f"**{len(wide)}** contracts ka spread 15% se zyada hai — "
                     "entry aur exit dono par kata lagega.")

gap = filtered[filtered["model_gap_pct"].abs() > 20]
if not gap.empty:
    warn_rows.append(f"**{len(gap)}** contracts par Black-Scholes value aur exchange "
                     "mark price mein 20%+ ka farak hai — ya IV galat hai, "
                     "ya quote stale hai.")

if warn_rows:
    for w in warn_rows:
        st.markdown(f"- {w}")
else:
    st.success("Filtered chain saaf hai — koi stale quote ya extreme spread nahi mila.")

st.markdown("### 💸 Cost of Trading (fees + spread)")
st.caption("Delta ki fee NOTIONAL par lagti hai (premium par nahi), phir "
           "premium ka cap lagta hai. Sasti OTM strikes par round-trip cost "
           "aksar premium ka bada hissa kha jaata hai.")

cost_tbl = filtered[["strike", "is_call", "mark_price", "fee_pct_of_premium",
                     "slippage_pct", "total_cost_pct",
                     "theta_pct_of_premium", "net_theta_pct_day",
                     "fee_capped"]].copy()
cost_tbl["Type"] = cost_tbl["is_call"].map({True: "CALL", False: "PUT"})
cost_tbl = cost_tbl[["Type", "strike", "mark_price", "fee_pct_of_premium",
                     "slippage_pct", "total_cost_pct",
                     "theta_pct_of_premium", "net_theta_pct_day", "fee_capped"]]
cost_tbl.columns = ["Type", "Strike", "Mark $", "Fee % prem", "Slippage %",
                    "Total cost %", "Gross θ %/day", "Net θ %/day",
                    "Cap binds"]
cost_tbl = cost_tbl.sort_values("Net θ %/day", ascending=False)

st.dataframe(
    cost_tbl.style.format({
        "Strike": "{:,.0f}", "Mark $": "${:,.2f}", "Fee % prem": "{:.2f}%",
        "Slippage %": "{:.2f}%", "Total cost %": "{:.2f}%",
        "Gross θ %/day": "{:.2f}%", "Net θ %/day": "{:+.2f}%",
    }, na_rep="—").background_gradient(
        subset=["Net θ %/day"], cmap="RdYlGn"),
    width="stretch", height=340,
)

neg = cost_tbl[cost_tbl["Net θ %/day"] < 0]
if not neg.empty:
    st.error(f"⚠️ **{len(neg)} strikes par net theta negative hai** — "
             "matlab ek din ka decay round-trip cost se kam hai. In par "
             "premium bechna theoretically bhi loss-making hai.")

st.markdown("#### Spread map")
st.plotly_chart(
    ch.spread_heat(filtered["strike"].tolist(),
                   filtered["spread_pct"].tolist(),
                   spot, liq["max_spread_pct"]),
    width="stretch",
)

with st.expander("🔍 Full raw table (saare computed columns)"):
    raw_cols = [
        "symbol", "is_call", "strike", "mark_price", "mid", "best_bid", "best_ask",
        "spread_pct", "iv_pct", "delta", "gamma", "theta", "vega",
        "theta_lot_usd", "theta_lot_inr", "premium_lot_inr",
        "theta_pct_of_premium", "model_gap_pct",
        "oi_contracts", "volume", "quote_age_sec",
        "buy_price", "sell_price", "fee_rt_inr_lot", "fee_pct_of_premium",
        "slippage_pct", "total_cost_pct", "net_theta_pct_day",
    ]
    raw_cols = [c for c in raw_cols if c in filtered.columns]
    st.dataframe(filtered[raw_cols], width='stretch', height=380)

    st.download_button(
        "⬇️ Download this chain as CSV",
        data=filtered[raw_cols].to_csv(index=False).encode("utf-8"),
        file_name=(f"MMC_chain_{settings['underlying']}_"
                   f"{settings['expiry']['api_date']}.csv"),
        mime="text/csv",
    )

ui.render_diagnostics(context, df, settings)

ui.maybe_auto_refresh(settings)
