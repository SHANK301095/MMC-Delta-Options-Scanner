"""
MMC Delta Scanner - Design System
=================================
One place that defines how the whole app looks: colours, spacing, type, and the
small components every page repeats.

DARK ONLY, DELIBERATELY
-----------------------
This is a trading terminal - people stare at it for hours, often in a dark
room. So the theme is fixed to dark (in `.streamlit/config.toml` too), which
keeps Streamlit's own widgets and our CSS on the same surface. "We support both
modes" sounds good, but in practice it means doing both of them badly.

ONE RULE FOR COLOUR
-------------------
Every colour has exactly one job, and that job never changes:

    CALL / profit / decay in your favour     -> ACCENT_UP   (aqua-green)
    PUT / loss / decay against you           -> ACCENT_DOWN (red)
    Analytical series (model curve, payoff)  -> SERIES_1 / SERIES_2
    Spot, ATM, thresholds                    -> INK_2 hairline (no hue)
    Status: healthy / watch / risky / broken -> STATUS_* (badges and gates only)

Status colours are distinct from series colours and never borrow from each
other. A chart's "warning" bar and a regime gate's "critical" badge must never
look alike, or both stop meaning anything.

ONE CONSTRAINT ON THE CALL/PUT PAIR
-----------------------------------
Green-for-calls and red-for-puts is the market's own language; changing it
would make the tool harder to read, not easier. But it is also precisely the
pair that separates worst under protanopia (measured CVD dE 6.5 - inside the
warn band). Hence the rule: **wherever calls and puts appear in the same chart,
a second channel is mandatory alongside colour** - marker shape, or line dash.
Colour alone never carries identity.

The palette was validated against this surface (SURFACE_1) with a CBOE-style
checker: lightness band, chroma floor, CVD separation, normal-vision floor and
contrast.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Surfaces & ink
# --------------------------------------------------------------------------

SURFACE_0 = "#0d0d0c"      # page plane - furthest back
SURFACE_1 = "#12120f"      # cards, chart surface
SURFACE_2 = "#1a1a17"      # raised: sidebar, table header, hover
SURFACE_3 = "#232320"      # input fields, chips

INK_1 = "#ffffff"          # primary text, headline numbers
INK_2 = "#c3c2b7"          # secondary text, spot / reference lines
INK_3 = "#898781"          # muted: axis labels, captions, units

GRID = "#26262a"           # hairline grid - one shade above the surface
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
# Status - badges, gates and pass/fail encoding only. Never a series.
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
    """The whole app's CSS, built from the tokens so colour changes in one place.

    Selectors deliberately target `data-testid` rather than generated class
    names, which change with every Streamlit release. Every rule is additive:
    if a selector stops matching, the page still works, it just looks a little
    plainer.
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

  /* Room to breathe, while keeping a trading tool's density.
     padding-top clears Streamlit's fixed toolbar (the strip holding the Deploy
     button) so the app bar starts below it instead of behind it. */
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
  /* Headline numbers use proportional figures - tabular is reserved for
     columns that must align vertically. */
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
  /* The hero figure keeps proportional figures - tabular is reserved for
     columns that must align vertically. */
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

  /* This single line is what makes an option chain readable: without tabular
     figures each column's digits shift between rows, and comparing two prices
     by eye becomes impossible. */
  [data-testid="stDataFrame"], [data-testid="stDataFrame"] * {{
      font-variant-numeric: tabular-nums;
      font-feature-settings: "tnum" 1;
  }}
  [data-testid="stDataFrame"] {{
      border: 1px solid {BORDER}; border-radius: {RADIUS}; overflow: hidden;
  }}

  /* ---------------- Sidebar ---------------- */

  /* The built-in nav derives labels from filenames ("app", "1_Live_Chain").
     We hide it and build our own from st.page_link instead. */
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

  /* ---------------- Metrics (where native st.metric is still used) ------- */

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
    """Inject the CSS once per rerun.

    `st` is passed in so this module can be tested without importing Streamlit.
    """
    st.markdown(_css(), unsafe_allow_html=True)


def _esc(text) -> str:
    """Escape a string that came from a user or an API before it enters markup.

    These components render with `unsafe_allow_html`, and the labels they
    receive come from the chain (symbols, expiry names, error messages). Without
    escaping, a single unclosed tag can break the whole layout.
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
    """A status badge - always icon plus label.

    Colour never carries status on its own: on light surfaces warning and
    serious fall below 3:1 contrast, and two status colours can sit close
    together for colour-blind readers. So every badge carries both a shape dot
    and the full word.
    """
    colour, dot = _STATUS.get(tone, _STATUS["neutral"])
    return (f'<span class="mmc-badge" style="color:{colour}">'
            f'<span class="dot">{dot}</span>{_esc(text)}</span>')


def stat(label: str, value, sub: str = "", tone: str = "",
         accent: bool = False) -> str:
    """A single stat tile. tone: "" | "up" | "down"."""
    tone_cls = f" {tone}" if tone in ("up", "down") else ""
    accent_cls = " accent" if accent else ""
    sub_html = (f'<div class="mmc-stat-sub">{_esc(sub)}</div>') if sub else ""
    return (f'<div class="mmc-stat{accent_cls}">'
            f'<div class="mmc-stat-label">{_esc(label)}</div>'
            f'<div class="mmc-stat-value{tone_cls}">{_esc(value)}</div>'
            f'{sub_html}</div>')


def stat_row(tiles: list) -> str:
    """Lay tiles built by `stat()` into a responsive grid.

    The grid is auto-fit, so on a narrow screen the tiles wrap instead of being
    squeezed into unreadable columns the way st.columns would.
    """
    return f'<div class="mmc-stats">{"".join(tiles)}</div>'


def section(title: str, note: str = "") -> str:
    note_html = f'<span class="mmc-section-note">{_esc(note)}</span>' if note else ""
    return (f'<div class="mmc-section">'
            f'<span class="mmc-section-title">{_esc(title)}</span>'
            f'{note_html}</div>')


def empty_state(icon: str, title: str, body: str) -> str:
    """For an empty result.

    Better than a bare warning because it always says what to do next.
    """
    return (f'<div class="mmc-empty">'
            f'<div class="mmc-empty-icon">{_esc(icon)}</div>'
            f'<div class="mmc-empty-title">{_esc(title)}</div>'
            f'<div class="mmc-empty-body">{_esc(body)}</div>'
            f'</div>')


def hero(label: str, value, sub: str = "", badge_html: str = "",
         tone: str = "") -> str:
    """A page's largest number, shown with its status.

    Used when a page's entire meaning is ONE number (the volatility index, for
    example) - hiding that in a row of stat tiles strips it of its job. The
    badge sits alongside so the number and its meaning read together rather
    than in two separate places.
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


# Streamlit's data grid metrics.
_ROW_PX = 35
_HEADER_PX = 40


def table_height(n_rows: int, max_px: int = 460, min_px: int = 120) -> int:
    """Size a table to its row count.

    A fixed height fails in both directions: with few rows it leaves a large
    empty grid below (a tight delta band might leave only two contracts), and
    with many rows it stays just as short. This grows with the content, then
    stops at a cap and lets the table scroll.
    """
    try:
        rows = max(0, int(n_rows))
    except (TypeError, ValueError):
        rows = 0
    return int(min(max_px, max(min_px, _HEADER_PX + rows * _ROW_PX)))


def tone_for(value: float, good_when_positive: bool = True) -> str:
    """Derive a stat tile's tone from a number's sign. NaN gets no tone."""
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
