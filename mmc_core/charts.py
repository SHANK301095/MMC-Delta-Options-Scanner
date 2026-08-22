"""
MMC Delta Scanner - Chart Layer
===============================
All charts go through here so that every page shares one visual language and
one set of colour semantics.

Colour semantics (consistent everywhere - never reused for anything else):
    GREEN  -> calls, profit, decay working in your favour
    RED    -> puts, loss, decay working against you
    BLUE   -> spot / reference lines
    AMBER  -> warnings, illiquid, stale
    PURPLE -> model / theoretical values
"""

from __future__ import annotations

import plotly.graph_objects as go

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

C_CALL = "#00cc96"
C_PUT = "#ef553b"
C_SPOT = "#636efa"
C_WARN = "#ffa15a"
C_MODEL = "#ab63fa"
C_NEUTRAL = "#8c9aa8"
C_GRID = "rgba(140,154,168,0.18)"
C_ZERO = "rgba(140,154,168,0.55)"

PROFIT_FILL = "rgba(0,204,150,0.22)"
LOSS_FILL = "rgba(239,85,59,0.22)"


def base_layout(title: str = "", height: int = 380,
                x_title: str = "", y_title: str = "",
                show_legend: bool = True) -> dict:
    """Shared layout. Transparent background so it inherits the Streamlit theme."""
    return dict(
        title=dict(text=title, font=dict(size=15)) if title else None,
        height=height,
        margin=dict(l=10, r=10, t=42 if title else 16, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        showlegend=show_legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.01,
                    xanchor="right", x=1),
        xaxis=dict(title=x_title, gridcolor=C_GRID, zerolinecolor=C_ZERO),
        yaxis=dict(title=y_title, gridcolor=C_GRID, zerolinecolor=C_ZERO),
    )


def apply_layout(fig: go.Figure, **kwargs) -> go.Figure:
    layout = base_layout(**kwargs)
    layout = {k: v for k, v in layout.items() if v is not None}
    fig.update_layout(**layout)
    return fig


def add_spot_line(fig: go.Figure, spot: float, label: str = "Spot") -> go.Figure:
    """Vertical reference line at spot. Every strike-axis chart needs this."""
    fig.add_vline(x=spot, line_width=1.5, line_dash="dash", line_color=C_SPOT,
                  annotation_text=f"{label} {spot:,.0f}",
                  annotation_position="top",
                  annotation_font_color=C_SPOT, annotation_font_size=11)
    return fig


def add_zero_line(fig: go.Figure) -> go.Figure:
    fig.add_hline(y=0, line_width=1, line_color=C_ZERO)
    return fig


# --------------------------------------------------------------------------
# Chart builders
# --------------------------------------------------------------------------

def oi_profile(strikes, call_oi, put_oi, spot: float) -> go.Figure:
    """Back-to-back OI bars by strike."""
    fig = go.Figure()
    fig.add_bar(x=strikes, y=call_oi, name="Call OI",
                marker_color=C_CALL, opacity=0.85,
                hovertemplate="Strike %{x:,.0f}<br>Call OI %{y:,.0f}<extra></extra>")
    fig.add_bar(x=strikes, y=put_oi, name="Put OI",
                marker_color=C_PUT, opacity=0.85,
                hovertemplate="Strike %{x:,.0f}<br>Put OI %{y:,.0f}<extra></extra>")
    apply_layout(fig, height=320, x_title="Strike", y_title="Open Interest (contracts)")
    fig.update_layout(barmode="group", hovermode="closest")
    add_spot_line(fig, spot)
    return fig


def volatility_smile(call_strikes, call_iv, put_strikes, put_iv,
                     spot: float, blend_strikes=None, blend_iv=None) -> go.Figure:
    """IV vs strike, with the OTM-blended curve on top.

    The blended line is what desks actually quote: OTM puts below spot,
    OTM calls above. ITM quotes on a crypto chain are usually stale.
    """
    fig = go.Figure()
    fig.add_scatter(x=call_strikes, y=call_iv, name="Call IV", mode="markers",
                    marker=dict(color=C_CALL, size=7, symbol="circle"),
                    hovertemplate="Strike %{x:,.0f}<br>Call IV %{y:.1f}%<extra></extra>")
    fig.add_scatter(x=put_strikes, y=put_iv, name="Put IV", mode="markers",
                    marker=dict(color=C_PUT, size=7, symbol="diamond"),
                    hovertemplate="Strike %{x:,.0f}<br>Put IV %{y:.1f}%<extra></extra>")
    if blend_strikes is not None and blend_iv is not None and len(blend_strikes):
        fig.add_scatter(x=blend_strikes, y=blend_iv, name="OTM curve",
                        mode="lines", line=dict(color=C_MODEL, width=2.5),
                        hovertemplate="Strike %{x:,.0f}<br>IV %{y:.1f}%<extra></extra>")
    apply_layout(fig, height=400, x_title="Strike", y_title="Implied Volatility (%)")
    fig.update_layout(hovermode="closest")
    add_spot_line(fig, spot)
    return fig


def term_structure(labels, atm_iv, days_left) -> go.Figure:
    """ATM IV across expiries. Upward slope = contango, downward = backwardation."""
    fig = go.Figure()
    fig.add_scatter(x=days_left, y=atm_iv, mode="lines+markers",
                    name="ATM IV", line=dict(color=C_MODEL, width=2.5),
                    marker=dict(size=9, color=C_MODEL),
                    text=labels,
                    hovertemplate="%{text}<br>%{x:.2f} days<br>ATM IV %{y:.1f}%<extra></extra>")
    apply_layout(fig, height=330, x_title="Days to expiry",
                 y_title="ATM Implied Volatility (%)", show_legend=False)
    fig.update_layout(hovermode="closest")
    return fig


def decay_curve(hours, premium, cumulative) -> go.Figure:
    """Premium melting + cumulative burn on a twin axis."""
    fig = go.Figure()
    fig.add_scatter(x=hours, y=premium, name="Premium ₹", mode="lines",
                    line=dict(color=C_CALL, width=2.5),
                    fill="tozeroy", fillcolor=PROFIT_FILL,
                    hovertemplate="+%{x:.1f}h<br>Premium ₹%{y:,.2f}<extra></extra>")
    fig.add_scatter(x=hours, y=cumulative, name="Cumulative burn ₹",
                    mode="lines", line=dict(color=C_PUT, width=2, dash="dot"),
                    yaxis="y2",
                    hovertemplate="+%{x:.1f}h<br>Burnt ₹%{y:,.2f}<extra></extra>")
    apply_layout(fig, height=340, x_title="Hours ahead", y_title="Premium (₹ / lot)")
    fig.update_layout(yaxis2=dict(title="Cumulative burn (₹)", overlaying="y",
                                  side="right", gridcolor="rgba(0,0,0,0)"))
    return fig


def burn_bars(hours, step_burn) -> go.Figure:
    """Per-step burn. The rising right tail IS theta acceleration."""
    fig = go.Figure()
    fig.add_bar(x=hours, y=step_burn, name="Burn per step",
                marker_color=C_WARN, opacity=0.9,
                hovertemplate="+%{x:.1f}h<br>Burn ₹%{y:,.2f}<extra></extra>")
    apply_layout(fig, height=250, x_title="Hours ahead", y_title="₹ burnt in step",
                 show_legend=False)
    fig.update_layout(hovermode="closest")
    return fig


def payoff_diagram(spots, payoff_expiry, spot_now: float,
                   payoff_now=None, breakevens=None,
                   label_now: str = "Today (T+0)") -> go.Figure:
    """Classic payoff diagram with profit/loss shading and break-even markers."""
    fig = go.Figure()

    # Shade profit above zero and loss below, using two clipped traces.
    pos = [max(0.0, v) for v in payoff_expiry]
    neg = [min(0.0, v) for v in payoff_expiry]
    fig.add_scatter(x=spots, y=pos, mode="lines", line=dict(width=0),
                    fill="tozeroy", fillcolor=PROFIT_FILL,
                    showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=spots, y=neg, mode="lines", line=dict(width=0),
                    fill="tozeroy", fillcolor=LOSS_FILL,
                    showlegend=False, hoverinfo="skip")

    fig.add_scatter(x=spots, y=payoff_expiry, name="At expiry", mode="lines",
                    line=dict(color=C_SPOT, width=2.8),
                    hovertemplate="Spot %{x:,.0f}<br>P&L ₹%{y:,.0f}<extra></extra>")

    if payoff_now is not None:
        fig.add_scatter(x=spots, y=payoff_now, name=label_now, mode="lines",
                        line=dict(color=C_MODEL, width=2, dash="dot"),
                        hovertemplate="Spot %{x:,.0f}<br>P&L ₹%{y:,.0f}<extra></extra>")

    if breakevens:
        fig.add_scatter(x=breakevens, y=[0] * len(breakevens), mode="markers",
                        name="Break-even",
                        marker=dict(color=C_WARN, size=11, symbol="x",
                                    line=dict(width=1.5, color="#ffffff")),
                        hovertemplate="Break-even %{x:,.0f}<extra></extra>")

    apply_layout(fig, height=430, x_title="Spot at expiry", y_title="P&L (₹)")
    add_zero_line(fig)
    add_spot_line(fig, spot_now, label="Now")
    return fig


def spread_heat(strikes, spread_pct, spot: float, limit: float) -> go.Figure:
    """Spread % per strike, coloured by whether it passes the filter."""
    colors = [C_CALL if (s is not None and s == s and s <= limit) else C_WARN
              for s in spread_pct]
    fig = go.Figure()
    fig.add_bar(x=strikes, y=spread_pct, marker_color=colors,
                hovertemplate="Strike %{x:,.0f}<br>Spread %{y:.1f}%<extra></extra>")
    fig.add_hline(y=limit, line_dash="dash", line_color=C_PUT, line_width=1.5,
                  annotation_text=f"Filter {limit:.0f}%",
                  annotation_font_color=C_PUT, annotation_font_size=11)
    apply_layout(fig, height=280, x_title="Strike", y_title="Bid-ask spread (%)",
                 show_legend=False)
    fig.update_layout(hovermode="closest")
    add_spot_line(fig, spot)
    return fig


def delta_profile(call_strikes, call_delta_pct, put_strikes, put_delta_pct,
                  spot: float, band: tuple | None = None) -> go.Figure:
    """|Δ| × 100 vs strike, chuni hui delta band shaded.

    Delta band ek abstract number hai; ye chart use chain par jagah deta hai —
    turant dikh jaata hai ki 20-30Δ maangne par aap spot se kitne door ja rahe
    hain, aur us range mein contracts hain bhi ya nahi.
    """
    fig = go.Figure()

    if band is not None:
        lo, hi = float(band[0]), float(band[1])
        fig.add_hrect(y0=lo, y1=hi, fillcolor=C_MODEL, opacity=0.13,
                      line_width=0, layer="below",
                      annotation_text=f"Band {lo:.0f}Δ – {hi:.0f}Δ",
                      annotation_position="top left",
                      annotation_font_color=C_MODEL, annotation_font_size=11)

    fig.add_scatter(x=call_strikes, y=call_delta_pct, name="Call |Δ|",
                    mode="markers+lines",
                    line=dict(color=C_CALL, width=1.5),
                    marker=dict(color=C_CALL, size=7, symbol="circle"),
                    hovertemplate="Strike %{x:,.0f}<br>Call |Δ| %{y:.1f}<extra></extra>")
    fig.add_scatter(x=put_strikes, y=put_delta_pct, name="Put |Δ|",
                    mode="markers+lines",
                    line=dict(color=C_PUT, width=1.5, dash="dot"),
                    marker=dict(color=C_PUT, size=7, symbol="diamond"),
                    hovertemplate="Strike %{x:,.0f}<br>Put |Δ| %{y:.1f}<extra></extra>")

    apply_layout(fig, height=360, x_title="Strike", y_title="|Delta| × 100")
    fig.update_layout(hovermode="closest", yaxis=dict(range=[0, 100],
                                                      gridcolor=C_GRID,
                                                      zerolinecolor=C_ZERO,
                                                      title="|Delta| × 100"))
    add_spot_line(fig, spot)
    return fig
