"""
MMC Delta Scanner - Volatility Index (VIX-style)
================================================
A single number for the whole market's volatility - the same idea as India VIX
or CBOE VIX.

WHY THIS IS NOT "ATM IV"
------------------------
ATM IV is one strike's number. If that strike is stale, or the skew is steep,
it misrepresents the market. The VIX method weights the entire OTM chain -
every strike contributes, wings included. That is why it is a better answer to
"how frightened is the market".

METHOD - CBOE's model-free variance formula
-------------------------------------------
For a single expiry:

    sigma^2 = (2/T) * SUM_i [ dK_i / K_i^2 * e^(rT) * Q(K_i) ]  -  (1/T) * (F/K0 - 1)^2

    T    = time to expiry, in years
    F    = forward level = K* + e^(rT) * (C(K*) - P(K*)), where K* is the strike
           at which |C - P| is smallest
    K0   = the first strike at or below F
    Q(K) = the bid-ask midpoint of that strike's OTM option
           (K < K0 -> put, K > K0 -> call, K = K0 -> the average of both)
    dK_i = (K_{i+1} - K_{i-1}) / 2

There is no volatility model in this - no Black-Scholes, no smile fit. Only the
payoff structure and quoted prices. That is what makes the number trustworthy.

Two expiries are then interpolated to exactly 30 days, so each day's number is
comparable with the next. Without constant maturity, "the index is 60 today"
means nothing, because tomorrow that expiry will be a day closer.

ZERO-BID RULE
-------------
CBOE excludes zero-bid options, and stops a side's summation after TWO
consecutive zero-bid strikes walking outward from K0. This rule is the most
important part of the formula: the 1/K^2 weight is small in the deep wings, but
a junk quote on a dead strike can still inflate the variance. On Delta India's
chain the wings are frequently dead.
"""

from __future__ import annotations

import math

SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0
SECONDS_PER_DAY = 24.0 * 60.0 * 60.0

TARGET_DAYS = 30.0

# Below this the discrete sum does not represent the distribution and the
# number stops being trustworthy.
MIN_STRIKES = 3

# The strike coverage needed around the forward; below it the number comes out
# QUIETLY LOW. Even with a correct formula, a narrow chain truncates the tail of
# the integral, and that bias grows with maturity. Measured on a 55% vol chain:
#
#     coverage   1-day   7-day   30-day   90-day
#     +-15%       57.2    54.9     50.4     43.5
#     +-25%       57.2    55.3     54.2     50.4
#     +-50%       57.2    55.3     55.1     54.5
#     wide        57.2    55.3     55.1     55.0
#
# At 30 days +-25% is enough (1.5% low); +-15% is not (8% low). So the index
# always reports its coverage alongside - showing the bias beats hiding it.
MIN_COVERAGE_PCT = 25.0


def _mid(quote: dict) -> float:
    """The bid-ask midpoint, or NaN if the book is not two-sided."""
    bid = quote.get("bid", float("nan"))
    ask = quote.get("ask", float("nan"))
    if any(v is None or (isinstance(v, float) and math.isnan(v))
           for v in (bid, ask)):
        return float("nan")
    if bid <= 0 or ask <= 0 or ask < bid:
        return float("nan")
    return 0.5 * (bid + ask)


def _has_bid(quote: dict) -> bool:
    bid = quote.get("bid", float("nan"))
    if bid is None or (isinstance(bid, float) and math.isnan(bid)):
        return False
    return bid > 0


def forward_level(calls: dict, puts: dict, t_years: float,
                  r: float = 0.0) -> dict:
    """The forward index level F and the first strike at or below it, K0.

    F is derived where the call and put prices are closest, because that is the
    strike at which put-call parity can be read with the least noise. Using
    spot would be wrong: an option's reference is the forward, not spot.
    """
    shared = sorted(k for k in set(calls) & set(puts)
                    if not math.isnan(_mid(calls[k]))
                    and not math.isnan(_mid(puts[k])))
    if not shared:
        return {"forward": float("nan"), "k0": float("nan"), "k_star": float("nan")}

    k_star = min(shared, key=lambda k: abs(_mid(calls[k]) - _mid(puts[k])))
    parity_gap = _mid(calls[k_star]) - _mid(puts[k_star])
    forward = k_star + math.exp(r * t_years) * parity_gap

    every_strike = sorted(set(calls) | set(puts))
    at_or_below = [k for k in every_strike if k <= forward]
    k0 = max(at_or_below) if at_or_below else min(every_strike)

    return {"forward": forward, "k0": k0, "k_star": k_star}


def _walk_with_zero_bid_stop(strikes, quotes, ascending: bool) -> list:
    """Select strikes walking outward from K0, stopping at two consecutive
    zero bids.

    A single zero-bid strike is simply skipped; two in a row mean the book has
    ended on that side, and every quote beyond it is noise.
    """
    ordered = sorted(strikes) if ascending else sorted(strikes, reverse=True)
    picked = []
    consecutive_empty = 0

    for k in ordered:
        quote = quotes.get(k)
        if quote is None or not _has_bid(quote) or math.isnan(_mid(quote)):
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            continue
        consecutive_empty = 0
        picked.append(k)

    return picked


def expiry_variance(calls: dict, puts: dict, t_years: float,
                    r: float = 0.0) -> dict:
    """Model-free sigma^2 for one expiry.

    calls / puts : {strike: {"bid": float, "ask": float}}
    Returns {"sigma2", "forward", "k0", "strikes_used", "reason"}.
    A reason of None means the number is trustworthy.
    """
    fail = {"sigma2": float("nan"), "forward": float("nan"), "k0": float("nan"),
            "strikes_used": 0}

    if t_years is None or t_years <= 0:
        return {**fail, "reason": "this expiry has already passed"}
    if not calls or not puts:
        return {**fail, "reason": "the call or put side is empty"}

    fwd = forward_level(calls, puts, t_years, r)
    forward, k0 = fwd["forward"], fwd["k0"]
    if math.isnan(forward) or math.isnan(k0):
        return {**fail, "reason": "could not resolve the forward (no two-sided book)"}

    # Puts below K0, calls above - the zero-bid rule applies on both sides.
    put_strikes = _walk_with_zero_bid_stop(
        [k for k in puts if k < k0], puts, ascending=False)
    call_strikes = _walk_with_zero_bid_stop(
        [k for k in calls if k > k0], calls, ascending=True)

    contributions = {}
    for k in put_strikes:
        contributions[k] = _mid(puts[k])
    for k in call_strikes:
        contributions[k] = _mid(calls[k])

    # At K0 both are closest to at-the-money, so take their average.
    at_k0 = [_mid(side[k0]) for side in (calls, puts)
             if k0 in side and not math.isnan(_mid(side[k0]))]
    if at_k0:
        contributions[k0] = sum(at_k0) / len(at_k0)

    strikes = sorted(contributions)
    if len(strikes) < MIN_STRIKES:
        return {**fail, "forward": forward, "k0": k0,
                "reason": f"only {len(strikes)} usable strikes "
                          f"(at least {MIN_STRIKES} are needed)"}

    discount = math.exp(r * t_years)
    total = 0.0
    for i, k in enumerate(strikes):
        if i == 0:
            d_k = strikes[1] - strikes[0]
        elif i == len(strikes) - 1:
            d_k = strikes[-1] - strikes[-2]
        else:
            d_k = 0.5 * (strikes[i + 1] - strikes[i - 1])
        total += (d_k / (k * k)) * discount * contributions[k]

    sigma2 = (2.0 / t_years) * total - (1.0 / t_years) * (forward / k0 - 1.0) ** 2

    if sigma2 <= 0 or math.isnan(sigma2):
        return {**fail, "forward": forward, "k0": k0,
                "reason": "variance came out negative - the chain's quotes "
                          "are inconsistent with each other"}

    return {"sigma2": sigma2, "forward": forward, "k0": k0,
            "strikes_used": len(strikes),
            "k_min": strikes[0], "k_max": strikes[-1],
            "coverage": coverage(strikes[0], strikes[-1], forward),
            "reason": None}


def coverage(k_min: float, k_max: float, forward: float) -> dict:
    """How far the summation reached on either side of the forward.

    Returns {"low_pct", "high_pct", "narrow_side"}.
    low_pct / high_pct are always positive distances, in percent.
    narrow_side is None when both sides have enough coverage.

    This belongs beside the index. A narrow chain makes the index read low, and
    for a regime gate that is directly dangerous: a low reading gets taken as
    "volatility is cheap" when the real cause was a small chain.
    """
    if any(v is None or (isinstance(v, float) and math.isnan(v))
           for v in (k_min, k_max, forward)) or forward <= 0:
        return {"low_pct": float("nan"), "high_pct": float("nan"),
                "narrow_side": "unknown"}

    low_pct = max(0.0, (forward - k_min) / forward * 100.0)
    high_pct = max(0.0, (k_max - forward) / forward * 100.0)

    if low_pct < MIN_COVERAGE_PCT and high_pct < MIN_COVERAGE_PCT:
        narrow = "both"
    elif low_pct < MIN_COVERAGE_PCT:
        narrow = "down"
    elif high_pct < MIN_COVERAGE_PCT:
        narrow = "up"
    else:
        narrow = None

    return {"low_pct": low_pct, "high_pct": high_pct, "narrow_side": narrow}


def interpolate_to_target(near: dict, far: dict,
                          target_days: float = TARGET_DAYS) -> float:
    """Bring two expiries' variance to a constant maturity.

    near / far : {"t_years", "sigma2"}

    The interpolation runs on TOTAL VARIANCE (T * sigma^2), not on sigma.
    Variance adds across time; volatility does not - interpolating sigma
    directly is a classic and quietly wrong shortcut.
    """
    t1, t2 = float(near["t_years"]), float(far["t_years"])
    v1, v2 = float(near["sigma2"]), float(far["sigma2"])
    t_target = target_days / 365.0

    if t2 <= t1:
        return math.sqrt(v1)

    w_near = (t2 - t_target) / (t2 - t1)
    w_far = (t_target - t1) / (t2 - t1)

    total_var_at_target = t1 * v1 * w_near + t2 * v2 * w_far
    if total_var_at_target <= 0:
        return float("nan")

    return math.sqrt(total_var_at_target / t_target)


def volatility_index(expiries: list, target_days: float = TARGET_DAYS) -> dict:
    """The full index - one number from a list of expiries.

    expiries : [{"t_years", "sigma2", "label"}] - only those with a valid sigma2

    Returns:
        value             - the index, in percent (e.g. 62.4)
        constant_maturity - True only when two expiries bracket 30 days
        basis_days        - the maturity the number actually represents
        near / far        - which expiries were used
        note              - why constant maturity was not achieved, if it wasn't

    When 30 days is not bracketed we do NOT extrapolate. Building a 30-day
    volatility from expiries on one side only produces a number that looks
    confident but is not - and this page exists to be traded from. In that case
    the maturity that genuinely exists is reported, clearly labelled.
    """
    usable = [e for e in expiries
              if e.get("sigma2") is not None
              and not math.isnan(e["sigma2"]) and e["sigma2"] > 0
              and e.get("t_years", 0) > 0]

    if not usable:
        return {"value": float("nan"), "constant_maturity": False,
                "basis_days": float("nan"), "near": None, "far": None,
                "note": "no expiry produced a valid variance"}

    usable.sort(key=lambda e: e["t_years"])
    t_target = target_days / 365.0

    below = [e for e in usable if e["t_years"] <= t_target]
    above = [e for e in usable if e["t_years"] > t_target]

    if below and above:
        near, far = below[-1], above[0]
        return {
            "value": interpolate_to_target(near, far, target_days) * 100.0,
            "constant_maturity": True,
            "basis_days": target_days,
            "near": near, "far": far, "note": None,
        }

    # No bracket - report what exists rather than extrapolating.
    pick = min(usable, key=lambda e: abs(e["t_years"] - t_target))
    days = pick["t_years"] * 365.0
    side = ("every expiry is shorter than 30 days" if not above
            else "every expiry is longer than 30 days")
    return {
        "value": math.sqrt(pick["sigma2"]) * 100.0,
        "constant_maturity": False,
        "basis_days": days,
        "near": pick, "far": None,
        "note": (f"{side}, so this is {days:.1f}-day volatility, not "
                 f"{target_days:.0f}-day. Do not compare it directly with "
                 "another day's reading."),
    }


def regime_status(value: float, band: tuple) -> dict:
    """Whether the current index sits inside the band.

    Returns {"in_regime": bool, "position": "below"|"inside"|"above"|"unknown",
             "distance": float}
    """
    if value is None or math.isnan(value) or band is None:
        return {"in_regime": False, "position": "unknown", "distance": float("nan")}

    lo, hi = float(band[0]), float(band[1])
    if lo > hi:
        lo, hi = hi, lo

    if value < lo:
        return {"in_regime": False, "position": "below", "distance": lo - value}
    if value > hi:
        return {"in_regime": False, "position": "above", "distance": value - hi}
    return {"in_regime": True, "position": "inside", "distance": 0.0}
