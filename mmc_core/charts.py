"""
MMC Delta Scanner - Chart Layer
===============================
Every chart is built here, so the whole app speaks one visual language and a
colour never changes meaning.

Colour, spacing and ink come from `theme.py` - there is no hard-coded hex in
this file. Change a token in one place and the whole app follows.

TWO RULES THAT ARE NEVER BROKEN HERE
------------------------------------
1. **One chart, one y-axis.** Putting two different scales on one plot is the
   most common and most expensive charting bug: the alignment between the two
   scales is arbitrary, so the chart invents a relationship the data does not
   contain. If you need two units, draw two charts.

2. **Calls and puts are never separated by colour alone.** Green and red are
   the market's own language and cannot be changed - but that is precisely the
   pair that separates worst under protanopia. So wherever both appear in one
   chart there is a second channel: marker shape (circle vs diamond), line
   dash, or the positional separation of grouped bars. A legend is always
   present.

Spot, ATM and threshold lines take no hue - they are recessive ink hairlines. A
reference line should not compete with the series; its only job is to mark a
position.
"""

from __future__ import annotations

import plotly.graph_objects as go

from .theme import (
    ACCENT_DOWN,
    ACCENT_UP,
    AXIS,
    FILL_BAND,
    FILL_DOWN,
    FILL_UP,
    GRID,
    INK_1,
    INK_2,
    INK_3,
    SERIES_1,
    SERIES_2,
    STATUS_GOOD,
    STATUS_WARN,
)

# Backwards-compatible names - older code imported these.
C_CALL = ACCENT_UP
C_PUT = ACCENT_DOWN
C_SPOT = INK_2
C_WARN = STATUS_WARN
C_MODEL = SERIES_1
C_NEUTRAL = INK_3
C_GRID = GRID
C_ZERO = AXIS
PROFIT_FILL = FILL_UP
LOSS_FILL = FILL_DOWN

# The marker and dash channel that keeps calls and puts distinct without
# relying on colour. Defined once so every chart stays consistent.
CALL_MARKER = "circle"
PUT_MARKER = "diamond"
CALL_DASH = "solid"
PUT_DASH = "dot"

_HOVER = dict(
    bgcolor="rgba(18,18,15,0.94)",
    bordercolor="rgba(255,255,255,0.18)",
    font=dict(color=INK_1, size=12),
)


def base_layout(title: str = "", height: int = 380,
                x_title: str = "", y_title: str = "",
                show_legend: bool = True) -> dict:
    """Shared layout. The background is transparent so the card surface shows."""
    axis = dict(
        gridcolor=GRID, griddash="solid", gridwidth=1,
        zerolinecolor=AXIS, zerolinewidth=1,
        linecolor=AXIS, ticks="outside", ticklen=4, tickcolor=AXIS,
        tickfont=dict(color=INK_3, size=11),
        title_font=dict(color=INK_3, size=11),
    )
    return dict(
        title=dict(text=title, font=dict(size=14, color=INK_1)) if title else None,
        height=height,
        margin=dict(l=8, r=8, t=44 if title else 18, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK_2, size=12),
        hovermode="x unified",
        hoverlabel=_HOVER,
        showlegend=show_legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="right", x=1, font=dict(color=INK_2, size=11),
                    bgcolor="rgba(0,0,0,0)"),
        xaxis={**axis, "title": x_title},
        yaxis={**axis, "title": y_title},
    )


def apply_layout(fig: go.Figure, **kwargs) -> go.Figure:
    layout = base_layout(**kwargs)
    layout = {k: v for k, v in layout.items() if v is not None}
    fig.update_layout(**layout)
    return fig


def add_spot_line(fig: go.Figure, spot: float, label: str = "Spot") -> go.Figure:
    """A recessive reference hairline at spot.

    This is not a series, so it gets no categorical hue - otherwise it would
    compete with the real series and consume a free colour slot.
    """
    fig.add_vline(x=spot, line_width=1, line_dash="dash", line_color=INK_2,
                  annotation_text=f"{label} {spot:,.0f}",
                  annotation_position="top",
                  annotation_font_color=INK_2, annotation_font_size=11)
    return fig


def add_zero_line(fig: go.Figure) -> go.Figure:
    fig.add_hline(y=0, line_width=1, line_color=AXIS)
    return fig


# --------------------------------------------------------------------------
# Chart builders
# --------------------------------------------------------------------------

def oi_profile(strikes, call_oi, put_oi, spot: float) -> go.Figure:
    """Back-to-back open-interest bars by strike.

    Grouped rather than stacked: calls and puts occupy separate positions, and
    that positional difference, together with the legend, is the second channel
    alongside colour.
    """
    fig = go.Figure()
    fig.add_bar(x=strikes, y=call_oi, name="Call OI",
                marker_color=ACCENT_UP, marker_line_width=0,
                hovertemplate="Strike %{x:,.0f}<br>Call OI %{y:,.0f}<extra></extra>")
    fig.add_bar(x=strikes, y=put_oi, name="Put OI",
                marker_color=ACCENT_DOWN, marker_line_width=0,
                hovertemplate="Strike %{x:,.0f}<br>Put OI %{y:,.0f}<extra></extra>")
    apply_layout(fig, height=320, x_title="Strike",
                 y_title="Open Interest (contracts)")
    # A 2px gap between fills - drawing borders to separate marks is an
    # anti-pattern.
    fig.update_layout(barmode="group", bargap=0.28, bargroupgap=0.08,
                      hovermode="closest")
    add_spot_line(fig, spot)
    return fig


def volatility_smile(call_strikes, call_iv, put_strikes, put_iv,
                     spot: float, blend_strikes=None, blend_iv=None,
                     band: tuple | None = None) -> go.Figure:
    """Implied volatility against strike, with the OTM-blended curve on top.

    The blended line is what desks actually quote: puts below spot, calls above
    - because ITM quotes on a crypto chain are usually stale.
    """
    fig = go.Figure()

    if band is not None:
        lo, hi = float(band[0]), float(band[1])
        fig.add_hrect(y0=lo, y1=hi, fillcolor=FILL_BAND, line_width=0,
                      layer="below",
                      annotation_text=f"IV band {lo:.0f}–{hi:.0f}%",
                      annotation_position="top left",
                      annotation_font_color=INK_2, annotation_font_size=11)

    fig.add_scatter(x=call_strikes, y=call_iv, name="Call IV", mode="markers",
                    marker=dict(color=ACCENT_UP, size=8, symbol=CALL_MARKER),
                    hovertemplate="Strike %{x:,.0f}<br>"
                                  "Call IV %{y:.1f}%<extra></extra>")
    fig.add_scatter(x=put_strikes, y=put_iv, name="Put IV", mode="markers",
                    marker=dict(color=ACCENT_DOWN, size=8, symbol=PUT_MARKER),
                    hovertemplate="Strike %{x:,.0f}<br>Put IV %{y:.1f}%<extra></extra>")
    if blend_strikes is not None and blend_iv is not None and len(blend_strikes):
        fig.add_scatter(x=blend_strikes, y=blend_iv, name="OTM curve",
                        mode="lines", line=dict(color=SERIES_1, width=2),
                        hovertemplate="Strike %{x:,.0f}<br>IV %{y:.1f}%<extra></extra>")

    apply_layout(fig, height=400, x_title="Strike",
                 y_title="Implied Volatility (%)")
    fig.update_layout(hovermode="closest")
    add_spot_line(fig, spot)
    return fig


def term_structure(labels, atm_iv, days_left) -> go.Figure:
    """ATM implied volatility across expiries.

    An upward slope is contango, downward is backwardation. There is only one
    series, so no legend is needed - the title names it.
    """
    fig = go.Figure()
    fig.add_scatter(x=days_left, y=atm_iv, mode="lines+markers",
                    name="ATM IV", line=dict(color=SERIES_1, width=2),
                    marker=dict(size=9, color=SERIES_1,
                                line=dict(width=2, color="rgba(18,18,15,1)")),
                    text=labels,
                    hovertemplate="%{text}<br>%{x:.2f} days"
                                  "<br>ATM IV %{y:.1f}%<extra></extra>")
    apply_layout(fig, height=330, x_title="Days to expiry",
                 y_title="Implied Volatility (%)", show_legend=False)
    fig.update_layout(hovermode="closest")
    return fig


def decay_curve(hours, premium, cumulative) -> go.Figure:
    """Premium remaining and cumulative burn - on ONE y-axis.

    This once used two axes. That was wrong, and not merely cosmetically: both
    series are in the same unit (rupees per lot) and are two halves of the same
    quantity - the premium that left is the burn that happened. Putting them on
    separate scales made the relationship between the two numbers arbitrary,
    and let a reader see a gap or a crossover that was not in the data.
    """
    fig = go.Figure()
    fig.add_scatter(x=hours, y=premium, name="Premium bacha", mode="lines",
                    line=dict(color=ACCENT_UP, width=2),
                    fill="tozeroy", fillcolor=FILL_UP,
                    hovertemplate="+%{x:.1f}h<br>Premium ₹%{y:,.2f}<extra></extra>")
    fig.add_scatter(x=hours, y=cumulative, name="Cumulative burn", mode="lines",
                    line=dict(color=ACCENT_DOWN, width=2, dash="dot"),
                    hovertemplate="+%{x:.1f}h<br>Burnt ₹%{y:,.2f}<extra></extra>")
    apply_layout(fig, height=340, x_title="Hours ahead", y_title="₹ per lot")
    return fig


def burn_bars(hours, step_burn) -> go.Figure:
    """Burn per step. The rising tail on the right is theta acceleration."""
    fig = go.Figure()
    fig.add_bar(x=hours, y=step_burn, name="Burn per step",
                marker_color=SERIES_2, marker_line_width=0,
                hovertemplate="+%{x:.1f}h<br>Burn ₹%{y:,.2f}<extra></extra>")
    apply_layout(fig, height=250, x_title="Hours ahead",
                 y_title="₹ burnt in step", show_legend=False)
    fig.update_layout(hovermode="closest", bargap=0.2)
    return fig


def payoff_diagram(spots, payoff_expiry, spot_now: float,
                   payoff_now=None, breakevens=None,
                   label_now: str = "Today (T+0)") -> go.Figure:
    """A payoff diagram with profit/loss shading and break-even markers.

    The shading encodes polarity (profit above, loss below) against the zero
    line as its reference - so here colour carries sign, not identity. The two
    curves are separated by their own hue and dash.
    """
    fig = go.Figure()

    pos = [max(0.0, v) for v in payoff_expiry]
    neg = [min(0.0, v) for v in payoff_expiry]
    fig.add_scatter(x=spots, y=pos, mode="lines", line=dict(width=0),
                    fill="tozeroy", fillcolor=FILL_UP,
                    showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=spots, y=neg, mode="lines", line=dict(width=0),
                    fill="tozeroy", fillcolor=FILL_DOWN,
                    showlegend=False, hoverinfo="skip")

    fig.add_scatter(x=spots, y=payoff_expiry, name="At expiry", mode="lines",
                    line=dict(color=SERIES_1, width=2.4),
                    hovertemplate="Spot %{x:,.0f}<br>P&L ₹%{y:,.0f}<extra></extra>")

    if payoff_now is not None:
        fig.add_scatter(x=spots, y=payoff_now, name=label_now, mode="lines",
                        line=dict(color=SERIES_2, width=2, dash="dot"),
                        hovertemplate="Spot %{x:,.0f}<br>P&L ₹%{y:,.0f}<extra></extra>")

    if breakevens:
        fig.add_scatter(x=breakevens, y=[0] * len(breakevens), mode="markers",
                        name="Break-even",
                        marker=dict(color=INK_1, size=10, symbol="x-thin",
                                    line=dict(width=2, color=INK_1)),
                        hovertemplate="Break-even %{x:,.0f}<extra></extra>")

    apply_layout(fig, height=430, x_title="Spot at expiry", y_title="P&L (₹)")
    add_zero_line(fig)
    add_spot_line(fig, spot_now, label="Now")
    return fig


def spread_heat(strikes, spread_pct, spot: float, limit: float) -> go.Figure:
    """Spread percentage per strike, coloured by whether it passes the filter.

    Here colour encodes STATE (pass / fail), not identity - so the status
    palette applies, not the series palette. The threshold line carries a label
    so the encoding does not rest on colour alone.
    """
    colours = [STATUS_GOOD if (s is not None and s == s and s <= limit)
               else STATUS_WARN for s in spread_pct]
    fig = go.Figure()
    fig.add_bar(x=strikes, y=spread_pct, marker_color=colours,
                marker_line_width=0,
                hovertemplate="Strike %{x:,.0f}<br>Spread %{y:.1f}%<extra></extra>")
    fig.add_hline(y=limit, line_dash="dash", line_color=INK_2, line_width=1,
                  annotation_text=f"Filter {limit:.0f}%",
                  annotation_font_color=INK_2, annotation_font_size=11)
    apply_layout(fig, height=280, x_title="Strike",
                 y_title="Bid-ask spread (%)", show_legend=False)
    fig.update_layout(hovermode="closest", bargap=0.2)
    add_spot_line(fig, spot)
    return fig


def delta_profile(call_strikes, call_delta_pct, put_strikes, put_delta_pct,
                  spot: float, band: tuple | None = None) -> go.Figure:
    """|delta| x 100 against strike, with the selected band shaded.

    Delta is an abstract number; this chart gives it a position on the chain -
    it shows at a glance how far from spot a 20-30 delta request actually
    lands, and whether any contracts exist in that range at all.
    """
    fig = go.Figure()

    if band is not None:
        lo, hi = float(band[0]), float(band[1])
        fig.add_hrect(y0=lo, y1=hi, fillcolor=FILL_BAND, line_width=0,
                      layer="below",
                      annotation_text=f"Band {lo:.0f}Δ – {hi:.0f}Δ",
                      annotation_position="top left",
                      annotation_font_color=INK_2, annotation_font_size=11)

    fig.add_scatter(x=call_strikes, y=call_delta_pct, name="Call |Δ|",
                    mode="markers+lines",
                    line=dict(color=ACCENT_UP, width=1.5, dash=CALL_DASH),
                    marker=dict(color=ACCENT_UP, size=8, symbol=CALL_MARKER),
                    hovertemplate="Strike %{x:,.0f}<br>"
                                  "Call |Δ| %{y:.1f}<extra></extra>")
    fig.add_scatter(x=put_strikes, y=put_delta_pct, name="Put |Δ|",
                    mode="markers+lines",
                    line=dict(color=ACCENT_DOWN, width=1.5, dash=PUT_DASH),
                    marker=dict(color=ACCENT_DOWN, size=8, symbol=PUT_MARKER),
                    hovertemplate="Strike %{x:,.0f}<br>Put |Δ| %{y:.1f}<extra></extra>")

    apply_layout(fig, height=360, x_title="Strike", y_title="|Delta| × 100")
    fig.update_layout(hovermode="closest")
    fig.update_yaxes(range=[0, 100])
    add_spot_line(fig, spot)
    return fig
