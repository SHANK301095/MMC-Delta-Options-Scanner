"""
MMC Delta Scanner — Mispricing & Arbitrage Bounds
=================================================
Four model-free no-arbitrage relationships that must hold on any European
options chain. When one breaks, either there is real edge or — far more often —
the quote is stale.

  1. PUT-CALL PARITY      C − P = S − K·e^(−rT)
  2. VERTICAL BOUNDS      0 ≤ C(K1) − C(K2) ≤ K2 − K1   for K1 < K2
  3. BUTTERFLY CONVEXITY  C(K1) − 2C(K2) + C(K3) ≥ 0    for evenly spaced K
  4. BOX SPREAD           (C(K1) − C(K2)) + (P(K2) − P(K1)) = K2 − K1

These need no volatility model at all — they follow from the payoff structure
alone. That is exactly why they are worth checking: no assumption can be wrong.

THE ONLY HONEST WAY TO RUN THESE
--------------------------------
Every check below uses EXECUTABLE prices (buy at ask, sell at bid) and then
subtracts fees. Run these on mark prices instead and the screen fills with
"free money" that vanishes the instant a real order touches the book.

A violation flagged here is a STARTING POINT for investigation, never a signal.
On Delta India the overwhelmingly likely explanation is a stale quote on an
illiquid strike, which is why the stale/OI/spread columns sit right next to
every finding.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import streamlit as st

from mmc_core import delta_api as api
from mmc_core import fees as fx
from mmc_core import ui_common as ui

ui.page_setup(
    "Mispricing Scanner",
    "Model-free arbitrage bounds · executable prices · net of fees & spread",
    icon="🔎",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)
liq = ui.render_liquidity_controls(prefix="arb")

df, context = ui.load_enriched_chain(products, settings)
if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

spot = context["spot"]
cv = context["contract_value"]
usdinr = settings["usdinr"]
r = settings["risk_free"]
cfg = settings["fee_cfg"]

# Arbitrage checks are meaningless without a two-sided book, so this page
# forces that requirement regardless of the sidebar setting.
filtered = ui.apply_liquidity_filter(df, **{**liq, "require_two_sided": True})

st.caption("ℹ️ Is page par two-sided book **hamesha** required hai — "
           "bina bid aur ask ke koi arbitrage check possible hi nahi.")

if filtered.empty:
    st.warning("Two-sided book wala koi strike nahi mila. "
               "Spread limit badhaiye ya dusri expiry chunein.")
    ui.render_diagnostics(context, df, settings)
    ui.maybe_auto_refresh(settings)
    st.stop()

min_edge_inr = st.number_input(
    "Minimum edge to report (₹ per lot, net of fees)",
    min_value=0.0, value=1.0, step=0.5,
    help="Isse chhoti 'edge' noise hai. Zero karke sab dekh sakte hain.",
)
hide_stale = st.checkbox("Stale quotes (>2 min purani) hide karein", value=True)

work = filtered.copy()
if hide_stale:
    work = work[~work["is_stale"].fillna(False)]

if work.empty:
    st.warning("Stale filter ke baad kuch nahi bacha.")
    ui.render_diagnostics(context, df, settings)
    ui.maybe_auto_refresh(settings)
    st.stop()

calls = work[work["is_call"]].set_index("strike").sort_index()
puts = work[~work["is_call"]].set_index("strike").sort_index()

t_years = float(work["t_years"].median())
discount = math.exp(-r * t_years)


def fee_for(price: float, lots: float = 1.0, maker: bool = False) -> float:
    return fx.leg_fee_usd(price, spot, lots, cv, cfg, is_maker=maker)


def to_inr_lot(usd_per_unit: float) -> float:
    return usd_per_unit * cv * usdinr


def oi_of(row) -> float:
    """Open interest, missing ko 0 maan kar.

    `float(row["oi_contracts"] or 0)` yahan kaam NAHI karta: NaN Python mein
    truthy hai, isliye missing OI NaN hi rehti hai aur min()/format dono ko
    chup-chaap kharab kar deti hai.
    """
    val = float(row["oi_contracts"])
    return 0.0 if math.isnan(val) else val


tab1, tab2, tab3, tab4 = st.tabs([
    "⚖️ Put-Call Parity", "📏 Vertical Bounds",
    "🦋 Butterfly Convexity", "📦 Box Spread",
])

# ==========================================================================
# 1 — PUT-CALL PARITY
# ==========================================================================

with tab1:
    st.markdown("### C − P = S − K·e^(−rT)")
    st.caption("Synthetic long stock (buy call + sell put) ka cost spot minus "
               "discounted strike ke barabar hona chahiye. Farak = parity gap.")

    shared = sorted(set(calls.index) & set(puts.index))
    rows = []

    for K in shared:
        c, p = calls.loc[K], puts.loc[K]
        theoretical = spot - K * discount

        # Synthetic LONG: pay call ask, receive put bid
        syn_long_cost = float(c["best_ask"]) - float(p["best_bid"])
        # Synthetic SHORT: receive call bid, pay put ask
        syn_short_proceeds = float(c["best_bid"]) - float(p["best_ask"])

        fees_pair = (fee_for(float(c["best_ask"]), maker=cfg.entry_is_maker)
                     + fee_for(float(p["best_bid"]), maker=cfg.entry_is_maker))
        fees_inr = fees_pair * usdinr

        # Synthetic cheap vs spot -> buy synthetic
        gap_long = theoretical - syn_long_cost
        # Synthetic rich vs spot -> sell synthetic
        gap_short = syn_short_proceeds - theoretical

        best_gap, direction = ((gap_long, "Synthetic sasta (buy synth)")
                               if gap_long >= gap_short
                               else (gap_short, "Synthetic mehnga (sell synth)"))
        net_inr = to_inr_lot(best_gap) - fees_inr

        rows.append({
            "Strike": float(K),
            "Call Ask": float(c["best_ask"]), "Put Bid": float(p["best_bid"]),
            "Theoretical C−P": theoretical,
            "Gross gap $": best_gap,
            "Direction": direction,
            "Fees ₹": fees_inr,
            "Net edge ₹/lot": net_inr,
            "Min OI": min(oi_of(c), oi_of(p)),
            "Max Spread %": max(float(c["spread_pct"]), float(p["spread_pct"])),
        })

    if not rows:
        st.info("Koi strike aisa nahi mila jahan call aur put dono two-sided hon.")
    else:
        parity = pd.DataFrame(rows).sort_values("Net edge ₹/lot", ascending=False)
        hits = parity[parity["Net edge ₹/lot"] >= min_edge_inr]

        h1, h2, h3 = st.columns(3)
        h1.metric("Strikes checked", len(parity))
        h2.metric("Above threshold", len(hits))
        h3.metric("Best net edge", f"₹{parity['Net edge ₹/lot'].max():,.2f}")

        if hits.empty:
            st.success("✅ Parity clean hai — fees ke baad koi exploitable gap nahi. "
                       "Ek liquid chain par yahi expected result hai.")
        else:
            st.warning(f"⚠️ {len(hits)} strikes par parity gap dikha. "
                       "Pehle OI aur spread columns dekhein — asli edge se "
                       "kahin zyada baar ye stale quote hoti hai.")

        st.dataframe(
            (hits if not hits.empty else parity.head(15)).style.format({
                "Strike": "{:,.0f}", "Call Ask": "${:,.2f}", "Put Bid": "${:,.2f}",
                "Theoretical C−P": "${:,.2f}", "Gross gap $": "${:+,.2f}",
                "Fees ₹": "₹{:,.2f}", "Net edge ₹/lot": "₹{:+,.2f}",
                "Min OI": "{:,.0f}", "Max Spread %": "{:.1f}",
            }).background_gradient(subset=["Net edge ₹/lot"], cmap="RdYlGn"),
            width="stretch", height=400,
        )

        st.info("**Practical note:** Synthetic ko hedge karne ke liye aapko "
                "perpetual future ki leg chahiye hogi. Uska funding rate aur "
                "spread is calculation mein **nahi** hai — real edge isse kam "
                "hoga. Ye bound sirf ye batata hai ki options chain apne aap "
                "mein consistent hai ya nahi.")

# ==========================================================================
# 2 — VERTICAL BOUNDS
# ==========================================================================

with tab2:
    st.markdown("### 0 ≤ C(K₁) − C(K₂) ≤ K₂ − K₁   (K₁ < K₂)")
    st.caption("Neeche wali call kabhi upar wali se sasti nahi ho sakti, "
               "aur unka farak strike difference se zyada nahi ho sakta. "
               "Puts par ulta niyam.")

    findings = []

    for side_name, frame, is_call in (("CALL", calls, True), ("PUT", puts, False)):
        ks = list(frame.index)
        for i in range(len(ks) - 1):
            for j in range(i + 1, min(i + 6, len(ks))):   # nearby pairs only
                k1, k2 = ks[i], ks[j]
                a, b = frame.loc[k1], frame.loc[k2]
                width = abs(k2 - k1)

                if is_call:
                    # Debit spread: buy low strike (ask), sell high strike (bid)
                    buy_px = float(a["best_ask"])
                    sell_px = float(b["best_bid"])
                else:
                    # For puts the higher strike is the more valuable one, so
                    # the debit spread buys K2 and sells K1 — the mirror legs.
                    buy_px = float(b["best_ask"])
                    sell_px = float(a["best_bid"])
                cost = buy_px - sell_px

                # Fees must be charged on the legs actually executed. Charging
                # the call-side legs on a put spread silently misprices every
                # put finding, because the premium cap keys off the premium.
                fees_pair = (fee_for(buy_px, maker=cfg.entry_is_maker)
                             + fee_for(sell_px, maker=cfg.entry_is_maker))
                fees_inr = fees_pair * usdinr

                violation, edge_usd = None, 0.0
                if cost < 0:
                    violation = "Negative cost (credit for a debit spread)"
                    edge_usd = -cost
                elif cost > width:
                    violation = "Cost exceeds max payoff"
                    edge_usd = cost - width

                if violation:
                    net = to_inr_lot(edge_usd) - fees_inr
                    if net >= min_edge_inr:
                        findings.append({
                            "Type": side_name,
                            "K₁": float(k1), "K₂": float(k2),
                            "Width": width, "Spread cost $": cost,
                            "Violation": violation,
                            "Gross edge $": edge_usd,
                            "Fees ₹": fees_inr,
                            "Net edge ₹/lot": net,
                            "Min OI": min(oi_of(a), oi_of(b)),
                        })

    if not findings:
        st.success("✅ Koi vertical bound violation nahi mila. "
                   "Chain internally consistent hai.")
    else:
        vf = pd.DataFrame(findings).sort_values("Net edge ₹/lot", ascending=False)
        st.warning(f"⚠️ {len(vf)} vertical violations mile (fees ke baad).")
        st.dataframe(
            vf.style.format({
                "K₁": "{:,.0f}", "K₂": "{:,.0f}", "Width": "{:,.0f}",
                "Spread cost $": "${:,.2f}", "Gross edge $": "${:,.2f}",
                "Fees ₹": "₹{:,.2f}", "Net edge ₹/lot": "₹{:+,.2f}",
                "Min OI": "{:,.0f}",
            }).background_gradient(subset=["Net edge ₹/lot"], cmap="RdYlGn"),
            width="stretch", height=380,
        )
        st.error("Aise violations 99% baar stale quote hote hain. Delta ke UI "
                 "par khud jaakar dono strikes ka live book verify kijiye "
                 "**pehle** ki koi order bhejein.")

# ==========================================================================
# 3 — BUTTERFLY CONVEXITY
# ==========================================================================

with tab3:
    st.markdown("### C(K₁) − 2·C(K₂) + C(K₃) ≥ 0   (evenly spaced strikes)")
    st.caption("Option price strike ke saath convex hona chahiye. "
               "Negative butterfly = free money OR (aksar) middle strike ki "
               "quote stale hai.")

    findings = []

    for side_name, frame, is_call in (("CALL", calls, True), ("PUT", puts, False)):
        ks = list(frame.index)
        for i in range(len(ks) - 2):
            k1, k2, k3 = ks[i], ks[i + 1], ks[i + 2]
            if abs((k2 - k1) - (k3 - k2)) > 1e-6:
                continue  # not evenly spaced, bound does not apply

            a, b, c_ = frame.loc[k1], frame.loc[k2], frame.loc[k3]

            # Long butterfly: buy wings (ask), sell 2x body (bid)
            cost = (float(a["best_ask"]) - 2 * float(b["best_bid"])
                    + float(c_["best_ask"]))
            fees_all = (fee_for(float(a["best_ask"]), maker=cfg.entry_is_maker)
                        + fee_for(float(b["best_bid"]), 2.0, maker=cfg.entry_is_maker)
                        + fee_for(float(c_["best_ask"]), maker=cfg.entry_is_maker))
            fees_inr = fees_all * usdinr

            if cost < 0:
                net = to_inr_lot(-cost) - fees_inr
                if net >= min_edge_inr:
                    findings.append({
                        "Type": side_name,
                        "K₁": float(k1), "K₂": float(k2), "K₃": float(k3),
                        "Butterfly cost $": cost,
                        "Gross edge $": -cost,
                        "Fees ₹": fees_inr,
                        "Net edge ₹/lot": net,
                        "Body OI": oi_of(b),
                        "Body spread %": float(b["spread_pct"]),
                    })

    if not findings:
        st.success("✅ Convexity intact — koi negative-cost butterfly nahi mila.")
    else:
        bf = pd.DataFrame(findings).sort_values("Net edge ₹/lot", ascending=False)
        st.warning(f"⚠️ {len(bf)} convexity violations mile.")
        st.dataframe(
            bf.style.format({
                "K₁": "{:,.0f}", "K₂": "{:,.0f}", "K₃": "{:,.0f}",
                "Butterfly cost $": "${:,.2f}", "Gross edge $": "${:,.2f}",
                "Fees ₹": "₹{:,.2f}", "Net edge ₹/lot": "₹{:+,.2f}",
                "Body OI": "{:,.0f}", "Body spread %": "{:.1f}",
            }).background_gradient(subset=["Net edge ₹/lot"], cmap="RdYlGn"),
            width="stretch", height=360,
        )
        st.caption("Butterfly ke teen legs matlab **6 fills** (entry + exit). "
                   "Har fill par spread aur fee lagegi. Paper edge yahan "
                   "execution mein sabse aasani se mar jaata hai.")

# ==========================================================================
# 4 — BOX SPREAD
# ==========================================================================

with tab4:
    st.markdown("### (C(K₁) − C(K₂)) + (P(K₂) − P(K₁)) = K₂ − K₁")
    st.caption("Box ek synthetic zero-coupon loan hai — payoff hamesha exactly "
               "K₂ − K₁ hota hai, spot chahe kahin bhi jaaye. "
               "Cost isse kam ho to risk-free lock hai.")

    shared = sorted(set(calls.index) & set(puts.index))
    findings = []

    for i in range(len(shared) - 1):
        for j in range(i + 1, min(i + 5, len(shared))):
            k1, k2 = shared[i], shared[j]
            width = k2 - k1
            if width <= 0:
                continue

            c1, c2 = calls.loc[k1], calls.loc[k2]
            p1, p2 = puts.loc[k1], puts.loc[k2]

            # Long box: buy C(K1), sell C(K2), buy P(K2), sell P(K1)
            cost = (float(c1["best_ask"]) - float(c2["best_bid"])
                    + float(p2["best_ask"]) - float(p1["best_bid"]))
            payoff = width * discount

            fees_all = sum([
                fee_for(float(c1["best_ask"]), maker=cfg.entry_is_maker),
                fee_for(float(c2["best_bid"]), maker=cfg.entry_is_maker),
                fee_for(float(p2["best_ask"]), maker=cfg.entry_is_maker),
                fee_for(float(p1["best_bid"]), maker=cfg.entry_is_maker),
            ])
            fees_inr = fees_all * usdinr

            gross = payoff - cost
            net = to_inr_lot(gross) - fees_inr

            if net >= min_edge_inr:
                findings.append({
                    "K₁": float(k1), "K₂": float(k2), "Width": width,
                    "Box cost $": cost, "Guaranteed payoff $": payoff,
                    "Gross edge $": gross,
                    "Fees ₹ (4 legs)": fees_inr,
                    "Net edge ₹/lot": net,
                    "Min OI": min(oi_of(x) for x in (c1, c2, p1, p2)),
                })

    if not findings:
        st.success("✅ Koi box arbitrage nahi mila — chain fees ke baad "
                   "arbitrage-free hai. Yahi normal aur healthy result hai.")
    else:
        bx = pd.DataFrame(findings).sort_values("Net edge ₹/lot", ascending=False)
        st.warning(f"⚠️ {len(bx)} boxes theoretical edge dikha rahe hain.")
        st.dataframe(
            bx.style.format({
                "K₁": "{:,.0f}", "K₂": "{:,.0f}", "Width": "{:,.0f}",
                "Box cost $": "${:,.2f}", "Guaranteed payoff $": "${:,.2f}",
                "Gross edge $": "${:+,.2f}", "Fees ₹ (4 legs)": "₹{:,.2f}",
                "Net edge ₹/lot": "₹{:+,.2f}", "Min OI": "{:,.0f}",
            }).background_gradient(subset=["Net edge ₹/lot"], cmap="RdYlGn"),
            width="stretch", height=360,
        )
        st.error(
            "**Box par teen cheezein yaad rakhein:**\n\n"
            "1. Chaaron legs ek saath bharni padengi — ek bhi leg reh gayi to "
            "hedge nahi, naked position ban jaayegi.\n"
            "2. Margin capital expiry tak block rahega. Annualised return "
            "nikaal kar dekhiye ki wo blocked capital worth hai ya nahi.\n"
            "3. Delta par settlement fee alag se lagti hai — wo yahan "
            "count nahi hui."
        )

st.markdown("---")
st.info(
    "🧠 **Is page ko padhne ka sahi tarika:** Yahan mostly **green (koi violation "
    "nahi)** dikhna chahiye. Wahi healthy chain ki nishani hai. Agar bahut saare "
    "violations aa rahe hain, to sabse pehla shak stale data par karein, "
    "free money par nahi."
)

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
