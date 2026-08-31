# MMC Delta Options Scanner — Setup Guide

**What this is:** a live option chain and analytics suite for Delta Exchange
India's BTC and ETH options.

Entirely **read-only** — no API key, no credentials, no order-placement code.

---

## 1. Install (once, about five minutes)

### Step 1 — Install Python (if you don't already have it)

1. Open https://www.python.org/downloads/
2. Click the large yellow **"Download Python 3.x"** button
3. Run the installer
4. ⚠️ **Most important:** on the first screen, tick **"Add Python to PATH"**
5. Click "Install Now" and wait for it to finish

To confirm: open the Start menu, type `cmd`, open Command Prompt and run:

```
py --version
```

If it prints something like `Python 3.12.x`, you are set.

### Step 2 — Put the folder somewhere permanent

Keep the project folder in a stable location, for example:

```
C:\MMC\MMC-Delta-Options-Scanner
```

⚠️ Avoid leaving it in Desktop or Downloads — moving it later breaks the
shortcut.

### Step 3 — Run it

**Windows:** double-click **`RUN_MMC_SCANNER.bat`**
**Linux / macOS:** run **`./run_scanner.sh`**

On first run this automatically:

- creates a virtual environment (a `.venv` folder)
- installs all libraries
- opens the scanner in your browser

The first run takes two to four minutes; afterwards about ten seconds.

**If the browser doesn't open by itself:** copy the `http://localhost:8501`
address shown in the terminal window and paste it into your browser.

**To stop:** press `Ctrl + C` in the terminal window, then close it.

### There is nothing to configure

The app uses Delta's public market-data endpoints, which need no credentials.
There is no API key to enter, no Streamlit secret to set and no environment file
to create. If you deploy it, the same is true there.

---

## 2. Folder structure (leave this as it is)

```
MMC-Delta-Options-Scanner/
├── RUN_MMC_SCANNER.bat      ← double-click this on Windows
├── run_scanner.sh           ← run this on Linux / macOS
├── app.py                   ← home page
├── requirements.txt
├── README.md                ← project overview
├── README_SETUP.md          ← this file
├── .streamlit/
│   └── config.toml          ← app theme
├── mmc_core/                ← engine (leave alone)
│   ├── delta_api.py         ← Delta API client
│   ├── options_math.py      ← Black-Scholes and payoff helpers
│   ├── volatility.py        ← VIX-style volatility index
│   ├── fees.py              ← Delta India fee model
│   ├── charts.py            ← Plotly chart layer
│   ├── theme.py             ← design system
│   ├── url_state.py         ← view state in the URL
│   ├── settings_store.py    ← local settings (local runs only)
│   └── ui_common.py         ← sidebar and shared calculations
├── pages/                   ← modules
│   ├── 1_Live_Chain.py
│   ├── 2_Theta_Decay.py
│   ├── 3_IV_Skew.py
│   ├── 4_Payoff_Builder.py
│   ├── 5_Mispricing.py
│   ├── 6_Delta_Filter.py
│   └── 7_Vol_Regime.py
└── mmc_settings.json        ← created when you press Save on a local run
```

⚠️ The `pages` folder must keep exactly that name — Streamlit looks for modules
there.

---

## 3. What to do on first run

1. The **Home** page opens, showing spot, expiry and time remaining
2. In the left sidebar, choose **Underlying** = BTC and the nearest **Expiry**
3. Set today's **USD → INR rate** in the sidebar (default 88)
4. Open the **🩺 Diagnostics** expander once and check it:
   - "API sends IV in percent -> divided by 100" is normal
   - "Greek basis detected: per_unit" is normal
   - If it reports `unknown`, send a screenshot

---

## 4. Modules

### 📈 Live Chain + Liquidity Filter

Calls and puts side by side. Columns:

| Column | Meaning |
|---|---|
| `C OI` / `P OI` | Open interest (contracts) |
| `C IV%` | Implied volatility, in percent |
| `C Δ` | Delta |
| `C θ₹` | Theta — the rupees one lot loses in a day |
| `C Spr%` | Bid-ask spread as a percentage of mid |
| `STRIKE` | Strike price (the ATM row is highlighted) |

**The liquidity filter is in the sidebar.** Defaults:

- Two-sided book only (both a bid and an ask)
- Maximum spread 25%
- Strike range ±20% from spot

This filter matters more than anything else on the page. On Delta India, distant
strikes frequently have no bid at all or a 40%+ spread — an "opportunity" shown
on one of those is an illusion.

### ⏳ Theta Decay Calculator (fee-aware)

**Tab 1 — Chain Decay Scanner.** Every liquid strike ranked by decay, over a
horizon you choose (1 to 72 hours). The strikes at the top of `Burn % of
premium` look juiciest to a seller, but they also carry the most gamma risk.

**Tab 2 — Single Strike Lab.** Pick a strike and get an hour-by-hour decay
curve, with two charts: premium melting away, and the per-step burn where theta
acceleration is clearly visible.

**Tab 3 — Position Basket.** Build a multi-leg position and see net premium, net
θ/day, net delta, net vega and a decay-only P&L curve.

⚠️ The scanner shows a **Net after cost** column on every strike — decay minus
fees and spread. Where that is negative, selling the premium loses money from
day one.

### 🌊 IV Skew & Term Structure

**Tab 1 — Smile.** IV against strike. The purple line is built from OTM
contracts (puts below spot, calls above), which is the market convention,
because ITM quotes are usually stale.

| Metric | Meaning |
|---|---|
| **25Δ Risk Reversal** | 25Δ call IV − 25Δ put IV. Positive means calls are expensive; negative means puts are (crypto's default state) |
| **25Δ Butterfly** | The average of the wings minus ATM. Higher means the market is pricing tail risk |

**Tab 2 — Term Structure.** ATM IV for each live expiry. An upward slope is
contango, downward is backwardation.

### 🎯 Payoff Builder

Eight preset strategies: short and long straddle, short and long strangle, iron
condor, bull call, bear put, short put.

Three things most payoff tools get wrong are correct here:

1. **Executable fills** — the ASK when buying, the BID when selling (nothing
   fills at the mark price)
2. **Fees on both sides** — entry and exit, GST included, with the premium cap
   applied
3. **A T+0 curve** — the expiry shape is the one people fall in love with; the
   T+0 curve decides whether you survive to see it

Break-evens, maximum profit and loss, an unlimited-risk warning and net greeks
are all computed automatically.

### 🔎 Mispricing Scanner

Four model-free arbitrage bounds, none of which assume any volatility model:

| Check | Rule |
|---|---|
| Put-call parity | C − P = S − K·e^(−rT) |
| Vertical bounds | 0 ≤ C(K₁) − C(K₂) ≤ K₂ − K₁ |
| Butterfly convexity | C(K₁) − 2C(K₂) + C(K₃) ≥ 0 |
| Box spread | payoff is always exactly K₂ − K₁ |

All of them run on **executable prices** and report net of fees.

⚠️ **This page should be mostly green.** That is what a healthy chain looks like.
If many violations appear, suspect stale data first, not free money.

### 📐 Delta Filter + Live Rates

Makes delta the primary control and the strike the result.

The slider runs on `|Δ| × 100`, from 0 to 100, with presets above it (5–15Δ deep
OTM, 15–25Δ classic short, 40–60Δ ATM and so on).

The band applies to **absolute** delta: asking for 20–30 returns both the 0.25
call and the −0.25 put. That is the market convention — "the 25 delta put" means
a delta of −0.25.

Each contract's live rates are shown: bid, ask, mark, and the **Buy @** /
**Sell @** prices for the sidebar's price basis, alongside premium per lot,
θ ₹/lot/day, round-trip cost and **Net θ %/day**.

The chart below shows where your band falls on the chain — delta is an abstract
number, and this makes it concrete.

⚠️ Two things worth remembering:

- If contracts existed in the band but the table is empty, they were removed by
  the liquidity filter. The "Removed by liquidity" tile counts exactly that.
- **Delta is not probability.** 25Δ means *roughly* a 25% chance of expiring in
  the money — an approximation, not a guarantee.

### 🌡️ Volatility Regime

A single number for the whole market's volatility — the India VIX idea, applied
to BTC and ETH.

This is not ATM IV. ATM IV is one strike's number; this is built from the entire
OTM chain, wings included, exactly as CBOE VIX and India VIX are. No
Black-Scholes, no smile fit — only quoted bid-ask midpoints and the payoff
structure.

**Regime gate:** set a band at the top (default 40–80). Inside it, your regime
is running. Outside, the page says which side and by how much — however good the
setups on the chain may look.

**Two things the page tells you about itself:**

- **Whether constant maturity was achieved.** The index should sit at 30 days,
  otherwise today's and tomorrow's readings are not comparable. If no two
  expiries bracket 30 days, the page does **not** extrapolate — it reports the
  maturity that genuinely exists, clearly labelled.
- **How wide the chain is.** A narrow chain makes the index read low. At 90
  days, ±15% strike coverage reports 55% volatility as 43.5%. Each expiry's
  coverage is shown, with a warning when it falls short.

⚠️ The index gives *expected* movement over 30 days, not direction. A high
reading does not say the market will fall — only that the move will be large,
either way.

---

## 5. Things worth reading

### Your view is saved in the URL

Underlying, expiry, price basis, USD/INR rate and both bands are written into
the address bar. Reload and you return to the same view; bookmark it and it
keeps; send the link and the recipient sees the same screen.

On a deployed app this replaces the Save button entirely, and for good reason: a
Streamlit app is one process shared by every visitor, so a setting saved on the
server would become everyone's setting.

### The decay curve holds spot and IV constant

Three things move together in real trading:

- **Theta** — time decay (this chart)
- **Delta and gamma** — P&L from spot moving
- **Vega** — P&L from IV changing

On a short-premium position the **gamma loss frequently exceeds the theta gain**.
That is why net delta and net vega are shown alongside every basket.

### Theta is shown two ways

- **Analytic θ** — the classic Black-Scholes derivative
- **Repricing burn** — the option repriced at a future timestamp, differenced

On expiry day these differ by more than 50%. **The repricing figure is the
correct one.** Analytic theta is an instantaneous slope, and it becomes wrong as
expiry approaches.

### Fees apply to notional, not premium

Delta India options fees:

```
fee = min( notional × rate , premium × cap )  × (1 + GST)
notional = lots × lot_size × index_price
```

The direct consequence: **a round trip costs about 8% of premium on a cheap OTM
option, versus roughly 2.4% at the money.** A scanner that ignores this reports
dead ₹1 strikes as the "best theta yield".

Defaults: maker 0.01%, taker 0.03%, cap 3.5%, GST 18%. **All are editable in the
sidebar** — Delta changes them occasionally, and published sources disagree with
each other. Verify against https://www.delta.exchange/fees before going live.

### Price basis

Three options in the sidebar:

- **Realistic** (default) — the ASK when buying, the BID when selling
- **Mid** — the midpoint of the book
- **Mark** — Delta's mark price

Realistic is the default because nothing fills at the mark. On a chain where a
quarter of strikes carry a 20%+ spread, mark-priced edge exists only on paper.

### Rate limit

Delta's quota is 10,000 weight per rolling five-minute window. At the default
15-second refresh the scanner uses roughly 5% of it. Do not set it to 5 seconds
without a reason.

### Expiry time

Delta India options expire at **17:30 IST = 12:00 UTC**. The scanner uses that
exact second, not whole days — otherwise every number on expiry day is wrong.

---

## 6. Troubleshooting

| Problem | Solution |
|---|---|
| `Python not found` | Python isn't installed, or PATH wasn't ticked. Reinstall |
| `Rate limit hit (HTTP 429)` | Set the refresh interval to 30 or 60 seconds |
| `Network error` | Check your internet, VPN or firewall |
| `HTTP 403 - blocked by the CDN` | Turn off any VPN and retry |
| The chain looks empty | The liquidity filter is too tight — raise the spread limit |
| Delta Filter is empty | Either no contract is in that band, or all of them failed the liquidity filter — the page says which |
| The numbers look odd | Open the Diagnostics expander and send a screenshot. For a full answer run `python tools/live_check.py` (below) |
| Libraries won't install | Delete the `.venv` folder and run the launcher again |
| Settings aren't remembered | Bookmark the URL — it carries your view. The Save button only appears on a local run |
| Auto-refresh feels slow | Increase the refresh interval, or turn auto-refresh off |
| Term structure is slow | Each expiry costs its own API call. Reduce the expiry-count slider |

### Checking the numbers against the live chain

If something on screen looks wrong and the Diagnostics expander does not settle
it, this runs the real chain through the app's own code and checks every
assumption it makes about Delta's data:

```bash
python tools/live_check.py
```

It prints a pass / warn / fail line per check and exits 0 when everything holds.
A failure names exactly which assumption stopped being true — the IV units, the
greek basis, the contract multiplier, the timestamp unit, a crossed market — so
the answer is a line of output rather than a guess. Add `--underlying ETH` for
ETH, `--all-expiries` to sweep every expiry, or `--json report.json` to save the
whole thing to a file worth sharing.

Warnings are not failures. A thin chain, or a volatility reading that is not on
a 30-day basis, are limits of what the market is quoting today, and the tool
says so rather than hiding it.

---

## 7. What this tool deliberately does not do

- ❌ No API key or secret — public endpoints only
- ❌ No order-placement code — it cannot trade
- ❌ No historical data, IV rank or IV percentile — these need history
- ❌ No realised-versus-implied volatility comparison — needs history
- ❌ No alerts or notifications
- ❌ No perpetual-futures basis or funding — the parity page checks the option
  chain's internal consistency only

---

*MMC Delta Options Scanner · Read-only market data · Not trading advice*
