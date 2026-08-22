# MMC Delta Scanner v2.0 — Setup Guide

**Kya hai:** Delta Exchange India ke BTC/ETH options ka live chain + theta decay calculator.
Poori tarah **read-only** — koi API key nahi, koi order placement code nahi.

---

## 1. Install (sirf ek baar, ~5 minute)

### Step 1 — Python install karein (agar pehle se nahi hai)

1. Kholein: https://www.python.org/downloads/
2. Bada peela button **"Download Python 3.x"** dabaiye
3. Installer chalaiye
4. ⚠️ **Sabse important:** pehli screen par **"Add Python to PATH"** ka checkbox tick karein
5. "Install Now" dabaiye, khatam hone tak wait karein

**Check karne ke liye:** Start menu → `cmd` type karein → Command Prompt kholein → likhen:
```
py --version
```
Agar `Python 3.12.x` jaisa kuch aaya to sab theek hai.

### Step 2 — Folder rakhein

`MMC_Delta_Scanner` folder ko kahin permanent jagah rakhein, jaise:
```
C:\MMC\MMC_Delta_Scanner
```
⚠️ Desktop ya Downloads mein mat chhodiye — path badalne par shortcut toot jaata hai.

### Step 3 — Chalaiye

Folder ke andar **`RUN_MMC_SCANNER.bat`** par double-click karein.

Pehli baar ye khud hi:
- ek virtual environment banayega (`.venv` folder)
- saari libraries install karega
- browser mein scanner khol dega

Pehli baar 2-4 minute lagega. Uske baad har baar 10 second.

**Browser apne aap na khule to:** black window mein jo `http://localhost:8501` likha hai, use copy karke browser mein paste kar dijiye.

**Band karne ke liye:** black window mein `Ctrl + C` dabaiye, phir window band kar dijiye.

---

## 2. Folder structure (mat badliye)

```
MMC_Delta_Scanner/
├── RUN_MMC_SCANNER.bat      ← isi par double-click
├── app.py                   ← Home page
├── requirements.txt
├── README_SETUP.md          ← ye file
├── mmc_core/                ← engine (mat chhediye)
│   ├── __init__.py
│   ├── delta_api.py         ← Delta API client
│   ├── options_math.py      ← Black-Scholes + payoff helpers
│   ├── fees.py              ← Delta India fee model
│   ├── charts.py            ← Plotly chart layer
│   ├── settings_store.py    ← settings save/load
│   └── ui_common.py         ← sidebar + calculations
├── pages/                   ← modules
│   ├── 1_Live_Chain.py
│   ├── 2_Theta_Decay.py
│   ├── 3_IV_Skew.py
│   ├── 4_Payoff_Builder.py
│   ├── 5_Mispricing.py
│   └── 6_Delta_Filter.py
└── mmc_settings.json        ← Save dabane par khud banegi
```

⚠️ `pages` folder ka naam bilkul `pages` hi rehna chahiye — Streamlit isi naam se modules dhoondhta hai.

---

## 3. Pehli baar kya karein

1. **Home page** khulega → upar Spot, Expiry, Time left dikhega
2. Left sidebar mein **Underlying** = BTC, **Expiry** = nearest wali chunein
3. Sidebar mein **USD → INR rate** aaj ka daal dijiye (default 88)
4. **🩺 Diagnostics** expander kholiye aur ek baar dekh lijiye:
   - "IV: API IV percent mein hai → ÷100 lagaya" — ye normal hai
   - "Greek basis detected: per_unit" — ye bhi normal hai
   - Agar yahan `unknown` aaye to mujhe screenshot bhej dijiye

---

## 4. Modules

### 📈 Live Chain + Liquidity Filter

Call/Put side-by-side chain. Columns:

| Column | Matlab |
|---|---|
| `C OI` / `P OI` | Open Interest (contracts) |
| `C IV%` | Implied Volatility, percent mein |
| `C Δ` | Delta |
| `C θ₹` | Theta — ek lot ek din mein kitna ₹ khoyega |
| `C Spr%` | Bid-ask spread, mid ka percent |
| `STRIKE` | Strike price (ATM row highlighted) |

**Liquidity filter sidebar mein hai.** Default settings:
- Sirf two-sided book (bid AND ask dono hon)
- Max spread 25%
- Strike range ±20% spot se

Ye filter sabse zaroori hai. Delta India par zyadatar door ke strikes par ya to bid hi nahi hota ya 40%+ spread hota hai — un par "opportunity" dikhna sirf illusion hai.

### ⏳ Theta Decay Calculator (fee-aware)

**Tab 1 — Chain Decay Scanner**
Har liquid strike ka decay ranking. Horizon slider se choose karein (1-72 ghante).
`Burn % of premium` sabse upar wale strikes seller ke liye juicy dikhte hain — lekin unhi ka gamma risk sabse zyada hota hai.

**Tab 2 — Single Strike Lab**
Ek strike chunein → ghanta-ba-ghanta decay curve. Do charts:
- Premium melting away (green line girti hui)
- Step burn (orange bars — theta acceleration saaf dikhta hai)

**Tab 3 — Position Basket**
Multi-leg position banaiye. Net Premium, Net θ/day, Net Delta, Net Vega aur decay-only P&L chart milega.

⚠️ Scanner ab har strike par **Net after cost** column dikhata hai — decay minus (fees + spread). Jahan ye negative hai, wahan premium bechna pehle din se ghaata hai.

### 🌊 IV Skew & Term Structure

**Tab 1 — Smile:** IV vs strike. Purple line OTM contracts se banti hai (spot ke neeche puts, upar calls) — yahi market convention hai, kyunki ITM quotes stale hoti hain.

Skew metrics:
| Metric | Matlab |
|---|---|
| **25Δ Risk Reversal** | 25Δ Call IV − 25Δ Put IV. Positive = calls mehnge. Negative = puts mehnge (crypto ki default state) |
| **25Δ Butterfly** | Wings ka average minus ATM. Zyada = market tail risk price kar raha hai |

**Tab 2 — Term Structure:** Har live expiry ki ATM IV. Upar jaati line = contango, neeche = backwardation.

### 🎯 Payoff Builder

8 preset strategies: Short/Long Straddle, Short/Long Strangle, Iron Condor, Bull Call, Bear Put, Short Put.

Teen cheezein jo aam payoff tools galat karte hain, yahan sahi hain:
1. **Executable fills** — Buy par ASK, Sell par BID (mark price par koi fill nahi hota)
2. **Fees dono taraf** — entry + exit, GST sameta, premium cap ke saath
3. **T+0 curve** — expiry wali shape se pyaar ho jaata hai; T+0 curve decide karti hai ki aap expiry tak zinda bachenge ya nahi

Break-evens, max profit/loss, unlimited-risk warning aur net greeks sab automatic.

### 📐 Delta Filter + Live Rates

Delta ko primary control banata hai, strike ko result.

Slider `|Δ| × 100` par chalta hai — 0 se 100. Upar preset buttons hain
(5-15Δ deep OTM, 15-25Δ classic short, 40-60Δ ATM waqaira), ya khud range
kheench lijiye.

Band **absolute** delta par lagta hai: 20-30 maangne par 0.25 delta call aur
−0.25 delta put dono aayenge. Yahi market convention hai — "25 delta put"
ka matlab delta −0.25 hota hai.

Table mein har contract ke live rate hain: Bid, Ask, Mark, aur sidebar ke price
basis se **Buy @** / **Sell @**. Uske saath ₹ premium per lot, θ ₹/lot/day,
round-trip cost, aur **Net θ %/day**.

Neeche ka chart batata hai ki aapki band chain par kahan padti hai — delta ek
abstract number hai, aur ye dikha deta hai ki 20-30Δ maangne par aap spot se
kitne door ja rahe hain.

⚠️ Do baatein:
- Agar band mein contracts the par table khaali hai, to wo liquidity filter mein
  nikle hain. Metric "Liquidity ne hataye" wahi ginta hai.
- **Delta probability nahi hai.** 25Δ ka matlab *lagbhag* 25% chance hai ki
  option ITM expire hoga — approximation hai, guarantee nahi.

### 🔎 Mispricing Scanner

Chaar model-free arbitrage bounds — inme koi volatility assumption hai hi nahi:

| Check | Rule |
|---|---|
| Put-Call Parity | C − P = S − K·e^(−rT) |
| Vertical Bounds | 0 ≤ C(K₁) − C(K₂) ≤ K₂ − K₁ |
| Butterfly Convexity | C(K₁) − 2C(K₂) + C(K₃) ≥ 0 |
| Box Spread | payoff hamesha exactly K₂ − K₁ |

Sab **executable prices** par chalte hain aur fees ghata kar report karte hain.

⚠️ **Is page par zyadatar GREEN dikhna chahiye.** Wahi healthy chain ki nishani hai. Bahut saare violations aayein to pehla shak stale data par karein, free money par nahi.

---

## 5. Zaroori baatein (padh lijiye)

### Decay curve spot aur IV ko FREEZE karke banta hai
Real trading mein teen cheezein saath chalti hain:
- **Theta** — time decay (ye chart)
- **Delta/Gamma** — spot hilne se P&L
- **Vega** — IV badalne se P&L

Short premium position par **gamma loss aksar theta gain se bada** ho jaata hai. Isi liye har basket ke saath Net Delta aur Net Vega bhi dikhaya jaata hai.

### Theta do tarike se dikhaya jaata hai
- **Analytic θ** — classic Black-Scholes derivative
- **Repricing burn** — option ko future timestamp par dobara price karke difference

Expiry ke din inme 50%+ ka farak aata hai. **Repricing wala number sahi hai.** Analytic theta ek instantaneous slope hai, jo expiry paas aane par ghalat ho jaata hai.

### Fees notional par lagti hain, premium par nahi

Delta India options fee:
```
fee = min( notional × rate , premium × cap )  × (1 + GST)
notional = lots × lot_size × index_price
```

Iska seedha asar: **sasti OTM options par round-trip cost premium ka ~8% hota hai, jabki ATM par ~2.4%.** Jo scanner ye ignore karta hai, wo dead ₹1 strikes ko "best theta yield" bata dega.

Defaults: maker 0.01%, taker 0.03%, cap 3.5%, GST 18%. **Sab sidebar mein editable hain** — Delta ye kabhi-kabhi badalta hai, aur published sources bhi aapas mein disagree karte hain. Live jaane se pehle https://www.delta.exchange/fees par verify kar lijiye.

### Price basis

Sidebar mein teen options:
- **Realistic** (default) — Buy par ASK, Sell par BID
- **Mid** — book ka midpoint
- **Mark** — Delta ka mark price

Realistic hi default hai kyunki mark price par koi fill nahi hota. Jis chain par chauthai strikes ka spread 20%+ ho, wahan mark-priced edge sirf kaagzi hota hai.

### Rate limit
Delta ka quota 5 minute ke window mein 10,000 weight hai. Default 15-second refresh par scanner iska ~5% use karta hai.
5 second par mat rakhiye jab tak zaroorat na ho.

### Expiry time
Delta India options **17:30 IST = 12:00 UTC** par expire hote hain. Scanner ye exact second-level use karta hai, whole days nahi — warna expiry din ke saare numbers galat aate.

---

## 6. Troubleshooting

| Problem | Solution |
|---|---|
| `Python nahi mila` | Python install nahi hua ya PATH tick nahi kiya. Dobara install karein |
| `Rate limit hit (HTTP 429)` | Sidebar mein refresh interval 30 ya 60 sec kar dijiye |
| `Network error` | Internet / VPN / firewall check karein |
| `HTTP 403 - CDN block` | VPN band karke try karein |
| Chain khali dikh rahi hai | Liquidity filter bahut tight hai — spread limit badhaiye |
| Delta Filter khali hai | Band mein contract nahi, ya sab liquidity filter mein nikal gaye — page khud batata hai kaunsi wajah hai |
| Numbers ajeeb lag rahe hain | Diagnostics expander kholiye, screenshot bhejiye |
| Libraries install nahi ho rahi | `.venv` folder delete karke `.bat` dobara chalaiye |
| Settings yaad nahi rah rahi | Sidebar mein **💾 Save** dabaiye (ek baar) |
| Auto-refresh par UI slow lagta hai | Normal hai — refresh ke beech click queue hota hai. Interval badha dijiye ya auto-refresh off karein |
| Term structure slow hai | Har expiry ke liye alag API call jaati hai. "Kitni expiries" slider kam kar dijiye |

---

## 7. Kya is tool mein NAHI hai (jaan-boojh kar)

- ❌ Koi API key ya secret — sirf public endpoints
- ❌ Koi order placement code — trade kar hi nahi sakta
- ❌ Historical data / IV Rank / IV Percentile — inke liye history chahiye (Data Spine, Phase 3)
- ❌ Realised vs implied vol comparison — history chahiye
- ❌ Alerts / notifications — Phase 3
- ❌ Cloud hosting — ye local-only tool hai
- ❌ Perpetual futures basis / funding — parity page abhi sirf options chain ki internal consistency check karta hai

---

---

## 8. v2.0 mein kya naya hai

| Area | v1.0 | v2.0 |
|---|---|---|
| Modules | 2 | 5 |
| Fees | ❌ | ✅ Full Delta India model (notional + cap + GST) |
| Price basis | Mark only | Realistic / Mid / Mark |
| Charts | Basic | Plotly (hover, zoom, export) |
| Auto-refresh | ❌ | ✅ |
| Settings save | ❌ | ✅ |
| Break-even detection | — | ✅ dedupe-safe |
| Arbitrage checks | ❌ | ✅ 4 model-free bounds |

---

*MMC Delta Scanner v2.0 · Read-only market data · Trading advice nahi*
