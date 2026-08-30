"""
MMC Delta Scanner - Shared UI + Enrichment Layer
================================================
Every page calls into this module so that:
  1. The sidebar controls are identical everywhere.
  2. Any page can be opened directly (deep link / bookmark) and still work,
     because defaults live in session_state, not in app.py.
  3. All the risky unit maths happens in exactly ONE place.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from . import delta_api as api
from . import fees as fx
from . import options_math as om
from . import settings_store as store
from . import theme, url_state
from . import volatility as vx

UTC = timezone.utc

IV_MODES = ["Auto (recommended)", "Force ÷100 (API sends percent)",
            "Force as-is (API sends decimal)"]
GREEK_MODES = ["Auto (recommended)", "Delta API", "MMC Black-Scholes"]
PRICE_MODES = ["Realistic (buy ask / sell bid)", "Mid", "Mark"]
PRICE_MODE_KEY = {"Realistic (buy ask / sell bid)": "realistic",
                  "Mid": "mid", "Mark": "mark"}

# Defaults live here so that every page agrees on them.
DEFAULTS = {
    "underlying": "BTC",
    "expiry_api_date": None,
    "refresh_seconds": 15,
    "usdinr": 88.0,
    "risk_free": 0.0,
    "iv_scale_mode": IV_MODES[0],
    "greeks_source": GREEK_MODES[0],
    "price_mode": PRICE_MODES[0],
    "auto_refresh": False,
    "fee_maker_rate": fx.DEFAULT_MAKER_RATE,
    "fee_taker_rate": fx.DEFAULT_TAKER_RATE,
    "fee_premium_cap": fx.DEFAULT_PREMIUM_CAP,
    "fee_gst": fx.DEFAULT_GST,
    "fee_entry_maker": True,
    "fee_exit_maker": False,
}


def _bootstrap_settings() -> None:
    """Load the saved view into session_state once per session.

    There are two sources and their order matters. The URL is read first,
    because it belongs to this browser and holds the view the user asked to
    open; the local settings file is applied afterwards, and only for keys the
    URL did not supply. Reversing that would let a machine's stale settings
    overwrite a shared link the moment it is opened.
    """
    if st.session_state.get("_mmc_bootstrapped"):
        return

    from_url = url_state.decode(dict(st.query_params))
    saved = store.load_settings()
    for key, val in saved.items():
        if key in DEFAULTS:
            # Guard against a stale file holding a label we no longer offer.
            if key == "iv_scale_mode" and val not in IV_MODES:
                continue
            if key == "greeks_source" and val not in GREEK_MODES:
                continue
            if key == "price_mode" and val not in PRICE_MODES:
                continue
            st.session_state[key] = val

    # The URL wins, so it is applied last.
    for key, val in from_url.items():
        st.session_state[key] = val

    st.session_state["_mmc_bootstrapped"] = True


def sync_url() -> None:
    """Write the current view into the URL so reload and sharing both work.

    Only writes when something has genuinely changed - setting query params on
    every rerun floods the browser history and makes the back button useless.
    """
    state = {k: st.session_state.get(k) for k in
             ("underlying", "expiry_api_date", "price_mode", "usdinr",
              "delta_band_main", "vol_regime_band")}
    wanted = url_state.encode(state)
    if dict(st.query_params) != wanted:
        st.query_params.from_dict(wanted)

# --------------------------------------------------------------------------
# Page chrome
# --------------------------------------------------------------------------

def page_setup(title: str, subtitle: str, icon: str = "📊") -> None:
    _bootstrap_settings()
    st.set_page_config(page_title=f"MMC · {title}", page_icon=icon,
                       layout="wide", initial_sidebar_state="expanded")
    theme.inject(st)
    st.markdown(theme.app_bar(icon, title, subtitle), unsafe_allow_html=True)


def _ss(key):
    """Read a setting from session_state, falling back to the default."""
    if key not in st.session_state:
        st.session_state[key] = DEFAULTS[key]
    return st.session_state[key]


# --------------------------------------------------------------------------
# Products loader with friendly failure
# --------------------------------------------------------------------------

def _retry_button(key: str) -> None:
    """Give the user a real way forward on failure, not just advice.

    This used to read "press Clear cache in the sidebar" - but when the chain
    fails to load, the sidebar has not been drawn. So the button belongs right
    here, next to the error.
    """
    if st.button("🔄 Try again", key=key, type="primary"):
        st.cache_data.clear()
        st.rerun()


def load_products():
    """Returns the products DataFrame, or None after showing an error box."""
    try:
        return api.fetch_option_products()
    except api.DeltaApiError as exc:
        st.error(f"**Could not load the contract list**\n\n{exc}")
        _retry_button("retry_products")
        return None


# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------

# (script path, label, icon) - the icons match the module cards, so what you
# saw on the home page is recognisable in the sidebar.
NAV = [
    ("app.py", "Home", "🏠"),
    ("pages/1_Live_Chain.py", "Live Chain", "📈"),
    ("pages/2_Theta_Decay.py", "Theta Decay", "⏳"),
    ("pages/3_IV_Skew.py", "IV Skew", "🌊"),
    ("pages/4_Payoff_Builder.py", "Payoff Builder", "🎯"),
    ("pages/5_Mispricing.py", "Mispricing", "🔎"),
    ("pages/6_Delta_Filter.py", "Delta Filter", "📐"),
    ("pages/7_Vol_Regime.py", "Vol Regime", "🌡️"),
]


def render_nav() -> None:
    """Our own sidebar navigation.

    Streamlit's built-in nav derives labels from filenames, so the home page
    shows as "app" and the rest as "1_Live_Chain". CSS hides it, and this
    function supplies proper names with the same icons used on the home page's
    module cards.
    """
    st.sidebar.markdown(theme.side_head("Modules"), unsafe_allow_html=True)
    for path, label, icon in NAV:
        try:
            st.sidebar.page_link(path, label=label, icon=icon)
        except Exception:
            # page_link needs a recent Streamlit; if it is missing, skip the
            # nav rather than letting the rest of the app stop.
            break


def render_global_sidebar(products: pd.DataFrame) -> dict:
    """Draw the shared sidebar and return the resolved settings dict."""
    render_nav()

    st.sidebar.markdown(theme.side_head("Market"), unsafe_allow_html=True)

    underlyings = api.list_underlyings(products)
    if not underlyings:
        st.sidebar.error("No live underlying found.")
        st.stop()

    prev_u = _ss("underlying")
    u_index = underlyings.index(prev_u) if prev_u in underlyings else 0
    underlying = st.sidebar.selectbox("Underlying", underlyings, index=u_index)
    st.session_state["underlying"] = underlying

    expiries = api.list_expiries(products, underlying)
    if not expiries:
        st.sidebar.error(f"No future expiry is live for {underlying}.")
        st.stop()

    labels = [e["label"] for e in expiries]
    prev_date = _ss("expiry_api_date")
    e_index = 0
    for i, e in enumerate(expiries):
        if e["api_date"] == prev_date:
            e_index = i
            break

    chosen_label = st.sidebar.selectbox("Expiry", labels, index=e_index)
    expiry = expiries[labels.index(chosen_label)]
    st.session_state["expiry_api_date"] = expiry["api_date"]

    st.sidebar.markdown(theme.side_head("Data"), unsafe_allow_html=True)

    refresh_seconds = st.sidebar.select_slider(
        "Data refresh window (sec)",
        options=[5, 10, 15, 30, 60, 120],
        value=_ss("refresh_seconds"),
        help="Refreshing faster than this burns through Delta's 5-minute "
             "rate-limit quota. 15 seconds is a safe default.",
    )
    st.session_state["refresh_seconds"] = refresh_seconds

    usdinr = st.sidebar.number_input(
        "USD → INR rate", min_value=50.0, max_value=150.0,
        value=float(_ss("usdinr")), step=0.25,
        help="Every Delta number is in USD; the rupee columns are derived from "
             "this rate. It is entered manually, so there is no extra API "
             "dependency.",
    )
    st.session_state["usdinr"] = usdinr

    st.sidebar.markdown(theme.side_head("Pricing"), unsafe_allow_html=True)

    price_mode = st.sidebar.radio(
        "Price basis", PRICE_MODES, key="price_basis_pick",
        index=PRICE_MODES.index(_ss("price_mode")),
        help="Realistic means you pay the ASK when buying and receive the BID "
             "when selling. Nothing fills at the mark price, so edge derived "
             "from it exists only on paper.",
    )
    st.session_state["price_mode"] = price_mode

    # ---------------- Fees ----------------
    with st.sidebar.expander("\U0001f4b8 Fees (Delta India)"):
        st.caption("Fees are charged on NOTIONAL, not on premium - but capped "
                   "at a percentage of the premium. Delta changes these "
                   "numbers from time to time, so all of them are editable.")
        fee_maker = st.number_input(
            "Maker fee (% of notional)", min_value=0.0, max_value=1.0,
            value=float(_ss("fee_maker_rate")) * 100.0, step=0.001, format="%.3f",
        ) / 100.0
        fee_taker = st.number_input(
            "Taker fee (% of notional)", min_value=0.0, max_value=1.0,
            value=float(_ss("fee_taker_rate")) * 100.0, step=0.001, format="%.3f",
        ) / 100.0
        fee_cap = st.number_input(
            "Premium cap (% of premium)", min_value=0.0, max_value=100.0,
            value=float(_ss("fee_premium_cap")) * 100.0, step=0.5, format="%.2f",
            help="The fee never exceeds this percentage of the premium. On "
                 "cheap OTM options this cap is what actually binds.",
        ) / 100.0
        fee_gst = st.number_input(
            "GST on fees (%)", min_value=0.0, max_value=50.0,
            value=float(_ss("fee_gst")) * 100.0, step=1.0, format="%.1f",
        ) / 100.0
        entry_maker = st.checkbox("Entry as Maker (limit order)",
                                  value=bool(_ss("fee_entry_maker")))
        exit_maker = st.checkbox(
            "Exit as Maker (limit order)", value=bool(_ss("fee_exit_maker")),
            help="Off by default - exiting usually means crossing the spread.")

    st.session_state["fee_maker_rate"] = fee_maker
    st.session_state["fee_taker_rate"] = fee_taker
    st.session_state["fee_premium_cap"] = fee_cap
    st.session_state["fee_gst"] = fee_gst
    st.session_state["fee_entry_maker"] = entry_maker
    st.session_state["fee_exit_maker"] = exit_maker

    fee_cfg = fx.FeeConfig(
        maker_rate=fee_maker, taker_rate=fee_taker,
        premium_cap_pct=fee_cap, gst=fee_gst,
        entry_is_maker=entry_maker, exit_is_maker=exit_maker,
    )

    # ---------------- Advanced ----------------
    with st.sidebar.expander("\U0001f52c Advanced / Calibration"):
        risk_free = st.number_input(
            "Risk-free rate (annual %)", min_value=-5.0, max_value=25.0,
            value=float(_ss("risk_free")) * 100.0, step=0.25,
            help="0% is the market convention for crypto options. Do not "
                 "change it without a reason.",
        ) / 100.0
        st.session_state["risk_free"] = risk_free

        iv_scale_mode = st.radio(
            "IV units", IV_MODES, index=IV_MODES.index(_ss("iv_scale_mode")),
            help="Auto determines whether the API sends IV as 55.0 or 0.55 by "
                 "repricing the mark price both ways.",
        )
        st.session_state["iv_scale_mode"] = iv_scale_mode

        greeks_source = st.radio(
            "Greeks source", GREEK_MODES,
            index=GREEK_MODES.index(_ss("greeks_source")),
            help="Auto uses Delta's greeks when they agree with our own "
                 "Black-Scholes, and computes them locally otherwise.",
        )
        st.session_state["greeks_source"] = greeks_source

    st.sidebar.markdown(theme.side_head("Session"), unsafe_allow_html=True)

    auto_refresh = st.sidebar.checkbox(
        "\u23f1\ufe0f Auto-refresh", value=bool(_ss("auto_refresh")),
        help="Reloads the page each time a new refresh window opens.",
    )
    st.session_state["auto_refresh"] = auto_refresh

    col_a, col_b = st.sidebar.columns(2)
    with col_a:
        if st.button("\U0001f504 Refresh", width="stretch"):
            st.rerun()
    with col_b:
        if st.button("\U0001f9f9 Clear cache", width="stretch"):
            st.cache_data.clear()
            st.rerun()

    col_c, col_d = st.sidebar.columns(2)
    with col_c:
        # The Save button appears only on a local run. On a shared deployment
        # it would not save your setting - it would change EVERYONE's, and the
        # file would vanish on reboot. There, the URL is the real save.
        if store.is_enabled():
            if st.button("\U0001f4be Save", width="stretch"):
                ok = store.save_settings({k: st.session_state.get(k)
                                          for k in store.PERSISTED_KEYS})
                if ok:
                    st.sidebar.success("Settings save ho gayi.")
                else:
                    st.sidebar.error("Save failed (write permission?).")
        else:
            st.caption("Bookmark = save")
    with col_d:
        if st.button("\u267b\ufe0f Reset", width="stretch"):
            store.clear_settings()
            for k in list(DEFAULTS):
                st.session_state.pop(k, None)
            for k in ("_mmc_bootstrapped", "delta_band_main", "vol_regime_band"):
                st.session_state.pop(k, None)
            st.query_params.clear()
            st.rerun()

    if not store.is_enabled():
        st.sidebar.caption(
            "Your view lives in the URL - reloading the page brings it back, "
            "and sending that link to someone shows them this exact screen."
        )

    st.sidebar.markdown(
        theme.badge("READ-ONLY BUILD", "good"), unsafe_allow_html=True)
    st.sidebar.caption("No API key, secret or order-placement code anywhere - "
                       "CI verifies this on every push.")

    sync_url()

    return {
        "underlying": underlying,
        "expiry": expiry,
        "expiries": expiries,
        "refresh_seconds": refresh_seconds,
        "usdinr": usdinr,
        "risk_free": risk_free,
        "iv_scale_mode": iv_scale_mode,
        "greeks_source": greeks_source,
        "price_mode": price_mode,
        "price_mode_key": PRICE_MODE_KEY[price_mode],
        "fee_cfg": fee_cfg,
        "auto_refresh": auto_refresh,
    }


def maybe_auto_refresh(settings: dict) -> None:
    """Call at the very BOTTOM of a page. Reruns the app when new data arrives.

    This used to call `time.sleep(interval)`, which was costly twice over: each
    viewer's script thread slept for the whole interval (four people with
    auto-refresh on would exhaust a deployed server), and every click made
    meanwhile was queued, so the UI felt stuck.

    It is now a small timer fragment. The fragment reruns itself without
    blocking the main script, and reruns the app ONLY when the data's refresh
    window has genuinely rolled over. No thread sleeps, and no rerun happens on
    data already on screen.
    """
    if not settings.get("auto_refresh"):
        return

    interval = max(5, int(settings.get("refresh_seconds", 15)))

    if not hasattr(st, "fragment"):
        # Very old Streamlit has no timer fragment. There, declining to
        # auto-refresh beats falling back to a blocking sleep: the user can
        # refresh manually and the server stays healthy.
        st.caption("⏱️ Auto-refresh needs a newer Streamlit - "
                   "use the Refresh button for now.")
        return

    @st.fragment(run_every=interval)
    def _tick():
        bucket = api.make_cache_bucket(interval)
        rendered = st.session_state.get("_mmc_rendered_bucket")
        if rendered is not None and bucket != rendered:
            st.rerun(scope="app")
        st.caption(f"⏱️ Auto-refresh ON · every {interval}s")

    _tick()


# --------------------------------------------------------------------------
# Calibration
# --------------------------------------------------------------------------

def _atm_samples(df: pd.DataFrame, spot: float, now: datetime,
                 count: int = 12) -> list:
    """Pick the most trustworthy rows for calibration.

    Near-ATM strikes with a two-sided book are the only rows where the mark
    price is reliable enough to reverse-engineer units from. Deep OTM strikes
    on crypto chains are frequently stale or zero-bid.
    """
    if df.empty or math.isnan(spot) or spot <= 0:
        return []

    work = df.copy()
    work["dist"] = (work["strike"] - spot).abs()
    work = work[work["mark_price"] > 0]
    work = work[work["iv_raw"] > 0]
    work = work[work["mid"].notna()]
    work = work.nsmallest(count, "dist")

    samples = []
    for _, row in work.iterrows():
        t_years = om.years_to_expiry(now, row["expiry_utc"])
        if t_years <= 0:
            continue
        samples.append({
            "S": spot,
            "K": float(row["strike"]),
            "T": t_years,
            "iv_raw": float(row["iv_raw"]),
            "is_call": bool(row["is_call"]),
            "mark_price": float(row["mark_price"]),
        })
    return samples


def calibrate(df: pd.DataFrame, spot: float, contract_value: float,
              now: datetime, settings: dict) -> dict:
    """Resolve IV units and greek basis. Returns a diagnostics dict."""
    r = settings["risk_free"]
    samples = _atm_samples(df, spot, now)

    # --- IV scale -------------------------------------------------------
    mode = settings["iv_scale_mode"]
    if mode.startswith("Force ÷100"):
        iv_divisor, iv_detect = 100.0, {"divisor": 100.0, "n": 0,
                                        "err_decimal": float("nan"),
                                        "err_percent": float("nan")}
    elif mode.startswith("Force as-is"):
        iv_divisor, iv_detect = 1.0, {"divisor": 1.0, "n": 0,
                                      "err_decimal": float("nan"),
                                      "err_percent": float("nan")}
    else:
        iv_detect = om.detect_iv_scale(samples, r=r)
        iv_divisor = iv_detect["divisor"]

    # --- Greek basis ----------------------------------------------------
    greek_samples = []
    for s in samples:
        greek_samples.append({
            "S": s["S"], "K": s["K"], "T": s["T"],
            "sigma": s["iv_raw"] / iv_divisor,
            "is_call": s["is_call"],
            "api_theta": None,
        })

    if greek_samples and not df.empty:
        work = df.copy()
        work["dist"] = (work["strike"] - spot).abs()
        lookup = {(float(r_["strike"]), bool(r_["is_call"])): float(r_["api_theta"])
                  for _, r_ in work.iterrows()
                  if not math.isnan(r_["api_theta"])}
        for gs in greek_samples:
            gs["api_theta"] = lookup.get((gs["K"], gs["is_call"]))

    greek_detect = om.detect_greek_scale(
        [g for g in greek_samples if g["api_theta"] is not None],
        contract_value, r=r,
    )

    src = settings["greeks_source"]
    if src == "Delta API":
        greeks_used = "api"
    elif src == "MMC Black-Scholes":
        greeks_used = "mmc"
    else:
        greeks_used = "api" if greek_detect["basis"] == "per_unit" else "mmc"

    return {
        "iv_divisor": iv_divisor,
        "iv_detect": iv_detect,
        "greek_detect": greek_detect,
        "greeks_used": greeks_used,
        "samples": len(samples),
    }


# --------------------------------------------------------------------------
# Enrichment - the single source of truth for every derived number
# --------------------------------------------------------------------------

def enrich_chain(df: pd.DataFrame, spot: float, contract_value: float,
                 now: datetime, settings: dict, calib: dict) -> pd.DataFrame:
    """Attach time, calibrated IV, greeks, per-lot values and liquidity flags."""
    if df.empty:
        return df

    r = settings["risk_free"]
    usdinr = settings["usdinr"]
    iv_div = calib["iv_divisor"]
    use_api_greeks = calib["greeks_used"] == "api"

    out = df.copy()

    out["t_years"] = out["expiry_utc"].apply(lambda e: om.years_to_expiry(now, e))
    out["seconds_left"] = out["expiry_utc"].apply(
        lambda e: om.seconds_to_expiry(now, e))
    out["iv"] = out["iv_raw"] / iv_div
    out["iv_pct"] = out["iv"] * 100.0

    # Moneyness: >0 means OTM by that % for a call, and the mirror for a put.
    out["moneyness_pct"] = (out["strike"] - spot) / spot * 100.0
    out["abs_moneyness_pct"] = out["moneyness_pct"].abs()

    bs_price, bs_delta, bs_gamma, bs_theta, bs_vega = [], [], [], [], []
    for _, row in out.iterrows():
        K = float(row["strike"])
        T = float(row["t_years"])
        sigma = float(row["iv"]) if not math.isnan(row["iv"]) else float("nan")
        is_call = bool(row["is_call"])

        if math.isnan(sigma) or sigma <= 0:
            bs_price.append(float("nan"))
            bs_delta.append(float("nan"))
            bs_gamma.append(float("nan"))
            bs_theta.append(float("nan"))
            bs_vega.append(float("nan"))
            continue

        bs_price.append(om.bs_price(spot, K, T, sigma, is_call, r))
        g = om.bs_greeks(spot, K, T, sigma, is_call, r)
        bs_delta.append(g["delta"])
        bs_gamma.append(g["gamma"])
        bs_theta.append(g["theta"])
        bs_vega.append(g["vega"])

    out["bs_price"] = bs_price
    out["bs_delta"] = bs_delta
    out["bs_gamma"] = bs_gamma
    out["bs_theta"] = bs_theta
    out["bs_vega"] = bs_vega

    if use_api_greeks:
        out["delta"] = out["api_delta"].where(out["api_delta"].notna(), out["bs_delta"])
        out["gamma"] = out["api_gamma"].where(out["api_gamma"].notna(), out["bs_gamma"])
        out["theta"] = out["api_theta"].where(out["api_theta"].notna(), out["bs_theta"])
        out["vega"] = out["api_vega"].where(out["api_vega"].notna(), out["bs_vega"])
    else:
        out["delta"] = out["bs_delta"]
        out["gamma"] = out["bs_gamma"]
        out["theta"] = out["bs_theta"]
        out["vega"] = out["bs_vega"]

    # Model vs market: a large gap flags a stale or mispriced strike.
    out["model_gap_pct"] = (out["bs_price"] - out["mark_price"]) \
        / out["mark_price"].replace(0, float("nan")) * 100.0

    # ---- Per-lot economics --------------------------------------------
    cv = contract_value if contract_value and contract_value > 0 else 1.0
    cv_safe = cv
    out["premium_lot_usd"] = out["mark_price"] * cv
    out["premium_lot_inr"] = out["premium_lot_usd"] * usdinr
    out["theta_lot_usd"] = out["theta"] * cv
    out["theta_lot_inr"] = out["theta_lot_usd"] * usdinr

    # Daily burn as a share of the premium — the real "is selling worth it" number.
    out["theta_pct_of_premium"] = (out["theta"].abs() / out["mark_price"]
                                   .replace(0, float("nan")) * 100.0)

    # ---- Executable prices + fees -------------------------------------
    # Everything below answers "what would this ACTUALLY cost me", which is a
    # different number from the mark price on a chain this wide.
    mode = settings.get("price_mode_key", "realistic")
    cfg = settings.get("fee_cfg") or fx.FeeConfig()

    buy_px, sell_px, fee_rt_usd, fee_pct, capped = [], [], [], [], []
    for _, row in out.iterrows():
        mark = float(row["mark_price"])
        bid, ask = float(row["best_bid"]), float(row["best_ask"])

        b = fx.execution_price(mark, bid, ask, is_buy=True, mode=mode)
        s_ = fx.execution_price(mark, bid, ask, is_buy=False, mode=mode)
        buy_px.append(b)
        sell_px.append(s_)

        fee_rt_usd.append(fx.round_trip_fee_usd(mark, spot, 1.0, cv_safe, cfg))
        fee_pct.append(fx.fee_as_pct_of_premium(mark, spot, cv_safe, cfg))
        capped.append(fx.cap_binds(mark, spot, cv_safe, cfg))

    out["buy_price"] = buy_px
    out["sell_price"] = sell_px
    out["fee_rt_usd_lot"] = fee_rt_usd
    out["fee_rt_inr_lot"] = out["fee_rt_usd_lot"] * usdinr
    out["fee_pct_of_premium"] = fee_pct
    out["fee_capped"] = capped

    # Crossing the spread twice usually costs several times the exchange fee.
    out["slippage_pct"] = out.apply(
        lambda rr: fx.slippage_cost_pct(rr["best_bid"], rr["best_ask"],
                                        rr["mark_price"]), axis=1)
    out["total_cost_pct"] = out["fee_pct_of_premium"].fillna(0) + \
        out["slippage_pct"].fillna(0)

    # Net decay yield: gross daily burn minus one round trip of friction.
    # This is the number that decides whether selling a strike is worth it.
    out["net_theta_pct_day"] = out["theta_pct_of_premium"] - out["total_cost_pct"]

    # ---- Data quality flags -------------------------------------------
    stale_cut = 120.0  # seconds
    def _age(ts):
        if ts is None or (isinstance(ts, float) and math.isnan(ts)):
            return float("nan")
        try:
            return (now - ts).total_seconds()
        except TypeError:
            return float("nan")

    out["quote_age_sec"] = out["ticker_time_utc"].apply(_age)
    out["is_stale"] = out["quote_age_sec"] > stale_cut
    out["two_sided"] = out["mid"].notna()

    return out


def apply_liquidity_filter(df: pd.DataFrame, max_spread_pct: float,
                           min_oi: float, min_volume: float,
                           max_moneyness_pct: float,
                           require_two_sided: bool,
                           delta_band: tuple | None = None) -> pd.DataFrame:
    """Drop untradable strikes. This is the highest-value filter on Delta India.

    On a crypto chain most far strikes have a one-sided book or a 40%+ spread.
    Scanning them is worse than useless: it produces 'opportunities' that
    evaporate the moment a real order hits the book.
    """
    if df.empty:
        return df

    mask = pd.Series(True, index=df.index)

    if require_two_sided:
        mask &= df["two_sided"].fillna(False)

    if max_spread_pct is not None:
        within_spread = df["spread_pct"] <= max_spread_pct
        if require_two_sided:
            # NaN spread means a one-sided book, which is already excluded above.
            spread_ok = within_spread.fillna(False)
        else:
            # User explicitly allowed one-sided rows, so an unknown spread passes.
            spread_ok = within_spread.fillna(True)
        mask &= spread_ok

    if min_oi is not None and min_oi > 0:
        mask &= df["oi_contracts"].fillna(0) >= min_oi
    if min_volume is not None and min_volume > 0:
        mask &= df["volume"].fillna(0) >= min_volume
    if max_moneyness_pct is not None and max_moneyness_pct > 0:
        mask &= df["abs_moneyness_pct"] <= max_moneyness_pct

    mask &= delta_band_mask(df, delta_band)

    return df[mask].copy()


DELTA_BAND_OFF = (0.0, 100.0)


def delta_band_mask(df: pd.DataFrame, delta_band) -> pd.Series:
    """A mask keeping |delta| x 100 inside a band.

    Traders pick a strike by delta, not by strike price - "sell the 25 delta
    put" is a complete instruction. So the band applies to ABSOLUTE delta:
    asking for 25 must return both the 0.25 delta call and the -0.25 delta put.

    A fully open band (0-100) filters nothing. Setting a band means the user
    has chosen by delta, so a row whose delta is unknown cannot be kept on the
    assumption that it "might match" - it is excluded.
    """
    if delta_band is None or df.empty or "delta" not in df.columns:
        return pd.Series(True, index=df.index)

    lo, hi = float(delta_band[0]), float(delta_band[1])
    if lo > hi:
        lo, hi = hi, lo
    if (lo, hi) == DELTA_BAND_OFF:
        return pd.Series(True, index=df.index)

    abs_delta_pct = df["delta"].abs() * 100.0
    return abs_delta_pct.between(lo, hi).fillna(False)


# --------------------------------------------------------------------------
# Combined loader used by every page
# --------------------------------------------------------------------------

def load_enriched_chain(products: pd.DataFrame, settings: dict):
    """Fetch, normalize, calibrate and enrich.

    Returns (df, context), or (None, None) after showing an error.
    """
    bucket = api.make_cache_bucket(settings["refresh_seconds"])
    try:
        raw = api.fetch_chain_raw(settings["underlying"],
                                  settings["expiry"]["api_date"], bucket)
    except api.DeltaApiError as exc:
        st.error(f"**Could not load the live chain**\n\n{exc}")
        _retry_button("retry_chain")
        return None, None

    df = api.normalize_chain(raw, products)
    if df.empty:
        st.warning("No option tickers were returned for this expiry. "
                   "Try selecting a different one.")
        return None, None

    now = datetime.now(UTC)
    spot = api.resolve_spot(df)
    if math.isnan(spot):
        st.error("Could not resolve the spot price - the chain data is incomplete.")
        return None, None

    contract_value = api.resolve_contract_value(df, settings["underlying"])
    calib = calibrate(df, spot, contract_value, now, settings)
    enriched = enrich_chain(df, spot, contract_value, now, settings, calib)

    # The timer fragment reads this to decide whether new data has arrived.
    st.session_state["_mmc_rendered_bucket"] = bucket

    context = {
        "now": now,
        "spot": spot,
        "contract_value": contract_value,
        "calib": calib,
        "raw_count": len(raw),
        "expiry_utc": settings["expiry"]["expiry_utc"],
        "seconds_left": settings["expiry"]["seconds_left"],
    }
    return enriched, context


# --------------------------------------------------------------------------
# Shared header + diagnostics
# --------------------------------------------------------------------------

def render_context_header(settings: dict, context: dict, df: pd.DataFrame) -> None:
    spot = context["spot"]
    seconds_left = om.seconds_to_expiry(context["now"], context["expiry_utc"])

    # The countdown is toned separately because in an expiry's final hours
    # every other number changes meaning - decay accelerates, gamma turns
    # dangerous, spreads widen. That state belongs in the headline, not buried
    # in diagnostics.
    urgent = 0 < seconds_left < 6 * 3600

    st.markdown(theme.stat_row([
        theme.stat(f"{settings['underlying']} Spot", f"${spot:,.1f}", accent=True),
        theme.stat("Time left", api.humanize_countdown(seconds_left),
                   sub=api.fmt_ist(context["expiry_utc"]),
                   tone="down" if urgent else ""),
        theme.stat("Strikes live", f"{int(df['strike'].nunique())}",
                   sub=f"{len(df)} contracts"),
        theme.stat("Lot size",
                   f"{context['contract_value']:g} {settings['underlying']}",
                   sub=f"₹ @ {settings['usdinr']:.2f}/USD"),
    ]), unsafe_allow_html=True)


def render_diagnostics(context: dict, df: pd.DataFrame, settings: dict) -> None:
    """Everything needed to debug a wrong number, without opening the code."""
    calib = context["calib"]
    iv_d = calib["iv_detect"]
    gk_d = calib["greek_detect"]

    with st.expander("🩺 Diagnostics — units, freshness, data quality"):
        st.markdown("**Unit calibration** (auto-detected by repricing ATM strikes)")

        col1, col2 = st.columns(2)
        with col1:
            verdict = ("API sends IV in percent -> divided by 100"
                       if calib["iv_divisor"] == 100.0
                       else "API IV is already decimal -> used as-is")
            st.write(f"- IV: **{verdict}**")
            if not math.isnan(iv_d.get("err_decimal", float("nan"))):
                st.write(f"- Median reprice error — as-decimal: "
                         f"`{iv_d['err_decimal']*100:.2f}%`, "
                         f"as-percent: `{iv_d['err_percent']*100:.2f}%`")
            st.write(f"- Calibration samples: `{calib['samples']}`")
        with col2:
            st.write(f"- Greek basis detected: **{gk_d['basis']}** "
                     f"(median api/mmc ratio = `{gk_d['ratio']:.4g}`)")
            greeks_label = ("Delta API" if calib["greeks_used"] == "api"
                            else "MMC Black-Scholes")
            st.write(f"- Greeks in use: **{greeks_label}**")
            st.write(f"- Risk-free rate: `{settings['risk_free']*100:.2f}%`")

        st.markdown("---")
        st.markdown("**Data quality**")

        stale_n = int(df["is_stale"].sum()) if "is_stale" in df else 0
        one_sided = int((~df["two_sided"]).sum()) if "two_sided" in df else 0
        no_iv = int(df["iv"].isna().sum()) if "iv" in df else 0

        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Rows fetched", context["raw_count"])
        q2.metric("Stale quotes (>2 min)", stale_n)
        q3.metric("One-sided book", one_sided)
        q4.metric("Missing IV", no_iv)

        if abs(iv_d.get("err_decimal", 0) - iv_d.get("err_percent", 0)) < 0.01 \
                and iv_d.get("n", 0) > 0:
            st.warning("IV auto-detection is not confident - both "
                       "interpretations give a similar error. You can force "
                       "one under Sidebar → Advanced.")

        st.caption(f"Snapshot taken: {api.fmt_ist(context['now'])} · "
                   f"refresh window {settings['refresh_seconds']}s")


def render_liquidity_controls(prefix: str = "",
                              include_delta: bool = True) -> dict:
    """Liquidity filter widgets. Shared so every page filters identically.

    Pass include_delta=False when a page shows its own, larger delta control;
    having the same filter in two places only causes confusion.
    """
    st.sidebar.markdown(theme.side_head("Liquidity Filter"),
                        unsafe_allow_html=True)

    require_two_sided = st.sidebar.checkbox(
        "Two-sided book only (bid AND ask)", value=True, key=f"{prefix}_two_sided",
        help="A one-sided strike cannot realistically be traded.")
    max_spread_pct = st.sidebar.slider(
        "Max bid-ask spread %", 1, 100, 25, key=f"{prefix}_spread",
        help="Spread = (ask - bid) / mid. On Delta India, above 25% means a "
             "practically dead strike.")
    min_oi = st.sidebar.number_input(
        "Min Open Interest (contracts)", min_value=0, value=0, step=50,
        key=f"{prefix}_oi")
    min_volume = st.sidebar.number_input(
        "Min 24h Volume (contracts)", min_value=0, value=0, step=50,
        key=f"{prefix}_vol")
    max_moneyness = st.sidebar.slider(
        "Strike range (± % from spot)", 1, 100, 20, key=f"{prefix}_mny",
        help="How far from spot to show strikes.")

    if include_delta:
        st.sidebar.markdown(theme.side_head("Delta Band"),
                            unsafe_allow_html=True)
        band = st.sidebar.slider(
            "|Δ| × 100", 0, 100, (0, 100), key=f"{prefix}_delta_band",
            help="Show only options in this delta range. 0-100 turns the "
                 "filter off. The band applies to ABSOLUTE delta, so asking "
                 "for 20-30 returns both the 0.25 call and the -0.25 put.",
        )
        if tuple(float(x) for x in band) != DELTA_BAND_OFF:
            st.sidebar.caption(f"Only {band[0]}Δ – {band[1]}Δ contracts")
    else:
        band = DELTA_BAND_OFF

    return {
        "require_two_sided": require_two_sided,
        "max_spread_pct": float(max_spread_pct),
        "min_oi": float(min_oi),
        "min_volume": float(min_volume),
        "max_moneyness_pct": float(max_moneyness),
        "delta_band": (float(band[0]), float(band[1])),
    }


# --------------------------------------------------------------------------
# Volatility index — a VIX-style number built from the chain
# --------------------------------------------------------------------------

def chain_quotes(df: pd.DataFrame) -> tuple:
    """Reshape a normalized chain into the form the volatility engine expects.

    Returns (calls, puts), each shaped {strike: {"bid", "ask"}}.

    The mark price is deliberately not passed through. The VIX formula runs on
    quoted bid-ask midpoints; the mark price is the exchange's own model output,
    and building a "model-free" index from it would be a contradiction.
    """
    calls, puts = {}, {}
    if df.empty:
        return calls, puts

    for _, row in df.iterrows():
        side = calls if bool(row["is_call"]) else puts
        side[float(row["strike"])] = {
            "bid": float(row["best_bid"]),
            "ask": float(row["best_ask"]),
        }
    return calls, puts


def load_volatility_index(products: pd.DataFrame, settings: dict,
                          now: datetime, max_fetch: int = 4) -> dict:
    """Build the selected underlying's VIX-style index from the live chain.

    Only fetches the expiries closest to 30 days - the index needs just two
    that bracket 30 days, and fetching more spends Delta's rate-limit quota for
    nothing. The extra two are fallbacks, because a single expiry's chain can
    be too thin to yield a valid variance at all.

    Returns volatility.volatility_index()'s output plus "per_expiry": each
    fetched expiry's own volatility and diagnostics.
    """
    t_target = vx.TARGET_DAYS / 365.0
    candidates = sorted(settings.get("expiries", []),
                        key=lambda e: abs(e["seconds_left"] / om.SECONDS_PER_YEAR
                                          - t_target))[:max_fetch]

    bucket = api.make_cache_bucket(settings["refresh_seconds"])
    per_expiry = []

    for exp in candidates:
        t_years = om.years_to_expiry(now, exp["expiry_utc"])
        entry = {
            "label": exp["expiry_utc"].astimezone(api.IST).strftime("%d-%b-%Y"),
            "days": t_years * 365.0,
            "t_years": t_years,
            "sigma2": float("nan"),
            "strikes_used": 0,
            "forward": float("nan"),
            "reason": None,
        }

        try:
            raw = api.fetch_chain_raw(settings["underlying"], exp["api_date"], bucket)
        except api.DeltaApiError as exc:
            entry["reason"] = str(exc)
            per_expiry.append(entry)
            continue

        sub = api.normalize_chain(raw, products)
        if sub.empty:
            entry["reason"] = "no tickers returned for this expiry"
            per_expiry.append(entry)
            continue

        calls, puts = chain_quotes(sub)
        result = vx.expiry_variance(calls, puts, t_years, settings["risk_free"])
        entry.update({
            "sigma2": result["sigma2"],
            "strikes_used": result["strikes_used"],
            "forward": result["forward"],
            "k0": result.get("k0", float("nan")),
            "coverage": result.get("coverage"),
            "reason": result["reason"],
        })
        per_expiry.append(entry)

    index = vx.volatility_index(per_expiry)
    index["per_expiry"] = sorted(per_expiry, key=lambda e: e["days"])
    return index
