#!/usr/bin/env python3
"""Live-data verification against the real Delta Exchange India chain.

WHY THIS EXISTS
---------------
Every number this project produces has been verified against a synthetic
Black-Scholes chain, because the development sandbox cannot reach Delta. A
synthetic chain proves the arithmetic is right; it cannot prove the
*assumptions about Delta's payloads* are right. Those assumptions are the
part most likely to be wrong, and most likely to drift silently when the
exchange changes something:

  - implied volatility arrives as a percent, not a decimal
  - greeks arrive per unit of underlying, not per lot
  - timestamps arrive in microseconds
  - contract_value is 0.001 for BTC and 0.01 for ETH
  - every live option carries a two-sided quote worth reading

This script runs the real chain through the project's own code and checks
each of those, plus the derived numbers the pages render. It reads the same
public endpoints the app reads and nothing else: no credential of any kind is
involved, because none exists and none is needed.

USAGE
-----
    python tools/live_check.py                  # BTC, nearest expiry
    python tools/live_check.py --underlying ETH
    python tools/live_check.py --all-expiries   # every live expiry
    python tools/live_check.py --json report.json

Exit code is 0 when every check passes, 1 when any check FAILs. WARNs do not
fail the run - they flag things worth a human look (a thin chain, a wide
market) that are not defects.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from mmc_core import delta_api as api
from mmc_core import fees as fx
from mmc_core import ui_common as ui

UTC = timezone.utc

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

_MARK = {PASS: "  ok  ", WARN: " warn ", FAIL: " FAIL ", INFO: " info "}


class Report:
    """Collects check results and prints them as one readable block."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.section_name = ""

    def section(self, name: str) -> None:
        self.section_name = name
        print(f"\n{'=' * 74}\n{name}\n{'=' * 74}")

    def add(self, status: str, label: str, detail: str = "") -> None:
        self.rows.append({"section": self.section_name, "status": status,
                          "check": label, "detail": detail})
        line = f"[{_MARK[status]}] {label}"
        print(line if not detail else f"{line}\n            {detail}")

    def check(self, ok: bool, label: str, detail: str = "",
              soft: bool = False, fail_detail: str | None = None) -> bool:
        """fail_detail replaces detail when the check does not pass.

        Several of these checks have nothing worth saying when they pass
        ("0 rows outside the range") but a lot worth saying when they fail.
        """
        shown = detail if (ok or fail_detail is None) else fail_detail
        self.add(PASS if ok else (WARN if soft else FAIL), label, shown)
        return ok

    def counts(self) -> dict:
        out = {PASS: 0, WARN: 0, FAIL: 0, INFO: 0}
        for r in self.rows:
            out[r["status"]] += 1
        return out


def _f(value, nd: int = 4) -> str:
    """Format a float for the report, tolerating NaN and None."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return "nan" if math.isnan(v) else f"{v:,.{nd}f}"


def settings_for(underlying: str) -> dict:
    """The same settings dict the sidebar builds, at its defaults.

    Using the defaults matters: it is what a first-time visitor sees, so it is
    the configuration whose correctness is worth verifying.
    """
    d = ui.DEFAULTS
    return {
        "underlying": underlying,
        "refresh_seconds": d["refresh_seconds"],
        "usdinr": d["usdinr"],
        "risk_free": d["risk_free"],
        "iv_scale_mode": d["iv_scale_mode"],
        "greeks_source": d["greeks_source"],
        "price_mode": d["price_mode"],
        "price_mode_key": ui.PRICE_MODE_KEY[d["price_mode"]],
        "fee_cfg": fx.FeeConfig(
            maker_rate=d["fee_maker_rate"],
            taker_rate=d["fee_taker_rate"],
            premium_cap_pct=d["fee_premium_cap"],
            gst=d["fee_gst"],
            entry_is_maker=d["fee_entry_maker"],
            exit_is_maker=d["fee_exit_maker"],
        ),
        "auto_refresh": False,
    }


# --------------------------------------------------------------------------
# 1. Products - the contract specs every other number leans on
# --------------------------------------------------------------------------

def check_products(rep: Report) -> pd.DataFrame:
    rep.section("1. Product catalogue  (/v2/products)")

    products = api.fetch_option_products()
    rep.add(INFO, f"{len(products)} live option contracts returned")

    unders = api.list_underlyings(products)
    rep.check(bool(unders), "at least one underlying has live options",
              f"underlyings: {', '.join(unders[:12])}")

    for col in ("strike", "expiry_utc", "contract_value"):
        missing = int(products[col].isna().sum())
        rep.check(missing == 0, f"every contract has a {col}",
                  fail_detail=f"{missing} of {len(products)} missing")

    # resolve_contract_value falls back to these when the payload omits one.
    # If the exchange ever changes a multiplier, the fallback becomes a
    # silently wrong number, so compare it against what Delta actually sends.
    for sym, expected in (("BTC", 0.001), ("ETH", 0.01)):
        sub = products[products["underlying"] == sym]
        if sub.empty:
            continue
        seen = sorted({float(v) for v in sub["contract_value"].dropna()})
        rep.check(seen == [expected],
                  f"{sym} contract_value is still {expected}",
                  fail_detail=f"Delta sent {seen}, but resolve_contract_value "
                              f"falls back to {expected} - that fallback is "
                              f"now wrong and every per-lot number with it")

    now = datetime.now(UTC)
    past = int((products["expiry_utc"] < now).sum())
    rep.check(past == 0, "no already-expired contract is marked live",
              soft=True,
              fail_detail=f"{past} contracts have an expiry in the past")

    return products


# --------------------------------------------------------------------------
# 2. Chain payload - quotes, timestamps, spot
# --------------------------------------------------------------------------

def check_chain(rep: Report, products: pd.DataFrame, underlying: str,
                expiry: dict) -> tuple:
    api_date = expiry["api_date"]
    when = expiry["expiry_utc"]
    rep.section(f"2. Chain payload  ({underlying}  expiry {when:%d-%b-%Y})")

    raw = api.fetch_chain_raw(underlying, api_date,
                              api.make_cache_bucket(15))
    rep.check(bool(raw), f"/v2/tickers returned rows for {api_date}",
              f"{len(raw)} raw tickers")
    if not raw:
        return pd.DataFrame(), float("nan"), float("nan")

    df = api.normalize_chain(raw, products)
    rep.check(not df.empty, "chain normalizes to a non-empty frame",
              f"{len(df)} rows, {df['strike'].nunique()} strikes")
    if df.empty:
        return df, float("nan"), float("nan")

    # --- quotes -------------------------------------------------------
    two_sided = int(df["mid"].notna().sum())
    pct = two_sided / len(df) * 100.0
    rep.check(two_sided > 0, "at least some strikes are two-sided",
              f"{two_sided}/{len(df)} ({pct:.0f}%) have both a bid and an ask")
    rep.check(pct >= 40.0, "most of the chain is quotable",
              f"only {pct:.0f}% two-sided - a thin chain biases the vol index low",
              soft=True)

    # Test this on the raw bid/ask, NOT on rows that have a mid: normalize_chain
    # deliberately leaves mid empty when bid > ask, so filtering on mid first
    # would hide every crossed row from the very check looking for them.
    both = df[df["best_bid"].notna() & df["best_ask"].notna()]
    crossed = int((both["best_bid"] > both["best_ask"]).sum())
    rep.check(crossed == 0, "no crossed markets (bid > ask)",
              fail_detail=f"{crossed} of {len(both)} quoted rows have bid above "
                          "ask; those rows lose their mid and drop out of the "
                          "volatility index")

    quoted = df[df["mid"].notna()]

    if not quoted.empty:
        rep.add(INFO, "spread, percent of mid",
                f"median {_f(quoted['spread_pct'].median(), 1)}%   "
                f"p90 {_f(quoted['spread_pct'].quantile(0.9), 1)}%   "
                f"max {_f(quoted['spread_pct'].max(), 1)}%")

    # --- marks and IV -------------------------------------------------
    no_mark = int(df["mark_price"].isna().sum())
    rep.check(no_mark == 0, "every row carries a mark price", soft=True,
              fail_detail=f"{no_mark} rows have no mark")

    no_iv = int(df["iv_raw"].isna().sum())
    rep.check(no_iv < len(df), "the chain carries implied volatility",
              f"{no_iv}/{len(df)} rows have no IV",
              soft=no_iv < len(df))

    # --- timestamps: the microsecond assumption -----------------------
    ages = df["ticker_time_utc"].dropna()
    if ages.empty:
        rep.add(WARN, "no ticker timestamps to check the time unit against")
    else:
        now = datetime.now(UTC)
        age_sec = [(now - t).total_seconds() for t in ages]
        med = sorted(age_sec)[len(age_sec) // 2]
        # A wrong unit is not subtle: it lands centuries away, not minutes.
        rep.check(abs(med) < 86_400,
                  "ticker timestamps decode to roughly now",
                  f"median quote age {_f(med, 1)}s - if this were wildly off, "
                  "the microsecond assumption would be wrong")
        rep.check(med < 300, "quotes are fresh",
                  f"median quote age {_f(med, 1)}s", soft=True)

    # --- spot ---------------------------------------------------------
    spot = api.resolve_spot(df)
    rep.check(spot > 0, f"a spot price resolves for {underlying}",
              f"median spot {_f(spot, 2)}")

    spots = df["spot_price"].dropna()
    spots = spots[spots > 0]
    if len(spots) > 1 and spot > 0:
        disp = (spots.max() - spots.min()) / spot * 100.0
        rep.check(disp < 1.0,
                  "every strike agrees on spot",
                  f"spread across rows is {_f(disp, 3)}% "
                  f"({_f(spots.min(), 2)} .. {_f(spots.max(), 2)}) - "
                  "resolve_spot takes the median, so a lone stale row is absorbed",
                  soft=True)

    cv = api.resolve_contract_value(df, underlying)
    rep.check(cv > 0, "a contract multiplier resolves", f"contract_value {cv}")

    return df, spot, cv


# --------------------------------------------------------------------------
# 3. Calibration - the two unit assumptions, detected at runtime
# --------------------------------------------------------------------------

def check_calibration(rep: Report, df: pd.DataFrame, spot: float, cv: float,
                      settings: dict) -> dict:
    rep.section("3. Runtime calibration  (IV units, greek basis)")

    now = datetime.now(UTC)
    calib = ui.calibrate(df, spot, cv, now, settings)

    n = calib["samples"]
    rep.check(n > 0, "ATM strikes were found to calibrate against",
              f"{n} samples near the money")
    if n == 0:
        return calib

    ivd = calib["iv_detect"]
    div = calib["iv_divisor"]
    rep.check(div in (1.0, 100.0), "IV scale resolved to a sane divisor",
              f"divisor {div} "
              f"(repricing error as decimal {_f(ivd.get('err_decimal'))}, "
              f"as percent {_f(ivd.get('err_percent'))})")
    rep.check(div == 100.0,
              "Delta still sends IV as a percent, as the code assumes",
              soft=True,
              fail_detail=f"the detected divisor is {div}, not 100. Delta "
                          "appears to have switched to decimal IV - every IV "
                          "shown is off by 100x unless Auto catches it")

    gd = calib["greek_detect"]
    rep.add(INFO, "greek basis detected",
            f"basis={gd.get('basis')}  using={calib['greeks_used']} greeks")
    basis = gd.get("basis")
    rep.check(basis in ("per_unit", "per_lot"),
              "greek basis was positively identified",
              f"basis={basis} from {gd.get('n')} samples, "
              f"median ratio {_f(gd.get('ratio'))}",
              soft=True,
              fail_detail=f"detection returned '{basis}' - Delta's greeks did "
                          "not match per-unit or per-lot, so the app fell back "
                          "to its own Black-Scholes greeks. The numbers stay "
                          "sound, but Delta's greeks are being ignored.")
    rep.check(basis != "per_unit" or calib["greeks_used"] == "api",
              "per-unit greeks from Delta are being used directly",
              soft=True,
              fail_detail=f"basis is per_unit but greeks_used="
                          f"{calib['greeks_used']}")

    return calib


# --------------------------------------------------------------------------
# 4. Derived numbers - what the pages actually render
# --------------------------------------------------------------------------

def check_derived(rep: Report, df: pd.DataFrame, spot: float, cv: float,
                  settings: dict, calib: dict) -> pd.DataFrame:
    rep.section("4. Derived numbers after enrichment")

    now = datetime.now(UTC)
    out = ui.enrich_chain(df, spot, cv, now, settings, calib)
    rep.check(not out.empty, "enrichment produces a frame", f"{len(out)} rows")
    if out.empty:
        return out

    # --- greeks -------------------------------------------------------
    calls = out[out["is_call"]]
    puts = out[~out["is_call"]]

    bad_c = int(((calls["delta"] < -0.01) | (calls["delta"] > 1.01)).sum())
    bad_p = int(((puts["delta"] < -1.01) | (puts["delta"] > 0.01)).sum())
    rep.check(bad_c == 0, "call deltas lie in [0, 1]",
              fail_detail=f"{bad_c} calls outside the range")
    rep.check(bad_p == 0, "put deltas lie in [-1, 0]",
              fail_detail=f"{bad_p} puts outside the range")

    # Model-free: at one strike, call delta - put delta must be 1 (at r = 0).
    # This is the single best cross-check that the greeks are on the basis we
    # think they are, because it holds no matter what the volatility is.
    merged = calls[["strike", "delta"]].merge(
        puts[["strike", "delta"]], on="strike", suffixes=("_c", "_p"))
    merged = merged.dropna()
    if merged.empty:
        rep.add(WARN, "no matched call/put pair to test delta parity")
    else:
        err = (merged["delta_c"] - merged["delta_p"] - 1.0).abs()
        rep.check(float(err.max()) < 0.05,
                  "put-call delta parity holds across the chain",
                  f"worst |Δc - Δp - 1| = {_f(err.max())} "
                  f"over {len(merged)} strikes")

    neg_theta = int((out["theta"].dropna() > 0).sum())
    rep.check(neg_theta == 0, "theta is negative for long options", soft=True,
              fail_detail=f"{neg_theta} rows show positive theta")

    # --- IV -----------------------------------------------------------
    iv = out["iv"].dropna()
    if iv.empty:
        rep.add(WARN, "no calibrated IV to range-check")
    else:
        rep.check(float(iv.min()) > 0.01 and float(iv.max()) < 5.0,
                  "calibrated IV sits in a plausible band",
                  f"{_f(iv.min() * 100, 1)}% .. {_f(iv.max() * 100, 1)}%  "
                  f"(median {_f(iv.median() * 100, 1)}%)")

    # --- money --------------------------------------------------------
    prem = out["premium_lot_usd"].dropna()
    if not prem.empty:
        rep.check(float(prem.min()) >= 0, "no negative premium per lot",
                  f"{_f(prem.min(), 2)} .. {_f(prem.max(), 2)} USD")

    fee = out["fee_rt_usd_lot"].dropna()
    if fee.empty:
        rep.add(WARN, "no round-trip fee computed")
    else:
        rep.check(float(fee.min()) >= 0, "round-trip fees are non-negative",
                  f"{_f(fee.min(), 4)} .. {_f(fee.max(), 4)} USD per lot")
        capped = int(out["fee_capped"].fillna(False).sum())
        rep.add(INFO, "premium cap engagement",
                f"{capped}/{len(out)} rows hit the premium cap - "
                "expected on cheap far-OTM strikes")

    # --- columns the pages read ---------------------------------------
    needed = ["iv", "delta", "gamma", "theta", "vega", "premium_lot_usd",
              "theta_lot_usd", "fee_rt_usd_lot", "total_cost_pct",
              "net_theta_pct_day", "moneyness_pct", "quote_age_sec"]
    absent = [c for c in needed if c not in out.columns]
    rep.check(not absent, "every column the pages render is present",
              fail_detail=f"missing: {absent}")

    all_nan = [c for c in needed if c in out.columns and out[c].isna().all()]
    rep.check(not all_nan, "no rendered column is entirely empty",
              fail_detail=f"all-NaN columns: {all_nan}")

    return out


# --------------------------------------------------------------------------
# 5. Model-free parity on live quotes
# --------------------------------------------------------------------------

def check_parity(rep: Report, out: pd.DataFrame, spot: float,
                 underlying: str) -> None:
    rep.section("5. Put-call parity on live quotes")

    quoted = out[out["mid"].notna()]
    calls = quoted[quoted["is_call"]][["strike", "mid", "t_years"]]
    puts = quoted[~quoted["is_call"]][["strike", "mid"]]
    pairs = calls.merge(puts, on="strike", suffixes=("_c", "_p")).dropna()

    if pairs.empty:
        rep.add(WARN, "no two-sided call/put pair to test parity on")
        return

    # C - P = S - K at r = 0. Deviations are real (fees, funding, stale
    # quotes), so this is a magnitude check, not an equality check.
    dev = ((pairs["mid_c"] - pairs["mid_p"]) - (spot - pairs["strike"])).abs()
    dev_pct = dev / spot * 100.0

    rep.add(INFO, f"parity deviation over {len(pairs)} strikes",
            f"median {_f(dev_pct.median(), 3)}% of spot   "
            f"p90 {_f(dev_pct.quantile(0.9), 3)}%   "
            f"max {_f(dev_pct.max(), 3)}%")
    rep.check(float(dev_pct.median()) < 1.0,
              "parity holds to within 1% of spot at the median",
              f"median deviation {_f(dev_pct.median(), 3)}% - a large number "
              "here means quotes, spot or units disagree", soft=True)


# --------------------------------------------------------------------------
# 6. Volatility index
# --------------------------------------------------------------------------

def check_volatility(rep: Report, products: pd.DataFrame,
                     settings: dict) -> None:
    rep.section("6. Volatility index  (VIX-style, 30-day constant maturity)")

    now = datetime.now(UTC)
    vol = ui.load_volatility_index(products, settings, now)

    per = vol.get("per_expiry") or []
    if not per:
        rep.add(FAIL, "no expiry produced a variance")
        return

    for e in per:
        cov = e.get("coverage") or {}
        sigma2 = e.get("sigma2")
        vol_pct = (math.sqrt(sigma2) * 100.0
                   if sigma2 is not None and not math.isnan(sigma2) and sigma2 >= 0
                   else float("nan"))
        detail = (f"vol {_f(vol_pct, 2)}%   "
                  f"strikes {e.get('strikes_used')}   "
                  f"forward {_f(e.get('forward'), 0)}   "
                  f"coverage -{_f(cov.get('low_pct'), 0)}% / "
                  f"+{_f(cov.get('high_pct'), 0)}%")
        if e.get("reason"):
            detail += f"   REJECTED: {e['reason']}"
        rep.add(INFO, f"{e.get('label')}  {_f(e.get('days'), 2)}d", detail)

    usable = [e for e in per
              if e.get("sigma2") is not None and not math.isnan(e["sigma2"])]
    rep.check(bool(usable), "at least one expiry yields a valid variance",
              f"{len(usable)}/{len(per)} usable")

    value = vol.get("value")
    if value is None or (isinstance(value, float) and math.isnan(value)):
        rep.add(WARN, "no index value",
                f"reason: {vol.get('note') or 'not stated'}")
    else:
        rep.check(0.0 < float(value) < 500.0,
                  "index value is in a plausible range",
                  f"{underlying_label(settings)} vol index = {_f(value, 2)}")

    if vol.get("constant_maturity"):
        rep.add(INFO, "constant maturity",
                "30 days is bracketed by two expiries - the reading is "
                "comparable across days")
    else:
        rep.add(WARN, "not a 30-day reading",
                f"basis is {_f(vol.get('basis_days'), 1)} days. "
                f"{vol.get('note') or ''}")

    # A narrow chain understates the index. The app already says so on screen;
    # this confirms the same judgement fires against the real chain.
    thin = [e for e in per if (e.get("coverage") or {}).get("narrow_side")]
    if thin:
        sides = ", ".join(f"{e.get('label')}:{e['coverage']['narrow_side']}"
                          for e in thin)
        rep.add(WARN, f"{len(thin)} expiry(ies) flagged narrow",
                f"{sides} - the index reads LOW on these. A limit of the "
                "chain's strike range, not a bug.")


def underlying_label(settings: dict) -> str:
    return str(settings.get("underlying", "?"))


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--underlying", default="BTC",
                    help="underlying to check (default: BTC)")
    ap.add_argument("--all-expiries", action="store_true",
                    help="check every live expiry, not just the nearest")
    ap.add_argument("--json", metavar="PATH",
                    help="also write the full report as JSON")
    args = ap.parse_args()

    rep = Report()
    print(f"MMC live-data check   {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC")
    print(f"endpoint: {api.BASE_URL}   (public market data, no credential)")

    try:
        products = check_products(rep)
    except api.DeltaApiError as exc:
        print(f"\n[{_MARK[FAIL]}] could not reach Delta: {exc}")
        return 1

    underlying = args.underlying.upper()
    expiries = api.list_expiries(products, underlying)
    if not expiries:
        rep.add(FAIL, f"no live expiry for {underlying}")
        return 1

    settings = settings_for(underlying)
    settings["expiries"] = expiries  # load_volatility_index picks from these
    targets = expiries if args.all_expiries else expiries[:1]

    for expiry in targets:
        df, spot, cv = check_chain(rep, products, underlying, expiry)
        if df.empty or not spot > 0:
            continue
        calib = check_calibration(rep, df, spot, cv, settings)
        out = check_derived(rep, df, spot, cv, settings, calib)
        if not out.empty:
            check_parity(rep, out, spot, underlying)

    try:
        check_volatility(rep, products, settings)
    except Exception as exc:
        rep.add(FAIL, "volatility index raised", f"{type(exc).__name__}: {exc}")

    c = rep.counts()
    print(f"\n{'=' * 74}")
    print(f"{c[PASS]} passed   {c[WARN]} warnings   {c[FAIL]} failed")
    print("=" * 74)

    if args.json:
        Path(args.json).write_text(
            json.dumps({"generated_utc": datetime.now(UTC).isoformat(),
                        "underlying": underlying,
                        "counts": c, "rows": rep.rows}, indent=2),
            encoding="utf-8")
        print(f"JSON report written to {args.json}")

    if c[FAIL]:
        print("\nSomething the code assumes about Delta's data is not holding.")
        print("Paste this output back and it can be chased down.")
    return 1 if c[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
