"""
MMC Delta Scanner — Theta Decay Calculator
==========================================
Three views on premium decay:
  1. Chain Decay Scanner — rank every liquid strike by how much it burns
  2. Single Strike Lab    — hour-by-hour burn curve until expiry
  3. Position Basket      — net theta and decay P&L for a multi-leg position

METHOD NOTE
-----------
Analytic theta is an INSTANTANEOUS derivative. Over a whole day, and
especially on expiry day, it misstates the real burn because theta itself
accelerates as time-to-expiry shrinks.

So every "burn" number on this page is computed by REPRICING the option at
the future timestamp (spot and IV held constant) and taking the difference.
Analytic theta is still shown alongside, as a sanity check.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import delta_api as api
from mmc_core import fees as fx
from mmc_core import options_math as om
from mmc_core import theme
from mmc_core import ui_common as ui

ui.page_setup(
    "Theta Decay Calculator",
    "Repricing-based premium burn · ₹ per lot · hour by hour till expiry",
    icon="⏳",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)
liq = ui.render_liquidity_controls(prefix="decay")

df, context = ui.load_enriched_chain(products, settings)
if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

spot = context["spot"]
cv = context["contract_value"]
usdinr = settings["usdinr"]
r = settings["risk_free"]
cfg = settings["fee_cfg"]
now = context["now"]

filtered = ui.apply_liquidity_filter(df, **liq)

if filtered.empty:
    st.markdown(theme.empty_state(
        "🫙", "Liquidity filter ke baad koi strike nahi bacha",
        "Sidebar mein spread limit badhaiye ya strike range widen kijiye. "
        "Decay sirf un strikes par matlab rakhta hai jinse aap nikal bhi sakein."
    ), unsafe_allow_html=True)
    ui.render_diagnostics(context, df, settings)
    st.stop()


def usd_to_inr_lot(usd_per_unit: float) -> float:
    """USD per unit of underlying -> ₹ per lot."""
    if usd_per_unit is None or (isinstance(usd_per_unit, float) and math.isnan(usd_per_unit)):
        return float("nan")
    return usd_per_unit * cv * usdinr


tab_scan, tab_lab, tab_basket = st.tabs(
    ["🔥 Chain Decay Scanner", "🔬 Single Strike Lab", "🧺 Position Basket"]
)

# ==========================================================================
# TAB 1 — Chain Decay Scanner
# ==========================================================================

with tab_scan:
    st.markdown(theme.section("Kaunse strikes sabse tez jal rahe hain", "burn = repricing se, analytic theta se nahi"), unsafe_allow_html=True)

    horizon_hours = st.slider(
        "Decay horizon (hours ahead)", min_value=1, max_value=72, value=24,
        help="Itne ghante mein kitna premium jalega — spot aur IV constant maan kar.",
    )

    rows = []
    for _, row in filtered.iterrows():
        sigma = float(row["iv"]) if not math.isnan(row["iv"]) else float("nan")
        if math.isnan(sigma) or sigma <= 0:
            continue

        t_now = float(row["t_years"])
        if t_now <= 0:
            continue

        t_future = max(0.0, t_now - (horizon_hours * 3600.0) / om.SECONDS_PER_YEAR)
        burn_usd = om.decay_between(spot, float(row["strike"]), sigma,
                                    bool(row["is_call"]), t_now, t_future, r)

        premium_inr = usd_to_inr_lot(float(row["mark_price"]))
        burn_inr = usd_to_inr_lot(burn_usd)
        theta_inr = float(row["theta_lot_inr"])

        yield_pct = (burn_usd / row["mark_price"] * 100.0) \
            if row["mark_price"] and row["mark_price"] > 0 else float("nan")

        cost_inr = float(row["fee_rt_inr_lot"]) + \
            (float(row["slippage_pct"]) / 100.0 * premium_inr
             if not math.isnan(row["slippage_pct"]) else 0.0)

        rows.append({
            "Type": "CALL" if row["is_call"] else "PUT",
            "Strike": float(row["strike"]),
            "Moneyness %": float(row["moneyness_pct"]),
            "IV %": float(row["iv_pct"]),
            "Premium ₹/lot": premium_inr,
            f"Burn ₹/lot ({horizon_hours}h)": burn_inr,
            "Burn % of premium": yield_pct,
            "Round-trip cost ₹": cost_inr,
            "Net after cost ₹": burn_inr - cost_inr,
            "Analytic θ ₹/lot/day": theta_inr,
            "Spread %": float(row["spread_pct"]),
            "OI": float(row["oi_contracts"]) if not math.isnan(row["oi_contracts"]) else 0.0,
        })

    if not rows:
        st.warning("Decay compute karne ke liye valid IV wala koi strike nahi mila.")
    else:
        scan = pd.DataFrame(rows)
        burn_col = f"Burn ₹/lot ({horizon_hours}h)"

        sort_choice = st.radio(
            "Ranking",
            ["Burn % of premium (yield)", "Absolute ₹ burn",
             "Premium ₹/lot", "Net after cost"],
            horizontal=True,
        )
        sort_map = {
            "Burn % of premium (yield)": "Burn % of premium",
            "Absolute ₹ burn": burn_col,
            "Premium ₹/lot": "Premium ₹/lot",
            "Net after cost": "Net after cost ₹",
        }
        scan = scan.sort_values(sort_map[sort_choice], ascending=False)

        st.dataframe(
            scan.style.format({
                "Strike": "{:,.0f}", "Moneyness %": "{:+.1f}", "IV %": "{:.1f}",
                "Premium ₹/lot": "₹{:,.2f}", burn_col: "₹{:,.2f}",
                "Burn % of premium": "{:.2f}%",
                "Round-trip cost ₹": "₹{:,.2f}",
                "Net after cost ₹": "₹{:+,.2f}",
                "Analytic θ ₹/lot/day": "₹{:,.2f}",
                "Spread %": "{:.1f}", "OI": "{:,.0f}",
            }, na_rep="—").background_gradient(
                subset=["Burn % of premium"], cmap="YlOrRd"),
            hide_index=True, width='stretch',
            height=theme.table_height(len(scan), max_px=520),
        )

        losers = scan[scan["Net after cost ₹"] <= 0]
        if not losers.empty:
            st.error(
                f"⚠️ **{len(losers)} strikes par {horizon_hours}h ka decay "
                "round-trip cost se kam hai.** In par premium bechne se pehle "
                "din se hi ghaata hai — chahe theta kitna bhi 'juicy' dikhe."
            )

        st.info(
            "**Padhne ka tarika:** *Burn % of premium* sabse upar wale strikes theta "
            "sellers ko sabse 'juicy' lagte hain — lekin yahi wo strikes hain "
            "jinka gamma risk sabse zyada hai, aur aksar spread bhi. "
            "**Net after cost** column hi asli decision number hai."
        )

        st.download_button(
            "⬇️ Download decay scan CSV",
            data=scan.to_csv(index=False).encode("utf-8"),
            file_name=(f"MMC_decay_{settings['underlying']}_"
                       f"{settings['expiry']['api_date']}_{horizon_hours}h.csv"),
            mime="text/csv",
        )

# ==========================================================================
# TAB 2 — Single Strike Lab
# ==========================================================================

with tab_lab:
    st.markdown(theme.section("Ek strike ka poora decay curve"), unsafe_allow_html=True)

    c1, c2, c3 = st.columns([2, 1, 1])

    strikes = sorted(filtered["strike"].unique().tolist())
    default_idx = min(range(len(strikes)),
                      key=lambda i: abs(strikes[i] - spot)) if strikes else 0

    with c1:
        chosen_strike = st.selectbox(
            "Strike", strikes, index=default_idx,
            format_func=lambda x: f"{x:,.0f}  ({(x - spot) / spot * 100:+.1f}% from spot)",
        )
    with c2:
        chosen_side = st.radio("Type", ["CALL", "PUT"], horizontal=True)
    with c3:
        lots = st.number_input("Lots", min_value=1, max_value=100000, value=1, step=1)

    is_call = chosen_side == "CALL"
    match = filtered[(filtered["strike"] == chosen_strike)
                     & (filtered["is_call"] == is_call)]

    if match.empty:
        st.warning(f"{chosen_strike:,.0f} {chosen_side} filter ke baad available "
                   "nahi hai. Dusra strike chunein ya filter dheela karein.")
    else:
        leg = match.iloc[0]
        sigma = float(leg["iv"])
        t_now = float(leg["t_years"])

        if math.isnan(sigma) or sigma <= 0 or t_now <= 0:
            st.error("Is strike ki IV ya time-to-expiry invalid hai — "
                     "decay curve nahi ban sakta.")
        else:
            premium_inr = usd_to_inr_lot(float(leg["mark_price"])) * lots
            theta_inr = float(leg["theta_lot_inr"]) * lots

            burn_24h_usd = om.decay_between(
                spot, chosen_strike, sigma, is_call, t_now,
                max(0.0, t_now - 86400.0 / om.SECONDS_PER_YEAR), r)
            burn_24h_inr = usd_to_inr_lot(burn_24h_usd) * lots

            burn_1h_usd = om.decay_between(
                spot, chosen_strike, sigma, is_call, t_now,
                max(0.0, t_now - 3600.0 / om.SECONDS_PER_YEAR), r)
            burn_1h_inr = usd_to_inr_lot(burn_1h_usd) * lots

            k1, k2, k3, k4 = st.columns(4)
            k1.metric(f"Premium ({lots} lot)", f"₹{premium_inr:,.2f}")
            k2.metric("Next 1 hour burn", f"₹{burn_1h_inr:,.2f}")
            k3.metric("Next 24 hour burn", f"₹{burn_24h_inr:,.2f}",
                      help="Repricing se — analytic theta se thoda alag hoga, "
                           "aur wahi sahi hai.")
            k4.metric("Analytic θ / day", f"₹{theta_inr:,.2f}")

            g1, g2, g3, g4 = st.columns(4)
            g1.metric("IV", f"{leg['iv_pct']:.1f}%")
            g2.metric("Delta", f"{leg['delta']:.3f}")
            g3.metric("Time left", api.humanize_countdown(float(leg["seconds_left"])))
            g4.metric("Spread", f"{leg['spread_pct']:.1f}%"
                      if not math.isnan(leg["spread_pct"]) else "—")

            if not math.isnan(burn_24h_usd) and not math.isnan(float(leg["theta"])):
                analytic_24h = abs(float(leg["theta"]))
                if analytic_24h > 0:
                    diff_pct = (abs(burn_24h_usd) - analytic_24h) / analytic_24h * 100.0
                    if abs(diff_pct) > 10:
                        st.warning(
                            f"Analytic theta aur actual 24h repricing mein "
                            f"**{diff_pct:+.0f}%** ka farak hai. Ye normal hai jab "
                            "expiry paas ho — theta accelerate karta hai. "
                            "Repricing wala number hi trust karein."
                        )

            # ---- Decay curve ------------------------------------------
            schedule = om.decay_schedule(spot, chosen_strike, sigma, is_call,
                                         t_now, step_seconds=3600.0,
                                         max_steps=300, r=r)

            if schedule:
                curve = pd.DataFrame(schedule)
                curve["Premium ₹"] = curve["price"].apply(usd_to_inr_lot) * lots
                curve["Cumulative burn ₹"] = curve["cum_decay"].apply(usd_to_inr_lot) * lots
                curve["Step burn ₹"] = curve["step_decay"].apply(usd_to_inr_lot) * lots
                curve["Hours ahead"] = curve["hours_ahead"].round(2)

                st.markdown(theme.section("Premium melting away", "premium bacha aur burn — dono ₹ per lot"), unsafe_allow_html=True)
                st.plotly_chart(
                    ch.decay_curve(curve["Hours ahead"].tolist(),
                                   curve["Premium ₹"].tolist(),
                                   curve["Cumulative burn ₹"].tolist()),
                    width="stretch",
                )

                st.markdown(theme.section("Burn per step", "dahini taraf uthta tail = theta acceleration"), unsafe_allow_html=True)
                st.plotly_chart(
                    ch.burn_bars(curve["Hours ahead"].tolist(),
                                 curve["Step burn ₹"].tolist()),
                    width="stretch",
                )

                with st.expander("📋 Hour-by-hour ladder"):
                    ladder = curve[["Hours ahead", "Premium ₹",
                                    "Step burn ₹", "Cumulative burn ₹"]]
                    st.dataframe(
                        ladder.style.format({
                            "Hours ahead": "{:.2f}", "Premium ₹": "₹{:,.2f}",
                            "Step burn ₹": "₹{:,.2f}",
                            "Cumulative burn ₹": "₹{:,.2f}",
                        }),
                        hide_index=True, width='stretch', height=340,
                    )

            st.caption(
                "⚠️ Ye curve **spot aur IV ko constant** maan kar bana hai. "
                "Real life mein spot hilega (delta/gamma P&L) aur IV badlegi "
                "(vega P&L) — decay sirf teen mein se ek component hai."
            )

# ==========================================================================
# TAB 3 — Position Basket
# ==========================================================================

with tab_basket:
    st.markdown(theme.section("Multi-leg position ka net theta"), unsafe_allow_html=True)
    st.caption("Neeche table mein legs add kijiye. Sell = premium receive, "
               "Buy = premium pay. Rows add/delete karne ke liye table use karein.")

    options_list = []
    label_to_row = {}
    for _, row in filtered.iterrows():
        label = (f"{'C' if row['is_call'] else 'P'} {row['strike']:,.0f}  "
                 f"(IV {row['iv_pct']:.0f}%, Δ {row['delta']:+.2f})")
        options_list.append(label)
        label_to_row[label] = row

    if not options_list:
        st.warning("Koi tradable leg available nahi hai.")
    else:
        default_leg = min(options_list,
                          key=lambda l: abs(label_to_row[l]["strike"] - spot))

        seed = pd.DataFrame([
            {"Leg": default_leg, "Side": "Sell", "Lots": 1},
        ])

        edited = st.data_editor(
            seed,
            num_rows="dynamic",
            width='stretch',
            key="basket_editor",
            column_config={
                "Leg": st.column_config.SelectboxColumn(
                    "Leg", options=options_list, required=True, width="large"),
                "Side": st.column_config.SelectboxColumn(
                    "Side", options=["Buy", "Sell"], required=True),
                "Lots": st.column_config.NumberColumn(
                    "Lots", min_value=1, max_value=100000, step=1, required=True),
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
            sign = 1.0 if e.get("Side") == "Buy" else -1.0
            legs.append({"row": label_to_row[label], "sign": sign,
                         "lots": n_lots, "label": label,
                         "side": e.get("Side")})

        if not legs:
            st.info("Kam se kam ek valid leg add kijiye.")
        else:
            net_premium_inr = 0.0
            net_theta_inr = 0.0
            net_delta = 0.0
            net_vega_inr = 0.0
            leg_table = []

            for L in legs:
                row, sign, n_lots = L["row"], L["sign"], L["lots"]
                prem = usd_to_inr_lot(float(row["mark_price"])) * n_lots
                thet = usd_to_inr_lot(float(row["theta"])) * n_lots
                vega = usd_to_inr_lot(float(row["vega"])) * n_lots
                dlt = float(row["delta"]) * n_lots * cv

                net_premium_inr += sign * prem
                net_theta_inr += sign * thet
                net_vega_inr += sign * vega
                net_delta += sign * dlt

                leg_table.append({
                    "Leg": L["label"], "Side": L["side"], "Lots": n_lots,
                    "Premium ₹": sign * prem,
                    "θ ₹/day": sign * thet,
                    "Δ (underlying units)": sign * dlt,
                    "Vega ₹/vol pt": sign * vega,
                })

            b1, b2, b3, b4 = st.columns(4)
            b1.metric("Net premium",
                      f"₹{abs(net_premium_inr):,.2f}",
                      delta="PAID" if net_premium_inr > 0 else "RECEIVED",
                      delta_color="inverse" if net_premium_inr > 0 else "normal")
            b2.metric("Net θ per day", f"₹{net_theta_inr:,.2f}",
                      help="Positive = decay aapke favour mein hai (net short premium).")
            b3.metric("Net Delta", f"{net_delta:+.4f} {settings['underlying']}")
            b4.metric("Net Vega", f"₹{net_vega_inr:,.2f} / vol pt")

            st.dataframe(
                pd.DataFrame(leg_table).style.format({
                    "Premium ₹": "₹{:,.2f}", "θ ₹/day": "₹{:,.2f}",
                    "Δ (underlying units)": "{:+.5f}",
                    "Vega ₹/vol pt": "₹{:,.2f}",
                }),
                width='stretch', hide_index=True)

            # ---- Basket decay P&L curve --------------------------------
            min_t = min(float(L["row"]["t_years"]) for L in legs)
            if min_t > 0:
                steps = om.decay_schedule(
                    spot, float(legs[0]["row"]["strike"]),
                    float(legs[0]["row"]["iv"]), bool(legs[0]["row"]["is_call"]),
                    min_t, step_seconds=3600.0, max_steps=250, r=r)

                if steps:
                    hours = [s["hours_ahead"] for s in steps]
                    pnl = []
                    for h in hours:
                        total_now = 0.0
                        total_future = 0.0
                        for L in legs:
                            row, sign, n_lots = L["row"], L["sign"], L["lots"]
                            sigma = float(row["iv"])
                            t0 = float(row["t_years"])
                            if math.isnan(sigma) or sigma <= 0 or t0 <= 0:
                                continue
                            t1 = max(0.0, t0 - (h * 3600.0) / om.SECONDS_PER_YEAR)
                            p0 = om.bs_price(spot, float(row["strike"]), t0,
                                             sigma, bool(row["is_call"]), r)
                            p1 = om.bs_price(spot, float(row["strike"]), t1,
                                             sigma, bool(row["is_call"]), r)
                            total_now += sign * n_lots * usd_to_inr_lot(p0)
                            total_future += sign * n_lots * usd_to_inr_lot(p1)
                        pnl.append(total_future - total_now)

                    pnl_df = pd.DataFrame({
                        "Hours ahead": [round(h, 2) for h in hours],
                        "Decay-only P&L ₹": pnl,
                    }).set_index("Hours ahead")

                    st.markdown(theme.section("Decay-only P&L", "spot aur IV frozen"), unsafe_allow_html=True)
                    st.plotly_chart(
                        ch.decay_curve(pnl_df.index.tolist(),
                                       pnl_df["Decay-only P&L ₹"].tolist(),
                                       pnl_df["Decay-only P&L ₹"].tolist()),
                        width="stretch",
                    )

                    final_pnl = pnl[-1] if pnl else 0.0
                    st.metric("Agar expiry tak spot & IV bilkul na hile",
                              f"₹{final_pnl:,.2f}")

            st.warning(
                "**Ye P&L sirf theta ka hissa hai.** Spot movement (delta/gamma) "
                "aur IV change (vega) is chart mein nahi hain. Short-premium "
                "position par gamma loss aksar theta gain se bada ho jaata hai — "
                "isi liye Net Delta aur Net Vega bhi upar dikhaye gaye hain."
            )

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
