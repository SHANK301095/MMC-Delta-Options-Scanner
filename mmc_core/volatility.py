"""
MMC Delta Scanner — Volatility Index (VIX-style)
================================================
Poore market ki volatility ka ek number — waise hi jaise India VIX ya CBOE VIX.

WHY THIS IS NOT "ATM IV"
------------------------
ATM IV ek strike ka number hai. Agar wo ek strike stale ho, ya skew tedhi ho,
to wo poore market ko galat represent karta hai. VIX poori OTM chain ko weight
karta hai — har strike apna hissa daalta hai, aur wings ka bhi. Isi liye wo
"market kitna dara hua hai" ka behtar jawab hai.

METHOD — CBOE ki model-free variance formula
--------------------------------------------
Kisi ek expiry ke liye:

    sigma^2 = (2/T) * SUM_i [ dK_i / K_i^2 * e^(rT) * Q(K_i) ]  -  (1/T) * (F/K0 - 1)^2

    T    = time to expiry, years
    F    = forward level = K* + e^(rT) * (C(K*) - P(K*)), jahan K* wo strike hai
           jahan |C - P| sabse chhota hai
    K0   = F se neeche (ya barabar) ka pehla strike
    Q(K) = us strike ke OTM option ka bid-ask midpoint
           (K < K0 -> put, K > K0 -> call, K = K0 -> dono ka average)
    dK_i = (K_{i+1} - K_{i-1}) / 2

Ismein koi volatility model nahi hai — na Black-Scholes, na koi smile fit.
Sirf payoff structure aur quoted prices. Isi liye ye number bharosemand hai.

Phir do expiries ke beech interpolate karke exactly 30 din nikaala jaata hai,
taaki har roz ka number ek doosre se comparable rahe. Bina constant maturity ke
"aaj VIX 60 hai" ka koi matlab nahi banta, kyunki kal expiry ek din paas aa
chuki hogi.

ZERO-BID RULE
-------------
CBOE zero-bid options ko chhod deta hai, aur K0 se bahar ki taraf chalte hue
DO lagataar zero-bid strikes milne par us taraf ka summation rok deta hai.
Ye niyam is formula ka sabse zaroori hissa hai: 1/K^2 weight deep wings par
chhota hota hai, lekin ek dead strike ka junk quote phir bhi variance ko
uchaal sakta hai. Delta India ki chain par wings aksar dead hi hoti hain.
"""

from __future__ import annotations

import math

SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0
SECONDS_PER_DAY = 24.0 * 60.0 * 60.0

TARGET_DAYS = 30.0

# Isse kam strikes par discrete sum poori distribution ko represent nahi karta
# aur number bharosemand nahi rehta.
MIN_STRIKES = 3

# Forward ke around itni strike coverage chahiye, warna number chup-chaap KAM
# aata hai. Formula sahi hone par bhi tang chain integral ka tail kaat deti hai,
# aur ye bias maturity ke saath badhti hai. Ek 55% vol chain par maapa gaya:
#
#     coverage   1-din   7-din   30-din   90-din
#     +-15%       57.2    54.9     50.4     43.5
#     +-25%       57.2    55.3     54.2     50.4
#     +-50%       57.2    55.3     55.1     54.5
#     wide        57.2    55.3     55.1     55.0
#
# 30 din par +-25% kaafi hai (1.5% kam), +-15% nahi (8% kam). Isliye index
# hamesha apni coverage ke saath report hota hai — bias ko chupane se behtar
# hai use dikha dena.
MIN_COVERAGE_PCT = 25.0


def _mid(quote: dict) -> float:
    """Bid-ask midpoint, ya NaN agar book two-sided nahi hai."""
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
    """Forward index level F aur uske neeche ka pehla strike K0.

    F wahan se nikaalte hain jahan call aur put ki keemat sabse kareeb hai —
    kyunki wahi wo strike hai jahan put-call parity sabse kam noise ke saath
    padhi ja sakti hai. Spot use karne se ye galat ho jaata: options ka
    reference forward hota hai, spot nahi.
    """
    shared = sorted(k for k in set(calls) & set(puts)
                    if not math.isnan(_mid(calls[k]))
                    and not math.isnan(_mid(puts[k])))
    if not shared:
        return {"forward": float("nan"), "k0": float("nan"), "k_star": float("nan")}

    k_star = min(shared, key=lambda k: abs(_mid(calls[k]) - _mid(puts[k])))
    forward = k_star + math.exp(r * t_years) * (_mid(calls[k_star]) - _mid(puts[k_star]))

    every_strike = sorted(set(calls) | set(puts))
    at_or_below = [k for k in every_strike if k <= forward]
    k0 = max(at_or_below) if at_or_below else min(every_strike)

    return {"forward": forward, "k0": k0, "k_star": k_star}


def _walk_with_zero_bid_stop(strikes, quotes, ascending: bool) -> list:
    """K0 se bahar chalte hue strikes chuniye, do lagataar zero-bid par ruk kar.

    Ek akela zero-bid strike sirf skip hota hai; do lagataar ka matlab hai ki
    book us taraf khatam ho chuki hai, aur usse aage ka har quote sirf shor hai.
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
    """Ek expiry ka model-free sigma^2.

    calls / puts : {strike: {"bid": float, "ask": float}}
    Returns {"sigma2", "forward", "k0", "strikes_used", "reason"}.
    reason None hone ka matlab hai number bharosemand hai.
    """
    fail = {"sigma2": float("nan"), "forward": float("nan"), "k0": float("nan"),
            "strikes_used": 0}

    if t_years is None or t_years <= 0:
        return {**fail, "reason": "expiry nikal chuki hai"}
    if not calls or not puts:
        return {**fail, "reason": "call ya put side khaali hai"}

    fwd = forward_level(calls, puts, t_years, r)
    forward, k0 = fwd["forward"], fwd["k0"]
    if math.isnan(forward) or math.isnan(k0):
        return {**fail, "reason": "forward resolve nahi hua (two-sided book nahi mila)"}

    # K0 se neeche puts, upar calls — dono taraf zero-bid rule ke saath.
    put_strikes = _walk_with_zero_bid_stop(
        [k for k in puts if k < k0], puts, ascending=False)
    call_strikes = _walk_with_zero_bid_stop(
        [k for k in calls if k > k0], calls, ascending=True)

    contributions = {}
    for k in put_strikes:
        contributions[k] = _mid(puts[k])
    for k in call_strikes:
        contributions[k] = _mid(calls[k])

    # K0 par dono OTM ke sabse kareeb hain, isliye unka average.
    at_k0 = [_mid(side[k0]) for side in (calls, puts)
             if k0 in side and not math.isnan(_mid(side[k0]))]
    if at_k0:
        contributions[k0] = sum(at_k0) / len(at_k0)

    strikes = sorted(contributions)
    if len(strikes) < MIN_STRIKES:
        return {**fail, "forward": forward, "k0": k0,
                "reason": f"sirf {len(strikes)} usable strikes mile "
                          f"(kam se kam {MIN_STRIKES} chahiye)"}

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
                "reason": "variance negative aa gaya — chain ke quotes "
                          "aapas mein inconsistent hain"}

    return {"sigma2": sigma2, "forward": forward, "k0": k0,
            "strikes_used": len(strikes),
            "k_min": strikes[0], "k_max": strikes[-1],
            "coverage": coverage(strikes[0], strikes[-1], forward),
            "reason": None}


def coverage(k_min: float, k_max: float, forward: float) -> dict:
    """Summation forward ke aas-paas kitni door tak gaya.

    Returns {"low_pct", "high_pct", "narrow_side"}.
    low_pct / high_pct hamesha positive distances hain, percent mein.
    narrow_side None hai jab dono taraf kaafi coverage hai.

    Ye number index ke bagal mein dikhna chahiye. Ek tang chain par index kam
    aata hai, aur regime gate ke liye ye seedha khatarnak hai: kam VIX ka
    matlab hoga "vol saste hain" jabki asal mein chain hi chhoti thi.
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
    """Do expiries ki variance ko constant maturity par le aaiye.

    near / far : {"t_years", "sigma2"}

    Interpolation TOTAL VARIANCE (T * sigma^2) par hoti hai, sigma par nahi.
    Variance time ke saath add hoti hai, volatility nahi — sigma ko seedha
    interpolate karna ek classic aur chup-chaap galat karne wala shortcut hai.
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
    """Poora index — expiries ki list se ek number.

    expiries : [{"t_years", "sigma2", "label"}] — sirf wahi jinka sigma2 valid ho

    Returns:
        value           — index, percent mein (e.g. 62.4)
        constant_maturity — True tabhi jab do expiries ne 30 din ko bracket kiya
        basis_days      — number kis maturity ka hai
        near / far      — kaunsi expiries use hui
        note            — agar constant maturity nahi mili to wajah

    Jab 30 din bracket nahi hota to hum EXTRAPOLATE nahi karte. Sirf ek taraf
    ki expiry se 30-din ki vol banaana ek aisa number deta hai jo confident
    dikhta hai par hai nahi — aur ye page us number par trade karne ke liye hai.
    Us case mein jo maturity sach mein available hai wahi report hoti hai,
    saaf label ke saath.
    """
    usable = [e for e in expiries
              if e.get("sigma2") is not None
              and not math.isnan(e["sigma2"]) and e["sigma2"] > 0
              and e.get("t_years", 0) > 0]

    if not usable:
        return {"value": float("nan"), "constant_maturity": False,
                "basis_days": float("nan"), "near": None, "far": None,
                "note": "kisi bhi expiry se valid variance nahi nikla"}

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

    # Bracket nahi bana — jo hai wahi report kijiye, extrapolate mat kijiye.
    pick = min(usable, key=lambda e: abs(e["t_years"] - t_target))
    days = pick["t_years"] * 365.0
    side = "sab expiries 30 din se kam hain" if not above \
        else "sab expiries 30 din se zyada hain"
    return {
        "value": math.sqrt(pick["sigma2"]) * 100.0,
        "constant_maturity": False,
        "basis_days": days,
        "near": pick, "far": None,
        "note": (f"{side}, isliye ye {days:.1f}-din ki vol hai, "
                 f"{target_days:.0f}-din ki nahi. Doosre dinon ke number se "
                 "seedha compare mat kijiye."),
    }


def regime_status(value: float, band: tuple) -> dict:
    """Current index band ke andar hai ya nahi.

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
