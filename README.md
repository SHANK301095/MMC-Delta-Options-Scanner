# MMC Delta Options Scanner

Delta Exchange India ke **BTC / ETH options** ka live scanner — option chain,
theta decay, IV skew, payoff builder aur model-free arbitrage checks, sab ek
Streamlit app mein.

**Poori tarah read-only.** Koi API key nahi, koi secret nahi, koi order-placement
code nahi. App sirf Delta ke do public endpoints padhta hai (`/v2/products` aur
`/v2/tickers`) — aur CI har push par machine se ye verify karta hai
([`tests/check_read_only.py`](tests/check_read_only.py)).

---

## Chalane ka tarika

**Windows:** `RUN_MMC_SCANNER.bat` par double-click.
**Linux / macOS:** `./run_scanner.sh`

Dono pehli baar khud hi `.venv` banayenge, libraries install karenge aur browser
mein `http://localhost:8501` khol denge. Pehli baar 2-4 minute, uske baad
~10 second.

Manual chalana ho to:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Detailed setup, module-by-module guide aur troubleshooting:
**[README_SETUP.md](README_SETUP.md)**

---

## Modules

| Page | Kya karta hai |
|---|---|
| 🏠 **Home** | Expiry snapshot, PCR, chain-health badge |
| 📈 **Live Chain** | Call/Put chain, liquidity filter, OI profile, cost-of-trading table |
| ⏳ **Theta Decay** | Repricing-based burn ranking, hour-by-hour curve, multi-leg basket |
| 🌊 **IV Skew** | Volatility smile, 25Δ risk reversal / butterfly, term structure |
| 🎯 **Payoff Builder** | 8 preset strategies, executable fills, expiry + T+0 curves |
| 🔎 **Mispricing** | Put-call parity, vertical bounds, butterfly convexity, box spreads |
| 📐 **Delta Filter** | Delta band (0–100) se strike chuniye, live bid/ask ke saath |
| 🌡️ **Vol Regime** | VIX-style index (30-din constant maturity) + regime gate |

---

## Design decisions jo baaki screeners galat karte hain

Ye teen cheezein is scanner ki asli value hain — inhi ke bina ek options tool
chup-chaap galat numbers deta hai (crash nahi karta, jo aur khatarnak hai):

**1. Fees NOTIONAL par lagti hain, premium par nahi.**
Delta India: `fee = min(notional × rate, premium × cap) × (1 + GST)`.
Iska seedha asar — sasti OTM options par round-trip cost premium ka ~8% hota
hai, ATM par ~1.5%. Jo scanner ye ignore karta hai wo dead ₹1 strikes ko
"best theta yield" bata dega. Har table mein **net of cost** column hai.

**2. Mark price par koi fill nahi hota.**
Default price basis "Realistic" hai — buy par ASK, sell par BID. Jis chain par
chauthai strikes ka spread 20%+ ho, wahan mark-priced edge sirf kaagzi hai.

**3. Theta ek instantaneous derivative hai, ek din ka burn nahi.**
Har burn number option ko future timestamp par **dobara price karke** nikala
jaata hai. Expiry ke din analytic theta aur asli burn mein 50%+ farak aata hai.

**4. Volatility index chain se banta hai, kisi ek strike se nahi.**
Delta koi India-VIX jaisa index publish nahi karta, par uski zaroorat bhi nahi:
VIX apne aap mein option chain se hi nikaala jaata hai. `mmc_core/volatility.py`
CBOE ki model-free variance formula lagata hai — har OTM strike ka quoted
midpoint, `1/K²` weight, zero-bid truncation — phir do expiries ke beech
**total variance** par interpolate karke 30-din constant maturity par le aata
hai. Constant maturity ke bina aaj ka aur kal ka number compare karne layak
nahi rehta.

Index apni **strike coverage** ke saath report hota hai, kyunki tang chain
number ko chup-chaap neeche le jaati hai (90 din par ±15% coverage 55% vol ko
43.5% dikhati hai). Regime gate ke liye ye chupana khatarnak hota: kam VIX
padha jaata "vol saste hain", jabki wajah sirf chhoti chain thi.

**5. Delta band absolute delta par lagta hai.**
"25 delta" maangne par 0.25 delta call *aur* −0.25 delta put dono aate hain —
wahi market convention hai. Aur jis contract ka delta hi unknown hai wo band
se bahar jaata hai, kyunki delta se chunav karte waqt "shayad match karta hai"
koi jawab nahi hai.

Aur time-to-expiry hamesha **exact seconds** mein hai, whole days mein nahi —
Delta India options 17:30 IST (12:00 UTC) par settle hote hain, aur whole-day
rounding expiry din ka premium ~8x overstate kar deti hai.

---

## Units contract

Har options bug yahin se shuru hota hai, isliye ek jagah likha hai:

| Symbol | Unit |
|---|---|
| `S`, `K` | USD |
| `T` | **years** (fraction) |
| `sigma` | **decimal** (0.55 = 55%, not 55) |
| `bs_price` output | USD **per 1 unit of underlying** (per BTC / per ETH) |
| `theta` | USD **per day** |
| `vega` | USD **per 1 vol point** (per 1%) |

Per-lot value chahiye to `contract_value` se multiply karein
(BTC options = 0.001 BTC, ETH = 0.01 ETH).

App do cheezein **runtime par khud detect** karta hai, hard-code nahi karta:
API ki IV percent mein hai ya decimal mein, aur API ke greeks per-unit hain ya
per-lot. Dono ATM strikes ko dobara price karke decide hote hain — verdict
har page ke **🩺 Diagnostics** expander mein dikhta hai.

---

## Development

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -v          # 218 tests
python tests/check_read_only.py     # read-only guard
```

Tests network ko chhoote bilkul nahi. Pure layers ke alawa har page ek
synthetic Black-Scholes chain par **sach mein render** hota hai
(`tests/test_pages_smoke.py`), kyunki ek page column ka naam galat likhne ya
format string tod dene par bhi import ho jaata hai — crash tabhi hota hai jab
user use kholta hai.

CI har push par Python 3.10 / 3.11 / 3.12 par yehi chalata hai.

---

## Kya is tool mein jaan-boojh kar NAHI hai

- ❌ Koi API key ya secret — sirf public endpoints
- ❌ Koi order placement — ye trade kar hi nahi sakta
- ❌ Historical data / IV Rank / IV Percentile — history chahiye
- ❌ Alerts / notifications
- ❌ Cloud hosting — local-only tool
- ❌ Perpetual futures basis / funding

---

*Read-only market data tool. Trading advice nahi. Fee defaults
([`mmc_core/fees.py`](mmc_core/fees.py)) sidebar mein editable hain — live jaane
se pehle https://www.delta.exchange/fees par verify kar lijiye.*
