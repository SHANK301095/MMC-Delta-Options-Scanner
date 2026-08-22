"""
MMC Delta Scanner - Options Math Engine
=======================================
Pure-python Black-Scholes for European options (Delta Exchange options are European).

WHY r = 0 by default:
    Delta Exchange India options are USD-quoted / USDT-settled crypto options.
    The market convention (and Delta's own pricing) uses a ~0 risk-free rate.
    The risk-free rate is still exposed as an input so it can be tuned later.

UNITS CONTRACT (very important - every bug in an options tool starts here):
    S      = spot price of underlying, in USD          (e.g. 112500.0)
    K      = strike price, in USD                      (e.g. 115000.0)
    T      = time to expiry in YEARS (fraction)        (e.g. 0.00274 = 1 day)
    sigma  = implied volatility as a DECIMAL           (0.55 = 55%, NOT 55)
    output = option price in USD per 1 unit of underlying (per 1 BTC / per 1 ETH)

    To get "per lot" values, multiply by contract_value
    (Delta: BTC options contract_value = 0.001 BTC, ETH options = 0.01 ETH).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0
SECONDS_PER_DAY = 24.0 * 60.0 * 60.0

# Below this time-to-expiry we treat the option as expired (avoids div-by-zero).
MIN_T_YEARS = 1e-9

# Below this vol we treat the option as deterministic (intrinsic only).
MIN_SIGMA = 1e-6


# --------------------------------------------------------------------------
# Normal distribution helpers (no scipy dependency on purpose - fewer installs)
# --------------------------------------------------------------------------

def norm_cdf(x: float) -> float:
    """Standard normal CDF via erf. Accurate to ~1e-15."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------

def seconds_to_expiry(now_utc: datetime, expiry_utc: datetime) -> float:
    """Seconds remaining. Never negative."""
    if expiry_utc is None or now_utc is None:
        return 0.0
    delta = (expiry_utc - now_utc).total_seconds()
    return max(0.0, delta)


def years_to_expiry(now_utc: datetime, expiry_utc: datetime) -> float:
    """Time to expiry in years. Uses exact seconds, NOT whole days.

    This matters enormously on expiry day: an option with 3 hours left
    has T = 0.000342, not T = 1/365 = 0.00274. Using whole days would
    overstate remaining premium by ~8x on the last day.
    """
    return seconds_to_expiry(now_utc, expiry_utc) / SECONDS_PER_YEAR


def utc_now() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Black-Scholes core
# --------------------------------------------------------------------------

def _d1_d2(S: float, K: float, T: float, sigma: float, r: float):
    """Returns (d1, d2). Caller must guarantee T > 0 and sigma > 0."""
    vol_sqrt_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def _intrinsic(S: float, K: float, is_call: bool) -> float:
    return max(0.0, S - K) if is_call else max(0.0, K - S)


def bs_price(S: float, K: float, T: float, sigma: float,
             is_call: bool, r: float = 0.0) -> float:
    """Black-Scholes price, USD per 1 unit of underlying.

    Degenerate inputs fall back to intrinsic value rather than raising,
    because a live options chain WILL contain zero-bid / expired / bad-IV rows
    and the scanner must not crash on them.
    """
    if S is None or K is None or S <= 0.0 or K <= 0.0:
        return float("nan")
    if T is None or T <= MIN_T_YEARS:
        return _intrinsic(S, K, is_call)
    if sigma is None or sigma <= MIN_SIGMA:
        return _intrinsic(S, K, is_call)

    try:
        d1, d2 = _d1_d2(S, K, T, sigma, r)
    except (ValueError, ZeroDivisionError):
        return _intrinsic(S, K, is_call)

    disc = math.exp(-r * T)
    if is_call:
        return S * norm_cdf(d1) - K * disc * norm_cdf(d2)
    return K * disc * norm_cdf(-d2) - S * norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, sigma: float,
              is_call: bool, r: float = 0.0) -> dict:
    """All greeks, per 1 unit of underlying.

    theta  -> USD per DAY (already divided by 365, so it is directly readable)
    vega   -> USD per 1 vol POINT (i.e. per 1%, already divided by 100)
    gamma  -> delta change per 1 USD move in spot
    delta  -> 0..1 for calls, -1..0 for puts
    """
    nan_pack = {"delta": float("nan"), "gamma": float("nan"),
                "theta": float("nan"), "vega": float("nan"), "rho": float("nan")}

    if S is None or K is None or S <= 0.0 or K <= 0.0:
        return dict(nan_pack)
    if T is None or T <= MIN_T_YEARS or sigma is None or sigma <= MIN_SIGMA:
        # At expiry greeks collapse: delta is a step function, rest are 0.
        if is_call:
            d = 1.0 if S > K else 0.0
        else:
            d = -1.0 if S < K else 0.0
        return {"delta": d, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    try:
        d1, d2 = _d1_d2(S, K, T, sigma, r)
    except (ValueError, ZeroDivisionError):
        return dict(nan_pack)

    sqrt_t = math.sqrt(T)
    disc = math.exp(-r * T)
    pdf_d1 = norm_pdf(d1)

    gamma = pdf_d1 / (S * sigma * sqrt_t)
    vega_per_point = S * pdf_d1 * sqrt_t / 100.0

    if is_call:
        delta = norm_cdf(d1)
        theta_year = (-(S * pdf_d1 * sigma) / (2.0 * sqrt_t)
                      - r * K * disc * norm_cdf(d2))
        rho = K * T * disc * norm_cdf(d2) / 100.0
    else:
        delta = norm_cdf(d1) - 1.0
        theta_year = (-(S * pdf_d1 * sigma) / (2.0 * sqrt_t)
                      + r * K * disc * norm_cdf(-d2))
        rho = -K * T * disc * norm_cdf(-d2) / 100.0

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta_year / 365.0,   # USD per calendar day
        "vega": vega_per_point,        # USD per 1 vol point
        "rho": rho,
    }


def bs_theta_per_day(S: float, K: float, T: float, sigma: float,
                     is_call: bool, r: float = 0.0) -> float:
    """Convenience wrapper - analytic theta in USD/day per unit underlying."""
    return bs_greeks(S, K, T, sigma, is_call, r)["theta"]


# --------------------------------------------------------------------------
# Realised (repricing) decay - the honest way to answer "kitna theta jalega"
# --------------------------------------------------------------------------

def decay_between(S: float, K: float, sigma: float, is_call: bool,
                  t_start_years: float, t_end_years: float,
                  r: float = 0.0) -> float:
    """Premium lost between two points in time, holding spot and IV constant.

    Analytic theta is an INSTANTANEOUS derivative. Over a full day - and
    especially on expiry day - it materially overstates or understates the
    real burn because theta itself accelerates as T shrinks.

    This function instead reprices the option at both timestamps and returns
    the difference. Positive result = premium lost (good for a seller).
    """
    if t_start_years is None or t_end_years is None:
        return float("nan")
    t_start = max(0.0, t_start_years)
    t_end = max(0.0, min(t_end_years, t_start))  # end must be <= start

    p_start = bs_price(S, K, t_start, sigma, is_call, r)
    p_end = bs_price(S, K, t_end, sigma, is_call, r)
    if any(math.isnan(x) for x in (p_start, p_end)):
        return float("nan")
    return p_start - p_end


def decay_schedule(S: float, K: float, sigma: float, is_call: bool,
                   t_now_years: float, step_seconds: float = 3600.0,
                   max_steps: int = 400, r: float = 0.0) -> list:
    """Hourly (default) decay ladder from now until expiry.

    Returns a list of dicts:
        seconds_ahead, t_years, price, cum_decay, step_decay

    Capped at max_steps so a 6-month expiry does not generate 4000 rows.
    When the expiry is far away the step is auto-widened instead of truncated,
    so the curve always spans the full life of the option.
    """
    out = []
    if t_now_years is None or t_now_years <= 0.0:
        return out

    total_seconds = t_now_years * SECONDS_PER_YEAR
    step = float(step_seconds)
    if total_seconds / step > max_steps:
        step = total_seconds / max_steps

    price_now = bs_price(S, K, t_now_years, sigma, is_call, r)
    if math.isnan(price_now):
        return out

    elapsed = 0.0
    prev_price = price_now
    while elapsed < total_seconds:
        elapsed = min(elapsed + step, total_seconds)
        t_left = max(0.0, t_now_years - elapsed / SECONDS_PER_YEAR)
        price = bs_price(S, K, t_left, sigma, is_call, r)
        out.append({
            "seconds_ahead": elapsed,
            "hours_ahead": elapsed / 3600.0,
            "t_years": t_left,
            "price": price,
            "cum_decay": price_now - price,
            "step_decay": prev_price - price,
        })
        prev_price = price
    return out


# --------------------------------------------------------------------------
# Implied volatility solver (used only as a fallback when the API IV is bad)
# --------------------------------------------------------------------------

def implied_vol(price: float, S: float, K: float, T: float, is_call: bool,
                r: float = 0.0, lo: float = 0.005, hi: float = 10.0,
                tol: float = 1e-6, max_iter: int = 100) -> float:
    """Bisection IV solver. Returns NaN when no solution exists in [lo, hi].

    Bisection (not Newton) on purpose: it cannot diverge on the deep-OTM
    near-expiry rows where vega collapses to ~0, which is exactly where a
    live crypto chain is most polluted.
    """
    if price is None or math.isnan(price) or price <= 0.0:
        return float("nan")
    if T is None or T <= MIN_T_YEARS:
        return float("nan")

    intrinsic = _intrinsic(S, K, is_call)
    if price < intrinsic - 1e-8:
        return float("nan")  # arbitrage / stale quote, not solvable

    f_lo = bs_price(S, K, T, lo, is_call, r) - price
    f_hi = bs_price(S, K, T, hi, is_call, r) - price
    if f_lo > 0 or f_hi < 0:
        return float("nan")  # price outside solvable band

    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        f_mid = bs_price(S, K, T, mid, is_call, r) - price
        if abs(f_mid) < tol or (b - a) < tol:
            return mid
        if f_mid < 0:
            a = mid
        else:
            b = mid
    return 0.5 * (a + b)


# --------------------------------------------------------------------------
# Auto-calibration - the anti-bug layer
# --------------------------------------------------------------------------

def detect_iv_scale(samples: list, r: float = 0.0) -> dict:
    """Figure out whether the API is sending IV as 55.0 (percent) or 0.55 (decimal).

    Method: for each sample take the raw IV, price it BOTH ways, and see which
    interpretation reproduces the exchange's own mark price more closely.
    The winner is decided by MEDIAN relative error across all samples, so a
    couple of junk strikes cannot flip the verdict.

    samples: list of dicts with keys S, K, T, iv_raw, is_call, mark_price
    Returns: {"divisor": 1.0 or 100.0, "err_decimal", "err_percent", "n"}
    """
    err_dec, err_pct = [], []

    for s in samples:
        S, K, T = s.get("S"), s.get("K"), s.get("T")
        iv_raw, mark = s.get("iv_raw"), s.get("mark_price")
        is_call = bool(s.get("is_call"))

        if None in (S, K, T, iv_raw, mark):
            continue
        if T <= MIN_T_YEARS or iv_raw <= 0 or mark is None or mark <= 0:
            continue

        p_dec = bs_price(S, K, T, iv_raw, is_call, r)
        p_pct = bs_price(S, K, T, iv_raw / 100.0, is_call, r)
        if not math.isnan(p_dec):
            err_dec.append(abs(p_dec - mark) / mark)
        if not math.isnan(p_pct):
            err_pct.append(abs(p_pct - mark) / mark)

    def _median(xs):
        if not xs:
            return float("inf")
        xs = sorted(xs)
        n = len(xs)
        return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])

    m_dec, m_pct = _median(err_dec), _median(err_pct)
    divisor = 1.0 if m_dec <= m_pct else 100.0
    return {
        "divisor": divisor,
        "err_decimal": m_dec,
        "err_percent": m_pct,
        "n": max(len(err_dec), len(err_pct)),
    }


def detect_greek_scale(samples: list, contract_value: float,
                       r: float = 0.0) -> dict:
    """Figure out whether API greeks are per-unit-of-underlying or per-lot.

    Method: compute our own Black-Scholes theta for each sample and take the
    median ratio (api_theta / our_theta). A ratio near 1.0 means the API is
    already on the same per-unit basis we use. A ratio near contract_value
    (0.001 for BTC) means the API is quoting per lot.

    Returns: {"basis": "per_unit"|"per_lot"|"unknown", "ratio", "n"}
    """
    ratios = []
    for s in samples:
        S, K, T = s.get("S"), s.get("K"), s.get("T")
        sigma, api_theta = s.get("sigma"), s.get("api_theta")
        is_call = bool(s.get("is_call"))

        if None in (S, K, T, sigma, api_theta):
            continue
        if T <= MIN_T_YEARS or sigma <= MIN_SIGMA or api_theta == 0:
            continue

        ours = bs_theta_per_day(S, K, T, sigma, is_call, r)
        if ours is None or math.isnan(ours) or abs(ours) < 1e-12:
            continue
        ratios.append(api_theta / ours)

    if not ratios:
        return {"basis": "unknown", "ratio": float("nan"), "n": 0}

    ratios.sort()
    n = len(ratios)
    med = ratios[n // 2] if n % 2 else 0.5 * (ratios[n // 2 - 1] + ratios[n // 2])

    cv = contract_value if contract_value and contract_value > 0 else 0.001
    d_unit = abs(med - 1.0)
    d_lot = abs(med - cv)

    if d_unit <= d_lot and d_unit < 0.5:
        basis = "per_unit"
    elif d_lot < d_unit and d_lot < cv * 5:
        basis = "per_lot"
    else:
        basis = "unknown"

    return {"basis": basis, "ratio": med, "n": n}


# --------------------------------------------------------------------------
# Payoff helpers
# --------------------------------------------------------------------------

def find_breakevens(spots, payoff, tol_frac: float = 1e-4) -> list:
    """Spot levels where a payoff curve crosses (or touches) zero.

    A naive "sign change between neighbours" loop reports the same break-even
    several times on exactly the payoffs traders care about:

    1. EXACT ZERO AT A GRID POINT.  If payoff[i] == 0 then both the interval
       ending at i and the interval starting at i register a crossing, so the
       break-even is emitted twice. Straddles hit this constantly because
       their break-evens land on round numbers, which are also grid points.

    2. FLAT SEGMENTS AT ZERO.  A capped structure can sit at zero across a
       whole range of spots; every interval inside it looks like a crossing.

    Both collapse if the curve is classified per POINT rather than per
    interval: a maximal run of zero points is one break-even (reported at the
    middle of the run), and an interpolated crossing is only emitted between
    two adjacent points that are both non-zero and of opposite sign.
    """
    if spots is None or payoff is None:
        return []
    n = min(len(spots), len(payoff))
    if n < 2:
        return []

    ys = [float(y) for y in payoff[:n]]
    xs = [float(x) for x in spots[:n]]

    finite = [abs(y) for y in ys if not math.isnan(y)]
    if not finite:
        return []

    # Scale-aware zero test: a payoff built from floating-point arithmetic
    # lands on -1e-13 rather than exactly 0.0 far more often than on 0.0.
    scale = max(finite)
    zero_eps = scale * 1e-9 if scale > 0 else 1e-12

    def _is_zero(y: float) -> bool:
        return not math.isnan(y) and abs(y) <= zero_eps

    raw = []

    # (a) Maximal runs of zero points -> one break-even each.
    i = 0
    while i < n:
        if _is_zero(ys[i]):
            j = i
            while j + 1 < n and _is_zero(ys[j + 1]):
                j += 1
            raw.append(0.5 * (xs[i] + xs[j]))
            i = j + 1
        else:
            i += 1

    # (b) Sign flips between two adjacent NON-zero points -> interpolate.
    for k in range(n - 1):
        y0, y1 = ys[k], ys[k + 1]
        if math.isnan(y0) or math.isnan(y1):
            continue
        if _is_zero(y0) or _is_zero(y1):
            continue  # already covered by the zero-run pass above
        if (y0 < 0.0) == (y1 < 0.0):
            continue
        raw.append(xs[k] + (0.0 - y0) / (y1 - y0) * (xs[k + 1] - xs[k]))

    # Final dedupe guards against a run midpoint and an interpolated crossing
    # landing on effectively the same spot.
    span = xs[n - 1] - xs[0]
    tol = abs(span) * tol_frac if span else 1e-9

    out = []
    for b in sorted(raw):
        if not out or abs(b - out[-1]) > tol:
            out.append(b)
    return out


def payoff_tail_risk(payoff, edge_frac: float = 0.01) -> dict:
    """Kya payoff plotted range ke bahar unbounded hai?

    Returns {"unlimited_profit": bool, "unlimited_loss": bool}.

    The trap this exists to avoid: "spot goes DOWN" is not the same question as
    "the position LOSES money". A short straddle loses without limit on BOTH
    edges; a long straddle profits without limit on both. Testing only the left
    edge, and calling whatever it finds there "downside risk", labels those two
    positions the exact wrong way round — and understating a short straddle's
    max loss is the single most dangerous number this tool could print.

    So each edge is judged by the DIRECTION the payoff is heading as it runs
    off-screen, and profit/loss are decided separately:

        payoff still rising at either edge  -> profit is unbounded
        payoff still falling at either edge -> loss is unbounded

    A capped structure (iron condor, vertical spread) is flat at both edges and
    correctly reports neither.
    """
    out = {"unlimited_profit": False, "unlimited_loss": False}
    if payoff is None:
        return out

    ys = [float(y) for y in payoff if not math.isnan(float(y))]
    n = len(ys)
    if n < 3:
        return out

    step = max(1, int(n * edge_frac))
    if step >= n:
        return out

    # Absolute epsilon alone is meaningless on rupee payoffs that can run into
    # lakhs, so the flat-edge test scales with the size of the payoff itself.
    scale = max(abs(y) for y in ys)
    tol = max(1e-9, scale * 1e-9)

    left_trend = ys[0] - ys[step]            # spot ghatne par P&L kis taraf ja raha hai
    right_trend = ys[-1] - ys[-1 - step]     # spot badhne par P&L kis taraf ja raha hai

    out["unlimited_profit"] = left_trend > tol or right_trend > tol
    out["unlimited_loss"] = left_trend < -tol or right_trend < -tol
    return out
