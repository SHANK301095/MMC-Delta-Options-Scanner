"""
MMC Delta Scanner - Delta Exchange India Fee Engine
===================================================
Why this module exists
----------------------
Almost every retail options screener quotes edge in GROSS premium terms.
On Delta India that is actively misleading, because the fee is charged on
NOTIONAL, not on premium.

    notional = lots x contract_value x index_price

For a deep-OTM strike the premium might be $4 while the notional is $100,000.
A naive "0.03% fee" reading gives $0.0012. The real fee is 0.03% of notional
= $30 ... except Delta then caps it at a percentage of the premium.

So the fee is:
    fee = min( notional x rate , premium x cap_pct )
    total = fee x (1 + gst)

That cap is the entire reason cheap OTM options are tradable at all on Delta.
Any scanner that ignores it will rank dead 1-dollar strikes as the best
"theta yield" on the board.

IMPORTANT - VERIFY THESE NUMBERS
--------------------------------
Delta changes its fee schedule from time to time, and published sources
disagree (the premium cap has been quoted at 3.5%, 10% and 12.5% on different
pages). Every value here is a SIDEBAR INPUT with a documented default, not a
hard-coded constant. Confirm against https://www.delta.exchange/fees before
sizing anything real.

Defaults used (Delta India options, as documented at build time):
    maker  0.01%   taker 0.03%   premium cap 3.5%   GST 18%
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Documented defaults - all overridable from the UI.
DEFAULT_MAKER_RATE = 0.0001     # 0.01% of notional
DEFAULT_TAKER_RATE = 0.0003     # 0.03% of notional
DEFAULT_PREMIUM_CAP = 0.035     # fee never exceeds 3.5% of premium
DEFAULT_GST = 0.18              # 18% GST on the fee itself


@dataclass
class FeeConfig:
    """All fee parameters in one object so nothing gets passed positionally."""
    maker_rate: float = DEFAULT_MAKER_RATE
    taker_rate: float = DEFAULT_TAKER_RATE
    premium_cap_pct: float = DEFAULT_PREMIUM_CAP
    gst: float = DEFAULT_GST
    entry_is_maker: bool = True     # limit order in
    exit_is_maker: bool = False     # assume you cross the spread to get out

    def rate(self, is_maker: bool) -> float:
        return self.maker_rate if is_maker else self.taker_rate


def leg_fee_usd(option_price: float, index_price: float, lots: float,
                contract_value: float, cfg: FeeConfig,
                is_maker: bool = False) -> float:
    """Fee in USD for ONE side of ONE leg.

    option_price : premium per unit of underlying (Delta's quoted price)
    index_price  : spot / index price of the underlying
    lots         : number of contracts
    contract_value: 0.001 for BTC options, 0.01 for ETH options
    """
    if any(x is None for x in (option_price, index_price, lots, contract_value)):
        return float("nan")
    if any(isinstance(x, float) and math.isnan(x)
           for x in (option_price, index_price, lots, contract_value)):
        return float("nan")
    if lots <= 0 or contract_value <= 0 or index_price <= 0:
        return 0.0

    notional = lots * contract_value * index_price
    premium = lots * contract_value * max(0.0, option_price)

    raw_fee = notional * cfg.rate(is_maker)
    capped_fee = premium * cfg.premium_cap_pct

    # The cap only binds when it is the SMALLER number.
    fee = min(raw_fee, capped_fee) if premium > 0 else raw_fee
    return fee * (1.0 + cfg.gst)


def round_trip_fee_usd(option_price: float, index_price: float, lots: float,
                       contract_value: float, cfg: FeeConfig,
                       exit_price: float | None = None) -> float:
    """Entry + exit fee in USD.

    exit_price defaults to option_price. For a decay analysis the honest exit
    price is LOWER (the option has decayed), which makes the exit fee smaller
    - so passing it matters.
    """
    entry = leg_fee_usd(option_price, index_price, lots, contract_value,
                        cfg, is_maker=cfg.entry_is_maker)
    exit_px = option_price if exit_price is None else exit_price
    exit_fee = leg_fee_usd(exit_px, index_price, lots, contract_value,
                           cfg, is_maker=cfg.exit_is_maker)
    return entry + exit_fee


def fee_as_pct_of_premium(option_price: float, index_price: float,
                          contract_value: float, cfg: FeeConfig,
                          is_maker: bool = False) -> float:
    """Round-trip fee expressed as a % of the premium. The reality check.

    On a cheap OTM strike this frequently lands at 7%+ round trip, which
    quietly eats most of what a decay scanner calls "yield".
    """
    if option_price is None or (isinstance(option_price, float)
                                and math.isnan(option_price)):
        return float("nan")
    if option_price <= 0:
        return float("nan")

    premium = contract_value * option_price
    if premium <= 0:
        return float("nan")

    fee = (leg_fee_usd(option_price, index_price, 1.0, contract_value,
                       cfg, is_maker=cfg.entry_is_maker)
           + leg_fee_usd(option_price, index_price, 1.0, contract_value,
                         cfg, is_maker=cfg.exit_is_maker))
    return fee / premium * 100.0


def cap_binds(option_price: float, index_price: float, contract_value: float,
              cfg: FeeConfig, is_maker: bool = False) -> bool:
    """True when the premium cap is what you actually pay.

    Useful as a UI badge: on cheap strikes the cap ALWAYS binds, and knowing
    that tells you the fee scales with premium rather than with notional.
    """
    if option_price is None or option_price <= 0:
        return False
    notional = contract_value * index_price
    premium = contract_value * option_price
    return (premium * cfg.premium_cap_pct) < (notional * cfg.rate(is_maker))


def execution_price(mark: float, bid: float, ask: float, is_buy: bool,
                    mode: str = "realistic") -> float:
    """What you would ACTUALLY pay or receive.

    mode:
      "mark"      - Delta's mark price (optimistic; nobody fills at mark)
      "mid"       - midpoint of the book
      "realistic" - buy at the ask, sell at the bid (crossing the spread)

    "realistic" is the default everywhere in this scanner. On a chain where
    quarter of the strikes carry a 20%+ spread, mark-price backtesting of an
    idea is fiction.
    """
    has_book = (bid is not None and ask is not None
                and not (isinstance(bid, float) and math.isnan(bid))
                and not (isinstance(ask, float) and math.isnan(ask))
                and bid > 0 and ask > 0)

    if mode == "mark" or not has_book:
        return mark
    if mode == "mid":
        return 0.5 * (bid + ask)
    return ask if is_buy else bid


def slippage_cost_pct(bid: float, ask: float, mark: float) -> float:
    """Round-trip cost of crossing the spread twice, as a % of mark.

    This is usually 3-10x larger than the exchange fee on Delta India, and
    it is the number most retail screeners never show.
    """
    if any(v is None or (isinstance(v, float) and math.isnan(v))
           for v in (bid, ask, mark)):
        return float("nan")
    if mark <= 0 or bid <= 0 or ask <= 0:
        return float("nan")
    return (ask - bid) / mark * 100.0
