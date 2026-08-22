"""
MMC Delta Scanner — IV Skew & Term Structure
============================================
Two questions this page answers, both from CURRENT chain data only
(no history, no Data Spine dependency):

  1. SKEW   — across strikes in one expiry, which side is the market paying up for?
  2. TERM   — across expiries, is near-dated vol richer or cheaper than far-dated?

Why the curve is built from OTM options
---------------------------------------
An option's IV is the same for a call and a put at the same strike IF put-call
parity holds. In practice it does not, because ITM quotes on a crypto chain are
wide and stale — nobody trades a 0.95-delta call. So the market convention is
to build the curve from OTM contracts only: puts below spot, calls above.
That is the purple line here.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import delta_api as api
from mmc_core import options_math as om
from mmc_core import theme
from mmc_core import ui_common as ui

ui.page_setup(
    "IV Skew & Term Structure",
    "Volatility smile, skew metrics and the vol curve across expiries",
    icon="🌊",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)
liq = ui.render_liquidity_controls(prefix="skew")

df, context = ui.load_enriched_chain(products, settings)
if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

spot = context["spot"]

filtered = ui.apply_liquidity_filter(df, **liq)

if filtered.empty or filtered["iv"].notna().sum() < 3:
    st.markdown(theme.empty_state(
        "🌊", "Skew banane ke liye kam se kam 3 valid IV chahiye",
        "Filter ne itne contracts hata diye ki curve banti hi nahi. "
        "Spread limit badhaiye ya strike range widen kijiye."
    ), unsafe_allow_html=True)
    ui.render_diagnostics(context, df, settings)
    ui.maybe_auto_refresh(settings)
    st.stop()

tab_smile, tab_term = st.tabs(["🌊 Smile / Skew", "📅 Term Structure"])

# ==========================================================================
# TAB 1 — Smile
# ==========================================================================

with tab_smile:
    valid = filtered[filtered["iv"].notna() & (filtered["iv"] > 0)]

    calls = valid[valid["is_call"]].sort_values("strike")
    puts = valid[~valid["is_call"]].sort_values("strike")

    # OTM blend: puts strictly below spot, calls at or above spot.
    otm = pd.concat([
        puts[puts["strike"] < spot],
        calls[calls["strike"] >= spot],
    ]).sort_values("strike")

    fig = ch.volatility_smile(
        calls["strike"].tolist(), calls["iv_pct"].tolist(),
        puts["strike"].tolist(), puts["iv_pct"].tolist(),
        spot,
        blend_strikes=otm["strike"].tolist(),
        blend_iv=otm["iv_pct"].tolist(),
    )
    st.plotly_chart(fig, width="stretch")

    # ---- Skew metrics ---------------------------------------------------
    st.markdown(theme.section("Skew metrics", "25Δ par interpolate kiya gaya"), unsafe_allow_html=True)

    def iv_at_delta(frame: pd.DataFrame, target_delta: float) -> float:
        """Linear-interpolate IV at a target absolute delta.

        Walks the chain to find the two rows that bracket the target delta,
        then interpolates. Returns NaN if the chain never reaches that delta —
        which happens often on thin expiries, and a wrong number there would
        be worse than no number.
        """
        work = frame.dropna(subset=["delta", "iv_pct"]).copy()
        if work.empty:
            return float("nan")
        work["abs_delta"] = work["delta"].abs()
        work = work[(work["abs_delta"] > 0.01) & (work["abs_delta"] < 0.99)]
        work = work.sort_values("abs_delta")
        if work.empty:
            return float("nan")

        lo = work[work["abs_delta"] <= target_delta]
        hi = work[work["abs_delta"] >= target_delta]
        if lo.empty or hi.empty:
            return float("nan")

        a, b = lo.iloc[-1], hi.iloc[0]
        if abs(b["abs_delta"] - a["abs_delta"]) < 1e-9:
            return float(a["iv_pct"])
        w = (target_delta - a["abs_delta"]) / (b["abs_delta"] - a["abs_delta"])
        return float(a["iv_pct"] + w * (b["iv_pct"] - a["iv_pct"]))

    atm_row = valid.iloc[(valid["strike"] - spot).abs().argsort()[:2]]
    atm_iv = float(atm_row["iv_pct"].mean()) if not atm_row.empty else float("nan")

    c25 = iv_at_delta(calls, 0.25)
    p25 = iv_at_delta(puts, 0.25)
    c10 = iv_at_delta(calls, 0.10)
    p10 = iv_at_delta(puts, 0.10)

    rr25 = (c25 - p25) if not (math.isnan(c25) or math.isnan(p25)) else float("nan")
    bf25 = ((c25 + p25) / 2 - atm_iv) if not (math.isnan(c25) or math.isnan(p25)
                                              or math.isnan(atm_iv)) else float("nan")

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("ATM IV", f"{atm_iv:.1f}%" if not math.isnan(atm_iv) else "—")
    k2.metric("25Δ Risk Reversal",
              f"{rr25:+.2f}" if not math.isnan(rr25) else "—",
              help="25Δ Call IV − 25Δ Put IV. Positive = calls mehnge "
                   "(upside demand). Negative = puts mehnge (crash hedging).")
    k3.metric("25Δ Butterfly",
              f"{bf25:+.2f}" if not math.isnan(bf25) else "—",
              help="Wings ka average minus ATM. Zyada = smile gehra = "
                   "market tail risk price kar raha hai.")
    k4.metric("10Δ Put − 10Δ Call",
              f"{(p10 - c10):+.2f}" if not (math.isnan(p10) or math.isnan(c10)) else "—",
              help="Deep tail skew. Crypto mein aksar put side bhaari hota hai.")

    if not math.isnan(rr25):
        if rr25 > 1.5:
            st.info("**Call skew:** Market upside ke liye premium de raha hai. "
                    "Call spreads bechne wale ko yahan zyada credit milega, "
                    "lekin ye aksar rally ke beech dikhta hai — "
                    "matlab momentum ke against ja rahe honge.")
        elif rr25 < -1.5:
            st.info("**Put skew:** Downside protection mehngi hai. Ye crypto ki "
                    "default state hai. Put selling se credit accha milega par "
                    "gap-down risk usi wajah se price hua hai.")
        else:
            st.info("**Flat skew:** Dono taraf lagbhag barabar priced hai. "
                    "Directional skew trades ke liye edge kam hai.")

    # ---- IV table -------------------------------------------------------
    with st.expander("📋 Strike-wise IV table"):
        tbl = valid[["strike", "is_call", "iv_pct", "delta", "moneyness_pct",
                     "spread_pct", "oi_contracts"]].copy()
        tbl["Type"] = tbl["is_call"].map({True: "CALL", False: "PUT"})
        tbl = tbl[["Type", "strike", "moneyness_pct", "iv_pct", "delta",
                   "spread_pct", "oi_contracts"]]
        tbl.columns = ["Type", "Strike", "Moneyness %", "IV %", "Delta",
                       "Spread %", "OI"]
        st.dataframe(
            tbl.style.format({
                "Strike": "{:,.0f}", "Moneyness %": "{:+.1f}", "IV %": "{:.2f}",
                "Delta": "{:+.3f}", "Spread %": "{:.1f}", "OI": "{:,.0f}",
            }, na_rep="—"),
            hide_index=True, width="stretch", height=380,
        )

# ==========================================================================
# TAB 2 — Term Structure
# ==========================================================================

with tab_term:
    st.markdown(theme.section("ATM IV across every live expiry"), unsafe_allow_html=True)
    st.caption("Har expiry ke liye ek alag API call jaati hai. "
               "Expiries jitni zyada, utna time lagega — sab cached hai.")

    max_expiries = st.slider("Kitni expiries scan karein", 2, 12, 6)
    expiries = settings.get("expiries", [])[:max_expiries]

    if len(expiries) < 2:
        st.warning("Term structure ke liye kam se kam 2 live expiries chahiye.")
    else:
        bucket = api.make_cache_bucket(settings["refresh_seconds"])
        rows = []
        progress = st.progress(0.0, text="Expiries fetch kar rahe hain...")

        for idx, exp in enumerate(expiries):
            try:
                raw = api.fetch_chain_raw(settings["underlying"],
                                          exp["api_date"], bucket)
            except api.DeltaApiError as exc:
                st.warning(f"{exp['api_date']} skip kiya: {exc}")
                continue

            sub = api.normalize_chain(raw, products)
            if sub.empty:
                continue

            sub_spot = api.resolve_spot(sub)
            if math.isnan(sub_spot):
                sub_spot = spot

            cv = api.resolve_contract_value(sub, settings["underlying"])
            calib = ui.calibrate(sub, sub_spot, cv, context["now"], settings)
            enr = ui.enrich_chain(sub, sub_spot, cv, context["now"],
                                  settings, calib)

            good = enr[enr["iv"].notna() & (enr["iv"] > 0) & enr["two_sided"]]
            if good.empty:
                good = enr[enr["iv"].notna() & (enr["iv"] > 0)]
            if good.empty:
                continue

            near = good.iloc[(good["strike"] - sub_spot).abs().argsort()[:2]]
            days = exp["seconds_left"] / 86400.0

            rows.append({
                "Expiry": exp["expiry_utc"].astimezone(api.IST).strftime("%d-%b-%Y"),
                "Days": days,
                "ATM IV %": float(near["iv_pct"].mean()),
                "Strikes": int(good["strike"].nunique()),
                "Liquid %": float(good["two_sided"].mean() * 100.0),
                "Total OI": float(good["oi_contracts"].fillna(0).sum()),
            })
            progress.progress((idx + 1) / len(expiries),
                              text=f"{idx + 1}/{len(expiries)} expiries")

        progress.empty()

        if len(rows) < 2:
            st.warning("Sirf ek expiry se data mila — term structure nahi ban sakta.")
        else:
            term = pd.DataFrame(rows).sort_values("Days")

            st.plotly_chart(
                ch.term_structure(term["Expiry"].tolist(),
                                  term["ATM IV %"].tolist(),
                                  term["Days"].tolist()),
                width="stretch",
            )

            front, back = term.iloc[0], term.iloc[-1]
            slope = back["ATM IV %"] - front["ATM IV %"]

            t1, t2, t3 = st.columns(3)
            t1.metric("Front ATM IV", f"{front['ATM IV %']:.1f}%",
                      help=f"{front['Expiry']} · {front['Days']:.1f} days")
            t2.metric("Back ATM IV", f"{back['ATM IV %']:.1f}%",
                      help=f"{back['Expiry']} · {back['Days']:.1f} days")
            t3.metric("Slope (back − front)", f"{slope:+.1f} vol pts")

            if slope > 2:
                st.info("**Contango** — door ki vol mehngi hai. Calendar spread "
                        "(front bechna, back kharidna) ke liye theoretically "
                        "achha setup, lekin front expiry ka gamma risk yaad rahe.")
            elif slope < -2:
                st.info("**Backwardation** — paas ki vol mehngi hai. Aam taur par "
                        "market kisi turant event ya stress ko price kar raha "
                        "hota hai. Front premium selling tempting lagti hai "
                        "aur usi liye khatarnak hoti hai.")
            else:
                st.info("**Flat term structure** — expiries ke beech koi khaas "
                        "vol edge nahi. Calendar trades par fees aur spread "
                        "hi jeet jayenge.")

            st.dataframe(
                term.style.format({
                    "Days": "{:.2f}", "ATM IV %": "{:.2f}",
                    "Strikes": "{:,.0f}", "Liquid %": "{:.0f}%",
                    "Total OI": "{:,.0f}",
                }),
                hide_index=True, width="stretch",
            )

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
