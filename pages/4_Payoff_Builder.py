"""
MMC Delta Scanner — Strategy Payoff Builder
===========================================
Multi-leg payoff with three things most retail payoff tools get wrong:

  1. ENTRY PRICES ARE EXECUTABLE, NOT MARK.
     You buy at the ask and sell at the bid. On a chain where a quarter of
     strikes carry a 20% spread, a mark-priced payoff diagram is fiction.

  2. FEES ARE INCLUDED, BOTH SIDES.
     Delta charges on notional with a premium cap, plus GST. On cheap OTM
     legs the round trip can eat a large share of the credit.

  3. THE T+0 CURVE IS SHOWN NEXT TO THE EXPIRY CURVE.
     The expiry payoff is the shape people fall in love with. The T+0 curve
     is the one that actually decides whether you survive to see it.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import fees as fx
from mmc_core import options_math as om
from mmc_core import theme
from mmc_core import ui_common as ui

ui.page_setup(
    "Payoff Builder",
    "Multi-leg P&L at expiry and today · executable fills · fees included",
    icon="🎯",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)
liq = ui.render_liquidity_controls(prefix="payoff")

df, context = ui.load_enriched_chain(products, settings)
if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

spot = context["spot"]
cv = context["contract_value"]
usdinr = settings["usdinr"]
r = settings["risk_free"]
cfg = settings["fee_cfg"]

filtered = ui.apply_liquidity_filter(df, **liq)

if filtered.empty:
    st.markdown(theme.empty_state(
        "🎯", "No legs are available",
        "A payoff needs at least one tradable contract. Loosen the liquidity "
        "filter in the sidebar."
    ), unsafe_allow_html=True)
    ui.render_diagnostics(context, df, settings)
    ui.maybe_auto_refresh(settings)
    st.stop()


def leg_label(row) -> str:
    return (f"{'C' if row['is_call'] else 'P'} {row['strike']:,.0f}  "
            f"(IV {row['iv_pct']:.0f}%, Δ {row['delta']:+.2f})")


label_to_row = {leg_label(row): row for _, row in filtered.iterrows()}
options_list = list(label_to_row.keys())

strikes_avail = sorted(filtered["strike"].unique().tolist())


def nearest_strike(target: float) -> float:
    return min(strikes_avail, key=lambda k: abs(k - target))


def find_label(strike: float, is_call: bool):
    sub = filtered[(filtered["strike"] == strike)
                   & (filtered["is_call"] == is_call)]
    return leg_label(sub.iloc[0]) if not sub.empty else None


# ==========================================================================
# Preset strategies
# ==========================================================================

st.markdown(theme.section("1 · Choose a strategy"), unsafe_allow_html=True)

PRESETS = [
    "Custom (empty)", "Short Straddle", "Long Straddle",
    "Short Strangle", "Long Strangle", "Iron Condor",
    "Bull Call Spread", "Bear Put Spread", "Covered-style Short Put",
]

pc1, pc2 = st.columns([2, 1])
with pc1:
    preset = st.selectbox("Preset", PRESETS, index=1, key="preset_pick")
with pc2:
    width_pct = st.slider("Wing width (% from spot)", 1, 30, 5,
                          help="How far out the wings sit on a strangle, "
                               "condor or spread.")

atm = nearest_strike(spot)
up = nearest_strike(spot * (1 + width_pct / 100.0))
dn = nearest_strike(spot * (1 - width_pct / 100.0))
up2 = nearest_strike(spot * (1 + 2 * width_pct / 100.0))
dn2 = nearest_strike(spot * (1 - 2 * width_pct / 100.0))


def build_preset(name: str) -> list:
    """Returns a list of (strike, is_call, side) tuples."""
    if name == "Short Straddle":
        return [(atm, True, "Sell"), (atm, False, "Sell")]
    if name == "Long Straddle":
        return [(atm, True, "Buy"), (atm, False, "Buy")]
    if name == "Short Strangle":
        return [(up, True, "Sell"), (dn, False, "Sell")]
    if name == "Long Strangle":
        return [(up, True, "Buy"), (dn, False, "Buy")]
    if name == "Iron Condor":
        return [(up, True, "Sell"), (up2, True, "Buy"),
                (dn, False, "Sell"), (dn2, False, "Buy")]
    if name == "Bull Call Spread":
        return [(atm, True, "Buy"), (up, True, "Sell")]
    if name == "Bear Put Spread":
        return [(atm, False, "Buy"), (dn, False, "Sell")]
    if name == "Covered-style Short Put":
        return [(dn, False, "Sell")]
    return []


seed_rows = []
for strike, is_call, side in build_preset(preset):
    lbl = find_label(strike, is_call)
    if lbl:
        seed_rows.append({"Leg": lbl, "Side": side, "Lots": 1})

if not seed_rows:
    fallback = find_label(atm, True)
    seed_rows = [{"Leg": fallback or options_list[0], "Side": "Sell", "Lots": 1}]

st.markdown(theme.section("2 · Adjust the legs"), unsafe_allow_html=True)
st.caption("Rows can be added or deleted. Changing the preset resets the table.")

edited = st.data_editor(
    pd.DataFrame(seed_rows),
    num_rows="dynamic",
    width="stretch",
    key=f"payoff_{preset}_{width_pct}",
    column_config={
        "Leg": st.column_config.SelectboxColumn("Leg", options=options_list,
                                                required=True, width="large"),
        "Side": st.column_config.SelectboxColumn("Side", options=["Buy", "Sell"],
                                                 required=True),
        "Lots": st.column_config.NumberColumn("Lots", min_value=1,
                                              max_value=100000, step=1,
                                              required=True),
    },
)

legs = []
for _, e in edited.iterrows():
    label = e.get("Leg")
    if label not in label_to_row:
        continue
    try:
        n_lots = int(e.get("Lots") or 0)
    except (TypeError, ValueError):
        continue
    if n_lots <= 0:
        continue
    legs.append({"row": label_to_row[label], "side": e.get("Side"),
                 "lots": n_lots, "label": label})

if not legs:
    st.info("Add at least one valid leg.")
    ui.render_diagnostics(context, df, settings)
    ui.maybe_auto_refresh(settings)
    st.stop()

# ==========================================================================
# Entry economics — executable prices + fees
# ==========================================================================

mode = settings["price_mode_key"]
net_cash_usd = 0.0        # positive = you PAID, negative = you RECEIVED
total_fee_usd = 0.0
net_delta = net_gamma = net_theta = net_vega = 0.0
leg_rows = []

for L in legs:
    row, n_lots = L["row"], L["lots"]
    is_buy = L["side"] == "Buy"
    sign = 1.0 if is_buy else -1.0

    entry_px = fx.execution_price(float(row["mark_price"]),
                                  float(row["best_bid"]), float(row["best_ask"]),
                                  is_buy=is_buy, mode=mode)
    if entry_px is None or math.isnan(entry_px):
        entry_px = float(row["mark_price"])

    cash = sign * entry_px * n_lots * cv          # USD
    entry_fee = fx.leg_fee_usd(entry_px, spot, n_lots, cv, cfg,
                               is_maker=cfg.entry_is_maker)
    exit_fee = fx.leg_fee_usd(entry_px, spot, n_lots, cv, cfg,
                              is_maker=cfg.exit_is_maker)

    net_cash_usd += cash
    total_fee_usd += entry_fee + exit_fee

    net_delta += sign * float(row["delta"]) * n_lots * cv
    net_gamma += sign * float(row["gamma"]) * n_lots * cv
    net_theta += sign * float(row["theta"]) * n_lots * cv
    net_vega += sign * float(row["vega"]) * n_lots * cv

    slip = float(row["mark_price"]) - entry_px if not is_buy else \
        entry_px - float(row["mark_price"])

    leg_rows.append({
        "Leg": L["label"], "Side": L["side"], "Lots": n_lots,
        "Fill price $": entry_px,
        "vs Mark $": -slip,
        "Cash ₹": cash * usdinr,
        "Fees ₹ (both sides)": (entry_fee + exit_fee) * usdinr,
    })

net_cash_inr = net_cash_usd * usdinr
total_fee_inr = total_fee_usd * usdinr
net_theta_inr = net_theta * usdinr
net_vega_inr = net_vega * usdinr

st.markdown(
    theme.section("3 · Entry economics", "executable fills, fees on both sides"),
            unsafe_allow_html=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Net premium",
          f"₹{abs(net_cash_inr):,.2f}",
          delta="DEBIT (paid)" if net_cash_usd > 0 else "CREDIT (received)",
          delta_color="inverse" if net_cash_usd > 0 else "normal")
m2.metric("Round-trip fees", f"₹{total_fee_inr:,.2f}",
          help="Entry + exit, GST included, premium cap applied.")
m3.metric("Net θ / day", f"₹{net_theta_inr:,.2f}",
          help="Positive means decay works in your favour.")
m4.metric("Net Δ", f"{net_delta:+.5f} {settings['underlying']}")

g1, g2, g3 = st.columns(3)
g1.metric("Net Vega", f"₹{net_vega_inr:,.2f} / vol pt")
g2.metric("Net Gamma", f"{net_gamma:+.8f}")
if abs(net_cash_inr) > 0:
    g3.metric("Fees as % of premium",
              f"{total_fee_inr / abs(net_cash_inr) * 100:.2f}%")

st.dataframe(
    pd.DataFrame(leg_rows).style.format({
        "Fill price $": "${:,.2f}", "vs Mark $": "${:+,.2f}",
        "Cash ₹": "₹{:,.2f}", "Fees ₹ (both sides)": "₹{:,.2f}",
    }),
    width="stretch", hide_index=True)

if mode == "realistic":
    st.caption("💡 *Fill price* is the ASK when buying and the BID when "
               "selling. *vs Mark* shows what crossing the spread cost on "
               "each leg.")

# ==========================================================================
# Payoff
# ==========================================================================

st.markdown(theme.section("4 · Payoff"), unsafe_allow_html=True)

rng = st.slider("Spot range (± % from now)", 5, 60, 20)
lo_s, hi_s = spot * (1 - rng / 100.0), spot * (1 + rng / 100.0)
spots = np.linspace(lo_s, hi_s, 401)

include_fees = st.checkbox("Include fees in the payoff", value=True)
fee_drag_inr = total_fee_inr if include_fees else 0.0

# ---- Payoff at expiry -----------------------------------------------------
payoff_expiry = []
for s_px in spots:
    value_usd = 0.0
    for L in legs:
        row, n_lots = L["row"], L["lots"]
        sign = 1.0 if L["side"] == "Buy" else -1.0
        K = float(row["strike"])
        intrinsic = max(0.0, s_px - K) if row["is_call"] else max(0.0, K - s_px)
        value_usd += sign * intrinsic * n_lots * cv
    # P&L = what the position is worth minus what you paid for it
    payoff_expiry.append((value_usd - net_cash_usd) * usdinr - fee_drag_inr)

# ---- Payoff at a chosen future date (T+n) ---------------------------------
min_days = min(float(L["row"]["t_years"]) for L in legs) * 365.0
days_ahead = st.slider("T+0 curve: how many days ahead", 0.0,
                       max(0.1, round(min_days, 2)), 0.0, step=0.25,
                       help="0 is now. Raising it moves the curve towards the "
                            "expiry line.")

payoff_now = []
for s_px in spots:
    value_usd = 0.0
    for L in legs:
        row, n_lots = L["row"], L["lots"]
        sign = 1.0 if L["side"] == "Buy" else -1.0
        sigma = float(row["iv"])
        t_left = max(0.0, float(row["t_years"]) - days_ahead / 365.0)
        if math.isnan(sigma) or sigma <= 0:
            price = max(0.0, s_px - float(row["strike"])) if row["is_call"] \
                else max(0.0, float(row["strike"]) - s_px)
        else:
            price = om.bs_price(s_px, float(row["strike"]), t_left, sigma,
                                bool(row["is_call"]), r)
        value_usd += sign * price * n_lots * cv
    payoff_now.append((value_usd - net_cash_usd) * usdinr - fee_drag_inr)

# ---- Break-evens ----------------------------------------------------------
breakevens = om.find_breakevens(spots.tolist(), payoff_expiry)

label_now = "Now (T+0)" if days_ahead == 0 else f"T+{days_ahead:g} days"
st.plotly_chart(
    ch.payoff_diagram(spots.tolist(), payoff_expiry, spot,
                      payoff_now=payoff_now, breakevens=breakevens,
                      label_now=label_now),
    width="stretch",
)

# ---- Summary stats --------------------------------------------------------
max_profit = max(payoff_expiry)
max_loss = min(payoff_expiry)
at_spot = float(np.interp(spot, spots, payoff_expiry))

# Unbounded detection: if the payoff is still climbing / falling as it runs off
# the plotted range, the true max or min is not on screen. Judged per EDGE and
# per DIRECTION - see options_math.payoff_tail_risk for why "spot falls" and
# "the position loses" are two different questions.
tail = om.payoff_tail_risk(payoff_expiry)
unlimited_profit = tail["unlimited_profit"]
unlimited_loss = tail["unlimited_loss"]

p1, p2, p3, p4 = st.columns(4)
p1.metric("Max profit (in range)",
          "Unlimited ↑" if unlimited_profit else f"₹{max_profit:,.0f}")
p2.metric("Max loss (in range)",
          "Unlimited ↓" if unlimited_loss else f"₹{max_loss:,.0f}")
p3.metric("P&L if spot does not move", f"₹{at_spot:,.0f}")
p4.metric("Break-evens",
          " / ".join(f"{b:,.0f}" for b in breakevens) if breakevens else "None")

if breakevens and len(breakevens) >= 2:
    width_abs = max(breakevens) - min(breakevens)
    st.caption(f"Profit zone: **{min(breakevens):,.0f} → {max(breakevens):,.0f}** "
               f"(±{width_abs / 2 / spot * 100:.1f}% from spot), "
               f"width {width_abs:,.0f} points")
elif breakevens:
    st.caption(f"Single break-even at **{breakevens[0]:,.0f}** "
               f"({(breakevens[0] - spot) / spot * 100:+.1f}% from spot)")

if unlimited_loss:
    st.error("⚠️ **Undefined risk.** This position's maximum loss is "
             "theoretically unlimited, and liquidation on Delta is automatic. "
             "Check your position size and margin before entering.")

if net_theta_inr > 0 and abs(net_gamma) > 0:
    st.warning(
        f"**Short gamma trade-off:** you are earning ₹{net_theta_inr:,.2f}/day "
        f"in theta against a net gamma of {net_gamma:+.8f}. One large gap can "
        "erase several days of theta in a single session. That, not decay, is "
        "this trade's real risk."
    )

with st.expander("📋 Payoff table (every 5%)"):
    marks = [spot * (1 + p / 100.0) for p in range(-rng, rng + 1, 5)]
    tbl = pd.DataFrame({
        "Spot": marks,
        "Move %": [(m - spot) / spot * 100 for m in marks],
        "P&L at expiry ₹": [float(np.interp(m, spots, payoff_expiry)) for m in marks],
        f"P&L {label_now} ₹": [float(np.interp(m, spots, payoff_now)) for m in marks],
    })
    st.dataframe(
        tbl.style.format({
            "Spot": "{:,.0f}", "Move %": "{:+.0f}%",
            "P&L at expiry ₹": "₹{:,.0f}", f"P&L {label_now} ₹": "₹{:,.0f}",
        }).background_gradient(subset=["P&L at expiry ₹"], cmap="RdYlGn"),
        hide_index=True, width="stretch", height=380,
    )

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
