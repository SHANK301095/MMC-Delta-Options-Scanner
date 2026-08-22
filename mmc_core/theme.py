"""
MMC Delta Scanner — Design System
=================================
Ek hi jagah se poore app ka look: colours, spacing, type, aur wo chhote
components jo har page dohraata hai.

DARK-ONLY, JAAN-BOOJH KAR
-------------------------
Ye ek trading terminal hai — log ise ghanton tak dekhte hain, aksar andhere
mein. Isliye theme dark par tay hai (`.streamlit/config.toml` mein bhi), taaki
Streamlit ke apne widgets aur hamari CSS ek hi surface par baithein. "Dono modes
support kar lete hain" sunne mein achha lagta hai, par practically iska matlab
hota hai dono aadhe-adhoore.

COLOUR KA EK HI NIYAM
---------------------
Har rang ka ek hi kaam hai, aur wo kaam kabhi badalta nahi:

    CALL / profit / decay aapke favour mein   -> ACCENT_UP   (aqua-green)
    PUT / loss / decay aapke khilaf           -> ACCENT_DOWN (red)
    Analytical series (model curve, payoff)   -> SERIES_1 / SERIES_2
    Spot, ATM, thresholds                     -> INK_2 hairline (rang nahi)
    Status: healthy / watch / risky / broken  -> STATUS_* (sirf badges aur gates)

Status ke rang series ke rang se alag hain aur kabhi aapas mein udhaar nahi
lete. Ek chart ki "warning" bar aur ek regime gate ka "critical" badge kabhi
ek jaise nahi dikhne chahiye — warna dono ka matlab khatam.

CALL/PUT PAIR PAR EK ZAROORI PABANDI
------------------------------------
Green/put-red market ki bhasha hai, isse badalna UX bigaadna hoga. Lekin ye
theek wahi jodi hai jo protanopia mein sabse kam alag dikhti hai (validate
karne par CVD ΔE 6.5 — warn band). Isliye niyam: **jahan calls aur puts ek hi
chart mein hain, wahan rang ke alawa ek doosra channel bhi lazmi hai** —
marker ka shape, ya line ka dash. Rang akela kabhi identity nahi uthaata.

Palette CBOE-style validator se paas ki gayi hai is surface (SURFACE_1) par:
lightness band, chroma floor, CVD separation, normal-vision floor, aur contrast.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Surfaces & ink
# --------------------------------------------------------------------------

SURFACE_0 = "#0d0d0c"      # page plane — sabse peeche
SURFACE_1 = "#12120f"      # cards, chart surface
SURFACE_2 = "#1a1a17"      # raised: sidebar, table header, hover
SURFACE_3 = "#232320"      # input fields, chips

INK_1 = "#ffffff"          # primary text, headline numbers
INK_2 = "#c3c2b7"          # secondary text, spot/reference lines
INK_3 = "#898781"          # muted: axis labels, captions, units

GRID = "#26262a"           # hairline grid — ek shade surface se upar
AXIS = "#383835"           # baseline / axis rule
BORDER = "rgba(255,255,255,0.10)"
BORDER_STRONG = "rgba(255,255,255,0.18)"

# --------------------------------------------------------------------------
# Series colours — validated on SURFACE_1
# --------------------------------------------------------------------------

ACCENT_UP = "#199e70"      # calls, profit, decay in your favour
ACCENT_DOWN = "#e66767"    # puts, loss
SERIES_1 = "#3987e5"       # blue   — pehla analytical series
SERIES_2 = "#d95926"       # orange — doosra analytical series

FILL_UP = "rgba(25,158,112,0.20)"
FILL_DOWN = "rgba(230,103,103,0.20)"
FILL_SERIES_1 = "rgba(57,135,229,0.18)"
FILL_BAND = "rgba(57,135,229,0.13)"    # shaded range (delta band, IV band)

# --------------------------------------------------------------------------
# Status — sirf badges, gates aur pass/fail encoding. Kabhi series nahi.
# --------------------------------------------------------------------------

STATUS_GOOD = "#0ca30c"
STATUS_WARN = "#fab219"
STATUS_SERIOUS = "#ec835a"
STATUS_CRITICAL = "#d03b3b"

_STATUS = {
    "good": (STATUS_GOOD, "●"),
    "warn": (STATUS_WARN, "▲"),
    "serious": (STATUS_SERIOUS, "▲"),
    "critical": (STATUS_CRITICAL, "■"),
    "neutral": (INK_3, "○"),
}

# --------------------------------------------------------------------------
# Type & spacing
# --------------------------------------------------------------------------

FONT_STACK = ('system-ui, -apple-system, "Segoe UI", Roboto, '
              '"Helvetica Neue", Arial, sans-serif')

RADIUS = "10px"
RADIUS_SM = "6px"


def _css() -> str:
    """Poore app ki CSS. Tokens se banti hai, taaki rang ek hi jagah badle.

    Selectors jaan-boojh kar `data-testid` par hain, generated class names par
    nahi — wo Streamlit ke har release mein badal jaate hain. Aur har rule
    additive hai: koi selector miss ho jaaye to page phir bhi kaam karta hai,
    bas thoda kam sundar dikhta hai.
    """
    return f"""
<style>
  :root {{
    --mmc-surface-0: {SURFACE_0};
    --mmc-surface-1: {SURFACE_1};
    --mmc-surface-2: {SURFACE_2};
    --mmc-surface-3: {SURFACE_3};
    --mmc-ink-1: {INK_1};
    --mmc-ink-2: {INK_2};
    --mmc-ink-3: {INK_3};
    --mmc-border: {BORDER};
    --mmc-up: {ACCENT_UP};
    --mmc-down: {ACCENT_DOWN};
  }}

  html, body, [class*="css"] {{ font-family: {FONT_STACK}; }}

  .stApp {{ background: {SURFACE_0}; }}

  /* Content ko saans lene ki jagah, par trading tool ki density bani rahe.
     padding-top itna hai ki app bar Streamlit ke fixed toolbar (Deploy button
     wali patti) ke neeche se shuru ho - warna heading uske peeche chali jaati
     hai. */
  .block-container {{
      padding-top: 3.2rem;
      padding-bottom: 3rem;
      max-width: 1500px;
  }}

  /* ---------------- App bar ---------------- */

  .mmc-bar {{
      display: flex; align-items: baseline; gap: 0.7rem;
      padding: 0 0 0.9rem 0;
      border-bottom: 1px solid {BORDER};
      margin-bottom: 1.2rem;
  }}
  .mmc-bar-icon {{ font-size: 1.35rem; line-height: 1; }}
  .mmc-bar-title {{
      font-size: 1.18rem; font-weight: 650; color: {INK_1};
      letter-spacing: -0.01em;
  }}
  .mmc-bar-sub {{
      font-size: 0.8rem; color: {INK_3}; margin-left: auto;
      text-align: right; max-width: 52%;
  }}

  /* ---------------- Stat tiles ---------------- */

  .mmc-stats {{
      display: grid; gap: 0.6rem; margin-bottom: 1.1rem;
      grid-template-columns: repeat(auto-fit, minmax(148px, 1fr));
  }}
  .mmc-stat {{
      background: {SURFACE_1};
      border: 1px solid {BORDER};
      border-radius: {RADIUS};
      padding: 0.7rem 0.85rem;
      min-width: 0;
  }}
  .mmc-stat-label {{
      font-size: 0.68rem; font-weight: 600; letter-spacing: 0.06em;
      text-transform: uppercase; color: {INK_3};
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  /* Headline numbers proportional figures mein — tabular sirf un columns ke
     liye hai jinhe vertically align hona hai. */
  .mmc-stat-value {{
      font-size: 1.32rem; font-weight: 620; color: {INK_1};
      margin-top: 0.18rem; line-height: 1.2;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .mmc-stat-sub {{
      font-size: 0.72rem; color: {INK_3}; margin-top: 0.14rem;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .mmc-stat-value.up {{ color: {ACCENT_UP}; }}
  .mmc-stat-value.down {{ color: {ACCENT_DOWN}; }}
  .mmc-stat.accent {{ border-color: {BORDER_STRONG}; background: {SURFACE_2}; }}

  /* ---------------- Badges ---------------- */

  .mmc-badge {{
      display: inline-flex; align-items: center; gap: 0.34rem;
      padding: 0.16rem 0.55rem; border-radius: 999px;
      font-size: 0.72rem; font-weight: 600; letter-spacing: 0.01em;
      border: 1px solid currentColor; margin-right: 0.4rem;
      white-space: nowrap;
  }}
  .mmc-badge .dot {{ font-size: 0.62rem; line-height: 1; }}

  /* ---------------- Section headings ---------------- */

  .mmc-section {{
      display: flex; align-items: baseline; gap: 0.55rem;
      margin: 1.5rem 0 0.6rem 0;
      padding-bottom: 0.4rem;
      border-bottom: 1px solid {BORDER};
  }}
  .mmc-section-title {{
      font-size: 0.94rem; font-weight: 640; color: {INK_1};
      letter-spacing: -0.005em;
  }}
  .mmc-section-note {{ font-size: 0.76rem; color: {INK_3}; margin-left: auto; }}

  /* ---------------- Hero ---------------- */

  .mmc-hero {{
      background: {SURFACE_1}; border: 1px solid {BORDER_STRONG};
      border-radius: {RADIUS}; padding: 1.05rem 1.2rem;
      margin-bottom: 1.1rem;
  }}
  .mmc-hero-top {{
      display: flex; align-items: center; gap: 0.7rem;
      flex-wrap: wrap;
  }}
  .mmc-hero-label {{
      font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em;
      text-transform: uppercase; color: {INK_3};
  }}
  .mmc-hero-badge {{ margin-left: auto; }}
  /* Hero figure proportional figures mein rehta hai - tabular sirf un
     columns ke liye hai jinhe vertically align hona hai. */
  .mmc-hero-value {{
      font-size: 2.9rem; font-weight: 660; color: {INK_1};
      line-height: 1.05; margin: 0.3rem 0 0.15rem 0;
      letter-spacing: -0.02em;
  }}
  .mmc-hero-value.up {{ color: {ACCENT_UP}; }}
  .mmc-hero-value.down {{ color: {ACCENT_DOWN}; }}
  .mmc-hero-sub {{ font-size: 0.8rem; color: {INK_3}; line-height: 1.5; }}

  /* ---------------- Nav cards ---------------- */

  .mmc-cards {{
      display: grid; gap: 0.6rem;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  }}
  .mmc-card {{
      background: {SURFACE_1}; border: 1px solid {BORDER};
      border-radius: {RADIUS}; padding: 0.85rem 0.95rem;
  }}
  .mmc-card-title {{
      font-size: 0.87rem; font-weight: 620; color: {INK_1};
      display: flex; align-items: center; gap: 0.45rem;
  }}
  .mmc-card-body {{
      font-size: 0.79rem; color: {INK_3}; margin-top: 0.35rem;
      line-height: 1.55;
  }}

  /* ---------------- Empty state ---------------- */

  .mmc-empty {{
      background: {SURFACE_1}; border: 1px dashed {BORDER_STRONG};
      border-radius: {RADIUS}; padding: 1.6rem 1.4rem; text-align: center;
  }}
  .mmc-empty-icon {{ font-size: 1.6rem; }}
  .mmc-empty-title {{
      font-size: 0.95rem; font-weight: 620; color: {INK_1};
      margin-top: 0.45rem;
  }}
  .mmc-empty-body {{
      font-size: 0.82rem; color: {INK_3}; margin-top: 0.35rem;
      max-width: 46ch; margin-left: auto; margin-right: auto; line-height: 1.55;
  }}

  /* ---------------- Tables ---------------- */

  /* Yahi wo ek line hai jo option chain ko padhne layak banati hai: bina
     tabular figures ke har column ke digits apni marzi se hilte hain aur
     do keemtein aankh se compare karna namumkin ho jaata hai. */
  [data-testid="stDataFrame"], [data-testid="stDataFrame"] * {{
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum" 1;
  }}
  [data-testid="stDataFrame"] {{
      border: 1px solid {BORDER}; border-radius: {RADIUS}; overflow: hidden;
  }}

  /* ---------------- Sidebar ---------------- */

  /* Built-in nav filename se label banata hai ("app", "1_Live_Chain"). Uski
     jagah hum st.page_link se apna nav dete hain. */
  [data-testid="stSidebarNav"] {{ display: none; }}

  section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] {{
      border-radius: {RADIUS_SM};
      padding: 0.3rem 0.5rem;
  }}
  section[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover {{
      background: {SURFACE_2};
  }}

  section[data-testid="stSidebar"] {{
      background: {SURFACE_1};
      border-right: 1px solid {BORDER};
  }}
  section[data-testid="stSidebar"] .block-container {{ padding-top: 1.1rem; }}

  .mmc-side-head {{
      font-size: 0.68rem; font-weight: 700; letter-spacing: 0.09em;
      text-transform: uppercase; color: {INK_3};
      margin: 1.05rem 0 0.35rem 0;
      padding-bottom: 0.28rem;
      border-bottom: 1px solid {BORDER};
  }}
  .mmc-side-head:first-of-type {{ margin-top: 0; }}

  /* ---------------- Metrics (jahan native st.metric abhi bhi hai) --------- */

  [data-testid="stMetric"] {{
      background: {SURFACE_1}; border: 1px solid {BORDER};
      border-radius: {RADIUS}; padding: 0.65rem 0.8rem;
  }}
  [data-testid="stMetricLabel"] {{
      font-size: 0.68rem !important; letter-spacing: 0.05em;
      text-transform: uppercase; color: {INK_3};
  }}
  [data-testid="stMetricValue"] {{ font-size: 1.25rem; color: {INK_1}; }}

  /* ---------------- Alerts, tabs, inputs ---------------- */

  [data-testid="stAlert"] {{
      border-radius: {RADIUS}; border-left-width: 3px;
      font-size: 0.86rem;
  }}

  .stTabs [data-baseweb="tab-list"] {{ gap: 0.15rem; }}
  .stTabs [data-baseweb="tab"] {{
      font-size: 0.86rem; font-weight: 560;
      padding: 0.5rem 0.9rem; border-radius: {RADIUS_SM} {RADIUS_SM} 0 0;
  }}

  [data-testid="stExpander"] {{
      border: 1px solid {BORDER}; border-radius: {RADIUS};
      background: {SURFACE_1};
  }}

  div[data-testid="stCaptionContainer"] p {{
      font-size: 0.77rem; color: {INK_3}; line-height: 1.55;
  }}

  hr {{ border-color: {BORDER}; }}
</style>
"""


# --------------------------------------------------------------------------
# Components
# --------------------------------------------------------------------------

def inject(st) -> None:
    """CSS ek baar per rerun daaliye. `st` inject hota hai taaki ye module
    Streamlit import kiye bina test ho sake."""
    st.markdown(_css(), unsafe_allow_html=True)


def _esc(text) -> str:
    """User ya API se aayi string ko markup mein daalne se pehle escape kijiye.

    Ye components `unsafe_allow_html` par chalte hain, aur inme jaane wale
    labels chain se aate hain (symbols, expiry names, error messages). Bina
    escape kiye ek adhoora tag poora layout tod sakta hai.
    """
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def app_bar(icon: str, title: str, subtitle: str) -> str:
    return (f'<div class="mmc-bar">'
            f'<span class="mmc-bar-icon">{_esc(icon)}</span>'
            f'<span class="mmc-bar-title">{_esc(title)}</span>'
            f'<span class="mmc-bar-sub">{_esc(subtitle)}</span>'
            f'</div>')


def badge(text: str, tone: str = "neutral") -> str:
    """Status badge — hamesha icon + label ke saath.

    Rang akela status nahi uthaata: light surfaces par warning aur serious
    3:1 contrast se neeche hote hain, aur colour-blind readers ke liye do
    status rang paas paas aa sakte hain. Isliye har badge mein ek shape-dot
    aur poora shabd dono hain.
    """
    colour, dot = _STATUS.get(tone, _STATUS["neutral"])
    return (f'<span class="mmc-badge" style="color:{colour}">'
            f'<span class="dot">{dot}</span>{_esc(text)}</span>')


def stat(label: str, value, sub: str = "", tone: str = "",
         accent: bool = False) -> str:
    """Ek stat tile. tone: "" | "up" | "down"."""
    tone_cls = f" {tone}" if tone in ("up", "down") else ""
    accent_cls = " accent" if accent else ""
    sub_html = (f'<div class="mmc-stat-sub">{_esc(sub)}</div>') if sub else ""
    return (f'<div class="mmc-stat{accent_cls}">'
            f'<div class="mmc-stat-label">{_esc(label)}</div>'
            f'<div class="mmc-stat-value{tone_cls}">{_esc(value)}</div>'
            f'{sub_html}</div>')


def stat_row(tiles: list) -> str:
    """`stat()` se bane tiles ko ek responsive grid mein rakhiye.

    Grid auto-fit hai, isliye chhoti screen par tiles apne aap wrap hote hain —
    st.columns ki tarah squeeze hokar unreadable nahi hote.
    """
    return f'<div class="mmc-stats">{"".join(tiles)}</div>'


def section(title: str, note: str = "") -> str:
    note_html = f'<span class="mmc-section-note">{_esc(note)}</span>' if note else ""
    return (f'<div class="mmc-section">'
            f'<span class="mmc-section-title">{_esc(title)}</span>'
            f'{note_html}</div>')


def empty_state(icon: str, title: str, body: str) -> str:
    """Khaali result ke liye. Ek bare warning se behtar isliye hai kyunki isme
    hamesha likha hota hai ki ab karna kya hai."""
    return (f'<div class="mmc-empty">'
            f'<div class="mmc-empty-icon">{_esc(icon)}</div>'
            f'<div class="mmc-empty-title">{_esc(title)}</div>'
            f'<div class="mmc-empty-body">{_esc(body)}</div>'
            f'</div>')


def hero(label: str, value, sub: str = "", badge_html: str = "",
         tone: str = "") -> str:
    """Ek page ka sabse bada number, uske status ke saath.

    Ye tab lagta hai jab page ka poora matlab EK number hai (VIX jaisa) —
    tab use stat tiles ki qatar mein chhupa dena uska kaam chheen leta hai.
    Badge saath rehta hai taaki number aur uska matlab ek saath padhe jaayein,
    do alag jagah nahi.
    """
    tone_cls = f" {tone}" if tone in ("up", "down") else ""
    badge_part = (f'<span class="mmc-hero-badge">{badge_html}</span>'
                  if badge_html else "")
    sub_part = f'<div class="mmc-hero-sub">{_esc(sub)}</div>' if sub else ""
    return (f'<div class="mmc-hero">'
            f'<div class="mmc-hero-top">'
            f'<span class="mmc-hero-label">{_esc(label)}</span>{badge_part}</div>'
            f'<div class="mmc-hero-value{tone_cls}">{_esc(value)}</div>'
            f'{sub_part}</div>')


def nav_card(icon: str, title: str, body: str) -> str:
    return (f'<div class="mmc-card">'
            f'<div class="mmc-card-title">{_esc(icon)} {_esc(title)}</div>'
            f'<div class="mmc-card-body">{_esc(body)}</div>'
            f'</div>')


def card_grid(cards: list) -> str:
    return f'<div class="mmc-cards">{"".join(cards)}</div>'


def side_head(text: str) -> str:
    return f'<div class="mmc-side-head">{_esc(text)}</div>'


# Streamlit ke data grid ki naapein.
_ROW_PX = 35
_HEADER_PX = 40


def table_height(n_rows: int, max_px: int = 460, min_px: int = 120) -> int:
    """Table ki height rows ke hisaab se.

    Fixed height do tarah se kharab karti hai: kam rows par neeche bada khaali
    grid chhodti hai (jaise ek tight delta band par do hi contracts bachein),
    aur zyada rows par bhi utni hi rehti hai. Ye helper content tak badhti hai
    aur phir cap par ruk kar scroll karne deti hai.
    """
    try:
        rows = max(0, int(n_rows))
    except (TypeError, ValueError):
        rows = 0
    return int(min(max_px, max(min_px, _HEADER_PX + rows * _ROW_PX)))


def tone_for(value: float, good_when_positive: bool = True) -> str:
    """Number ke sign se stat tile ka tone. NaN par koi tone nahi."""
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ""
    if val != val:          # NaN
        return ""
    if val == 0:
        return ""
    positive = val > 0
    return "up" if positive == good_when_positive else "down"
