# MMC Delta Options Scanner

A live options scanner for **BTC and ETH on Delta Exchange India**: the option
chain, theta decay, IV skew, a payoff builder, model-free arbitrage checks, a
delta-band filter and a VIX-style volatility regime gate — in one Streamlit app.

**Entirely read-only.** No API key, no secrets, no order-placement code. The app
reads two public endpoints (`/v2/products` and `/v2/tickers`), and CI verifies
that on every push with [`tests/check_read_only.py`](tests/check_read_only.py).

---

## Running it

**Windows:** double-click `RUN_MMC_SCANNER.bat`
**Linux / macOS:** `./run_scanner.sh`

Both create a `.venv`, install dependencies and open
`http://localhost:8501` on first run — two to four minutes the first time, about
ten seconds afterwards.

To run it manually:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

There is nothing to configure. The API needs no credentials, so there are no
secrets to set and no environment file to create.

Full setup instructions, a module-by-module guide and troubleshooting are in
**[README_SETUP.md](README_SETUP.md)**.

---

## Your view lives in the URL

Everything you are looking at — underlying, expiry, price basis, USD/INR rate,
delta band, volatility band — is written into the query string:

```
…/Delta_Filter?u=BTC&e=29-08-2026&p=realistic&fx=88&d=15-25
```

So reloading returns you to the same view, a bookmark works, and sending someone
that link shows them **exactly the same screen**.

This is deliberately better than a server-side settings file. A Streamlit app is
**one process shared by every visitor**, so a setting "saved" on the server
becomes everyone's setting. A URL belongs to a single browser. The file store
therefore runs only when `MMC_LOCAL_SETTINGS=1` is set — which the launcher
scripts do and a cloud deployment does not.

URL params arrive from outside, so every value is validated and a bad one is
dropped silently rather than guessed at: `?u=<script>` simply opens on the
default underlying. A link naming an expiry that has since passed opens on a
current one instead of breaking.

---

## Modules

| Page | What it does |
|---|---|
| 🏠 **Home** | Expiry snapshot, put/call ratio, chain-health badge |
| 📈 **Live Chain** | Calls and puts side by side, liquidity filter, OI profile, cost-of-trading table |
| ⏳ **Theta Decay** | Repricing-based burn ranking, hour-by-hour curve, multi-leg basket |
| 🌊 **IV Skew** | Volatility smile, 25Δ risk reversal and butterfly, term structure |
| 🎯 **Payoff Builder** | Eight preset strategies, executable fills, expiry and T+0 curves |
| 🔎 **Mispricing** | Put-call parity, vertical bounds, butterfly convexity, box spreads |
| 📐 **Delta Filter** | Pick strikes by delta band, with live bid/ask |
| 🌡️ **Vol Regime** | VIX-style index at 30-day constant maturity, plus a regime gate |

---

## Design decisions other screeners get wrong

These are the choices that make the numbers trustworthy. Without them an options
tool does not crash — it quietly reports wrong figures, which is worse.

**1. Fees are charged on notional, not on premium.**
On Delta India, `fee = min(notional × rate, premium × cap) × (1 + GST)`. The
consequence: a round trip costs roughly 8% of premium on a cheap OTM option and
about 1.5% at the money. A scanner that ignores this ranks dead ₹1 strikes as
the "best theta yield". Every table here carries a **net of cost** column.

**2. Nothing fills at the mark price.**
The default price basis is Realistic — the ASK when buying, the BID when
selling. On a chain where a quarter of strikes carry a 20% spread, edge derived
from the mark price exists only on paper.

**3. Theta is an instantaneous derivative, not a day's burn.**
Every burn figure is produced by **repricing** the option at a future timestamp.
On expiry day, analytic theta and the real burn differ by more than 50%.

**4. The volatility index is built from the chain, not from one strike.**
Delta publishes no India-VIX equivalent, and none is needed: a VIX is derived
from the option chain itself. [`mmc_core/volatility.py`](mmc_core/volatility.py)
applies CBOE's model-free variance formula — each OTM strike's quoted midpoint,
a `1/K²` weight, zero-bid truncation — then interpolates **total variance**
between two expiries to reach 30-day constant maturity. Without constant
maturity, today's reading and tomorrow's are not comparable.

The index reports its own **strike coverage**, because a narrow chain biases it
quietly downward (at 90 days, ±15% coverage reads 55% volatility as 43.5%). For
a regime gate, hiding that would be dangerous: a low reading would be taken as
"volatility is cheap" when the real cause was a small chain.

**5. A delta band applies to absolute delta.**
Asking for 25 returns both the 0.25 call and the −0.25 put — that is the market
convention. A contract whose delta is unknown is excluded, because once the
selection is made by delta, "might match" is not an answer.

Time to expiry is always computed in **exact seconds**, never in whole days.
Delta India options settle at 17:30 IST (12:00 UTC), and whole-day rounding
overstates remaining premium roughly eightfold on expiry day.

---

## Design system

The entire look is defined in one place: [`mmc_core/theme.py`](mmc_core/theme.py)
for tokens, CSS and components, and
[`.streamlit/config.toml`](.streamlit/config.toml) for Streamlit's own widgets.
Both use the same hex values, and a test fails if they drift apart.

**Dark is fixed, deliberately.** This is a terminal people read for hours.
Supporting both modes in practice means doing both of them badly.

**Every colour has exactly one job:**

| Job | Token |
|---|---|
| Calls, profit, decay in your favour | `ACCENT_UP` |
| Puts, loss | `ACCENT_DOWN` |
| Analytical series (model curve, payoff) | `SERIES_1`, `SERIES_2` |
| Spot, ATM, thresholds | recessive ink — **no hue** |
| healthy / watch / risky / broken | `STATUS_*`, badges and gates only |

Status colours never overlap with series colours, and a test keeps the two sets
disjoint. Reference lines take no hue, because a marker whose only job is to say
"here" should not compete with real series or consume a colour slot.

**Two charting rules are never broken, and both are tested:**

1. **One chart, one y-axis.** Two scales on one plot make their alignment
   arbitrary, so the chart shows a relationship the data does not contain.
   `decay_curve` once made this mistake — premium and burn are both rupees per
   lot, so there was never a reason to separate them.
2. **Calls and puts are never separated by colour alone.** Green and red are the
   market's own language and cannot be changed, but that pair separates worst
   under protanopia (measured CVD ΔE 6.5, inside the warn band). Every such
   chart also differs by marker shape or line dash.

The palette was validated against the app's own dark surface: lightness band,
chroma floor, CVD separation, normal-vision floor and contrast.

One more line does a disproportionate amount of work: every table uses
`font-variant-numeric: tabular-nums`. Without it each column's digits shift
between rows and comparing two prices by eye becomes impossible — which is most
of what an option chain is for.

---

## Units contract

Every options bug starts here, so it is written down once:

| Symbol | Unit |
|---|---|
| `S`, `K` | USD |
| `T` | **years** (fraction) |
| `sigma` | **decimal** (0.55 = 55%, not 55) |
| `bs_price` output | USD **per 1 unit of underlying** (per BTC / per ETH) |
| `theta` | USD **per day** |
| `vega` | USD **per 1 volatility point** (per 1%) |

Multiply by `contract_value` for per-lot figures (BTC options = 0.001 BTC,
ETH = 0.01 ETH).

Two things are **detected at runtime** rather than hard-coded: whether the API
sends IV in percent or as a decimal, and whether its greeks are per-unit or
per-lot. Both are resolved by repricing ATM strikes, and the verdict is shown in
each page's **🩺 Diagnostics** expander.

---

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -v          # 354 tests
python tests/check_read_only.py     # read-only guard
ruff check .                        # lint
```

No test touches the network. Beyond the pure layers, every page is **actually
rendered** against a synthetic Black-Scholes chain
([`tests/test_pages_smoke.py`](tests/test_pages_smoke.py)) — a page that
misnames a column or breaks a format string still imports cleanly and only fails
when a user opens it.

CI runs the same checks on Python 3.10, 3.11 and 3.12.

### Checking the live chain

The test suite proves the arithmetic; it cannot prove that the **assumptions
about Delta's payloads** still hold, because it never calls Delta. Those
assumptions are the ones most likely to drift silently when the exchange
changes something. `tools/live_check.py` runs the real chain through this
project's own code and checks each of them:

```bash
python tools/live_check.py                  # BTC, nearest expiry
python tools/live_check.py --underlying ETH
python tools/live_check.py --all-expiries
python tools/live_check.py --json report.json
```

It verifies that IV still arrives as a percent, that greeks are still per unit,
that timestamps still decode from microseconds, that `contract_value` is still
0.001 / 0.01, and that no market is crossed — then re-checks the derived numbers
model-free, via put-call delta parity and put-call parity on the live quotes.

Exit code is 0 when everything holds and 1 when a check fails. Warnings do not
fail the run: they mark things worth a look (a thin chain, a non-30-day
volatility basis) that are limits of the data rather than defects. Where the app
already self-corrects — the runtime calibration catching a units change — the
result is a warning, because the numbers stay right even though something moved.

This reads the same public endpoints the app reads, and nothing else.

---

## What this tool deliberately does not do

- No API key or secret — public endpoints only
- No order placement — it cannot trade
- No historical data, IV rank or IV percentile — these need history
- No alerts or notifications
- No perpetual-futures basis or funding

---

*Read-only market data. Not trading advice. The fee defaults in
[`mmc_core/fees.py`](mmc_core/fees.py) are editable in the sidebar — verify them
against https://www.delta.exchange/fees before sizing anything real.*
