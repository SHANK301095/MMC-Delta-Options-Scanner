"""
MMC Delta Scanner - Volatility Regime (VIX-style index)
=======================================================
A single number for the whole market's volatility, with a regime gate on top.

WHY AN INDEX WHEN EVERY STRIKE ALREADY HAS AN IV
------------------------------------------------
One strike's IV tells that strike's story. "How frightened is the market" is a
different question, and its answer lives in the whole chain - wings included.

This page does what CBOE VIX and India VIX do: take every OTM strike's quoted
midpoint, derive a model-free variance, then interpolate between two expiries
to land on exactly 30 days. No Black-Scholes, no smile fit - only the payoff
structure and live quotes.

WHY 30-DAY CONSTANT MATURITY MATTERS
------------------------------------
Without it, "volatility is 60 today" means nothing, because tomorrow that same
expiry is a day closer and the number moves on its own. Without constant
maturity, today's index and tomorrow's are not comparable - and comparison is
the entire job of a regime gate.

REGIME GATE
-----------
You set a band. If the index sits inside it, your regime is running. If it sits
outside, the page says plainly that your condition is not currently met -
however good the setups on the chain may look.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import theme
from mmc_core import ui_common as ui
from mmc_core import volatility as vx

ui.page_setup(
    "Volatility Regime",
    "VIX-style index · 30-day constant maturity · model-free · from the live chain",
    icon="🌡️",
)

products = ui.load_products()
if products is None:
    st.stop()

settings = ui.render_global_sidebar(products)

df, context = ui.load_enriched_chain(products, settings)
if df is None:
    st.stop()

ui.render_context_header(settings, context, df)

underlying = settings["underlying"]

# --------------------------------------------------------------------------
# Index
# --------------------------------------------------------------------------

with st.spinner(f"Computing the {underlying} volatility index…"):
    index = ui.load_volatility_index(products, settings, context["now"])

value = index["value"]
per_expiry = index["per_expiry"]

st.markdown(
    theme.section("Regime band", "your regime runs only while the index is in range"),
            unsafe_allow_html=True)
band = st.slider(
    f"{underlying} VIX band", 0, 100, (40, 80), key="vol_regime_band",
    help="Your regime runs only while the index is inside this range. The "
         "page warns you when it is outside.",
)

status = vx.regime_status(value, (float(band[0]), float(band[1])))

# The band is set after the sidebar on this page, so re-sync the URL.
ui.sync_url()

# --------------------------------------------------------------------------
# Headline
# --------------------------------------------------------------------------

basis = ("30-day constant maturity" if index["constant_maturity"]
         else f"{index['basis_days']:.1f}-day (not constant maturity)")

_REGIME_BADGE = {
    "inside": ("IN REGIME", "good"),
    "below": ("BELOW BAND", "warn"),
    "above": ("ABOVE BAND", "serious"),
    "unknown": ("NO READING", "critical"),
}
badge_text, badge_tone = _REGIME_BADGE[status["position"]]

st.markdown(theme.hero(
    f"{underlying} VIX",
    f"{value:.1f}" if not math.isnan(value) else "—",
    sub=f"{basis} · your band {band[0]} – {band[1]}",
    badge_html=theme.badge(badge_text, badge_tone),
    tone="" if status["in_regime"] or status["position"] == "unknown"
         else "down",
), unsafe_allow_html=True)

used = sum(1 for e in per_expiry if e["reason"] is None)
st.markdown(theme.stat_row([
    theme.stat("Band", f"{band[0]} – {band[1]}", sub="regime gate"),
    theme.stat("Basis", basis.split(" (")[0],
               sub="only 30-day readings are comparable",
               tone="" if index["constant_maturity"] else "down"),
    theme.stat("Expiries used", f"{used} / {len(per_expiry)}",
               sub="produced a valid variance",
               tone="down" if used < 2 else ""),
    theme.stat("Distance from band",
               "—" if status["position"] in ("inside", "unknown")
               else f"{status['distance']:.1f} pts",
               sub=status["position"]),
]), unsafe_allow_html=True)

if status["position"] == "unknown":
    st.error(
        "🚫 **The index could not be computed - no regime call can be made.**\n\n"
        f"{index['note'] or ''}\n\n"
        "Assuming 'the regime is fine' here would be the most dangerous "
        "mistake available: it would authorise a trade on a basis that does not "
        "exist. The reason for each expiry is listed below."
    )
elif status["in_regime"]:
    st.success(
        f"✅ **In regime.** {underlying} VIX is **{value:.1f}**, and your band "
        f"is {band[0]}–{band[1]}. Your volatility condition is currently met."
    )
elif status["position"] == "below":
    st.warning(
        f"⚠️ **Below regime.** {underlying} VIX is **{value:.1f}** - "
        f"**{status['distance']:.1f} points below** your band.\n\n"
        "Volatility is cheap. For a premium seller that means the credit on "
        "offer is below your own standard, while the gamma risk is unchanged."
    )
else:
    st.warning(
        f"⚠️ **Above regime.** {underlying} VIX is **{value:.1f}** - "
        f"**{status['distance']:.1f} points above** your band.\n\n"
        "Premium is fat, and dangerous for exactly that reason: the market is "
        "pricing something in. Expensive volatility is not edge by itself."
    )

if index["note"] and not math.isnan(value):
    st.info(f"ℹ️ {index['note']}")

# --------------------------------------------------------------------------
# Term structure of model-free vol
# --------------------------------------------------------------------------

valid = [e for e in per_expiry if e["reason"] is None and not math.isnan(e["sigma2"])]

if len(valid) >= 2:
    st.markdown(
        theme.section("Model-free volatility, per expiry"),
        unsafe_allow_html=True,
    )
    st.caption("This is not the IV Skew page's ATM curve - every point is "
               "built from the whole OTM chain, not one ATM strike.")
    st.plotly_chart(
        ch.term_structure([e["label"] for e in valid],
                          [math.sqrt(e["sigma2"]) * 100.0 for e in valid],
                          [e["days"] for e in valid]),
        width="stretch",
    )

# --------------------------------------------------------------------------
# Kaam kaise hua
# --------------------------------------------------------------------------

st.markdown(
    theme.section("How the index was built", "the arithmetic behind each number"),
            unsafe_allow_html=True)

detail = pd.DataFrame([{
    "Expiry": e["label"],
    "Days": e["days"],
    "Vol %": (math.sqrt(e["sigma2"]) * 100.0
              if not math.isnan(e["sigma2"]) else float("nan")),
    "Strikes used": e["strikes_used"],
    "Forward": e["forward"],
    "K₀": e.get("k0", float("nan")),
    "Coverage": (f"−{e['coverage']['low_pct']:.0f}% / +{e['coverage']['high_pct']:.0f}%"
                 if e.get("coverage") else "—"),
    "Status": "✅ used" if e["reason"] is None else f"⚠️ {e['reason']}",
} for e in per_expiry])

st.dataframe(
    detail.style.format({
        "Days": "{:.2f}", "Vol %": "{:.2f}",
        "Strikes used": "{:,.0f}", "Forward": "${:,.0f}", "K₀": "${:,.0f}",
    }, na_rep="—"),
    hide_index=True, width="stretch",
)

# A narrow chain quietly pushes the index DOWN, and for a regime gate that is
# directly dangerous: a low reading gets taken as "volatility is cheap" when
# the real cause was simply a small chain.
narrow = [e for e in valid
          if e.get("coverage")
          and e["coverage"]["narrow_side"] not in (None, "unknown")]
if narrow:
    worst = min(narrow, key=lambda e: min(e["coverage"]["low_pct"],
                                          e["coverage"]["high_pct"]))
    st.warning(
        f"📏 **The chain is narrow - the index is probably reading LOW.** "
        f"On {worst['label']} the strikes reach only "
        f"−{worst['coverage']['low_pct']:.0f}% / "
        f"+{worst['coverage']['high_pct']:.0f}% from the forward, while a "
        f"30-day index needs roughly ±{vx.MIN_COVERAGE_PCT:.0f}%.\n\n"
        "The formula is correct; the chain is the limitation. This bias grows "
        "with maturity, and at the regime gate it means a drop below the band "
        "may be caused by coverage rather than by the market."
    )

if index["constant_maturity"]:
    near, far = index["near"], index["far"]
    st.caption(
        f"Interpolated between **{near['label']}** ({near['days']:.1f}d, "
        f"{math.sqrt(near['sigma2'])*100:.1f}%) and **{far['label']}** "
        f"({far['days']:.1f}d, {math.sqrt(far['sigma2'])*100:.1f}%). The "
        "interpolation runs on TOTAL VARIANCE, not on volatility - variance "
        "adds across time, volatility does not."
    )

st.info(
    "🧠 **How to read this number:** the index gives *expected* volatility over "
    "30 days, not direction. A high reading does not say the market will fall - "
    "only that the move will be large, either way.\n\n"
    "And this is **implied** volatility, not realised. The gap between the two "
    "is where premium selling actually wins or loses - but that comparison "
    "needs historical data, which this tool does not yet hold."
)

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
