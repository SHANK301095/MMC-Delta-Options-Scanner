"""
MMC Delta Scanner — Volatility Regime (VIX-style index)
=======================================================
Poore market ki volatility ka ek number, aur uske upar ek regime gate.

KYUN EK INDEX, JAB CHAIN MEIN HAR STRIKE KI IV MAUJOOD HAI
-----------------------------------------------------------
Ek strike ki IV us strike ki kahani batati hai. "Market kitna dara hua hai" ek
alag sawaal hai, aur uska jawab poori chain mein hai — wings sameth.

Ye page wahi karta hai jo CBOE VIX aur India VIX karte hain: har OTM strike ka
quoted midpoint le kar model-free variance nikaalta hai, phir do expiries ke
beech interpolate karke exactly 30 din par le aata hai. Ismein koi
Black-Scholes nahi, koi smile fit nahi — sirf payoff structure aur live quotes.

30 DIN CONSTANT MATURITY KYUN ZAROORI HAI
------------------------------------------
Bina uske "aaj vol 60 hai" ka koi matlab nahi banta, kyunki kal wahi expiry ek
din paas aa chuki hogi aur number apne aap badal jayega. Constant maturity ke
bina aaj ka aur kal ka index compare karne layak hi nahi rehta — aur regime
gate ka poora kaam hi comparison hai.

REGIME GATE
-----------
Aap ek band set karte hain. Index us band mein hai to aapka regime chal raha
hai. Bahar hai to page saaf keh deta hai ki abhi aapki condition poori nahi
hoti — chahe chain par setups kitne bhi acche dikh rahe hon.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from mmc_core import charts as ch
from mmc_core import delta_api as api
from mmc_core import theme
from mmc_core import ui_common as ui
from mmc_core import volatility as vx

ui.page_setup(
    "Volatility Regime",
    "VIX-style index · 30-din constant maturity · model-free · live chain se",
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

with st.spinner(f"{underlying} volatility index compute kar rahe hain…"):
    index = ui.load_volatility_index(products, settings, context["now"])

value = index["value"]
per_expiry = index["per_expiry"]

st.markdown(theme.section("Regime band", "index is range mein ho tabhi aapka regime hai"), unsafe_allow_html=True)
band = st.slider(
    f"{underlying} VIX band", 0, 100, (40, 80), key="vol_regime_band",
    help="Is range mein index ho tabhi aapka regime chal raha hai. "
         "Bahar hone par page warn karega.",
)

status = vx.regime_status(value, (float(band[0]), float(band[1])))

# Band is page par sidebar ke baad set hota hai, to URL dobara sync kijiye.
ui.sync_url()

# --------------------------------------------------------------------------
# Headline
# --------------------------------------------------------------------------

basis = ("30-din constant maturity" if index["constant_maturity"]
         else f"{index['basis_days']:.1f}-din (constant maturity nahi)")

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
    sub=f"{basis} · aapka band {band[0]} – {band[1]}",
    badge_html=theme.badge(badge_text, badge_tone),
    tone="" if status["in_regime"] or status["position"] == "unknown"
         else "down",
), unsafe_allow_html=True)

used = sum(1 for e in per_expiry if e["reason"] is None)
st.markdown(theme.stat_row([
    theme.stat("Band", f"{band[0]} – {band[1]}", sub="regime gate"),
    theme.stat("Basis", basis.split(" (")[0],
               sub="30 din par hi numbers comparable hain",
               tone="" if index["constant_maturity"] else "down"),
    theme.stat("Expiries used", f"{used} / {len(per_expiry)}",
               sub="valid variance nikli",
               tone="down" if used < 2 else ""),
    theme.stat("Distance from band",
               "—" if status["position"] in ("inside", "unknown")
               else f"{status['distance']:.1f} pts",
               sub=status["position"]),
]), unsafe_allow_html=True)

if status["position"] == "unknown":
    st.error(
        "🚫 **Index compute nahi ho paaya — regime ka faisla nahi ho sakta.**\n\n"
        f"{index['note'] or ''}\n\n"
        "Yahan 'regime theek hai' maan lena sabse khatarnak galti hoti: wo ek "
        "aise aadhaar par trade ki ijazat de dega jo maujood hi nahi hai. "
        "Neeche har expiry ki wajah likhi hai."
    )
elif status["in_regime"]:
    st.success(
        f"✅ **Regime mein hain.** {underlying} VIX **{value:.1f}** hai, aur "
        f"aapka band {band[0]}–{band[1]} hai. Aapki volatility condition abhi "
        "poori ho rahi hai."
    )
elif status["position"] == "below":
    st.warning(
        f"⚠️ **Regime se neeche.** {underlying} VIX **{value:.1f}** hai — "
        f"aapke band se **{status['distance']:.1f} points neeche**.\n\n"
        "Vol saste hai. Premium bechne walon ke liye iska matlab hai ki jo "
        "credit mil raha hai wo aapke apne mapdand se kam hai, jabki gamma "
        "risk waisa ka waisa hai."
    )
else:
    st.warning(
        f"⚠️ **Regime se upar.** {underlying} VIX **{value:.1f}** hai — "
        f"aapke band se **{status['distance']:.1f} points upar**.\n\n"
        "Premium mota hai, aur usi wajah se khatarnak: market kisi cheez ko "
        "price kar raha hai. Mehngi vol apne aap mein edge nahi hoti."
    )

if index["note"] and not math.isnan(value):
    st.info(f"ℹ️ {index['note']}")

# --------------------------------------------------------------------------
# Term structure of model-free vol
# --------------------------------------------------------------------------

valid = [e for e in per_expiry if e["reason"] is None and not math.isnan(e["sigma2"])]

if len(valid) >= 2:
    st.markdown(theme.section("Model-free vol, har expiry par"), unsafe_allow_html=True)
    st.caption("Ye IV Skew page ki ATM IV curve nahi hai — har point poori OTM "
               "chain se banta hai, sirf ATM strike se nahi.")
    st.plotly_chart(
        ch.term_structure([e["label"] for e in valid],
                          [math.sqrt(e["sigma2"]) * 100.0 for e in valid],
                          [e["days"] for e in valid]),
        width="stretch",
    )

# --------------------------------------------------------------------------
# Kaam kaise hua
# --------------------------------------------------------------------------

st.markdown(theme.section("Index kaise bana", "har number ka hisaab"), unsafe_allow_html=True)

detail = pd.DataFrame([{
    "Expiry": e["label"],
    "Days": e["days"],
    "Vol %": math.sqrt(e["sigma2"]) * 100.0 if not math.isnan(e["sigma2"]) else float("nan"),
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

# Tang chain index ko chup-chaap NEECHE le jaati hai, aur regime gate ke liye
# ye seedha khatarnak hai: kam VIX padha jayega "vol saste hain", jabki asli
# wajah sirf ye thi ki chain chhoti thi.
narrow = [e for e in valid
          if e.get("coverage") and e["coverage"]["narrow_side"] not in (None, "unknown")]
if narrow:
    worst = min(narrow, key=lambda e: min(e["coverage"]["low_pct"],
                                          e["coverage"]["high_pct"]))
    st.warning(
        f"📏 **Chain tang hai — index sach se KAM aa raha hoga.** "
        f"{worst['label']} par strikes forward se sirf "
        f"−{worst['coverage']['low_pct']:.0f}% / "
        f"+{worst['coverage']['high_pct']:.0f}% tak jaate hain, jabki 30-din ke "
        f"index ko lagbhag ±{vx.MIN_COVERAGE_PCT:.0f}% chahiye.\n\n"
        "Formula sahi hai; kami chain ki hai. Ye bias maturity ke saath badhti "
        "hai, aur regime gate par iska matlab hai ki band ke neeche girna "
        "market ki nahi, coverage ki wajah se ho sakta hai."
    )

if index["constant_maturity"]:
    near, far = index["near"], index["far"]
    st.caption(
        f"Index **{near['label']}** ({near['days']:.1f}d, "
        f"{math.sqrt(near['sigma2'])*100:.1f}%) aur **{far['label']}** "
        f"({far['days']:.1f}d, {math.sqrt(far['sigma2'])*100:.1f}%) ke beech "
        "interpolate hua hai. Interpolation TOTAL VARIANCE par hoti hai, "
        "volatility par nahi — variance time ke saath judti hai, vol nahi."
    )

st.info(
    "🧠 **Is number ko padhne ka tarika:** VIX 30 din ki *expected* vol batata "
    "hai, direction nahi. Uncha VIX ye nahi kehta ki market girega — sirf ye "
    "ki chaal badi hogi, kisi bhi taraf.\n\n"
    "Aur ye **implied** vol hai, realised nahi. Dono ka farak hi premium "
    "selling ka asli edge ya nuksaan hai — lekin us comparison ke liye "
    "historical data chahiye, jo abhi is tool mein nahi hai."
)

ui.render_diagnostics(context, df, settings)
ui.maybe_auto_refresh(settings)
