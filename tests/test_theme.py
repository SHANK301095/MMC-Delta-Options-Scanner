"""Tests for the design system and the charting rules.

Two kinds of thing are covered here. First, the theme helpers - they render
through `unsafe_allow_html`, so their escaping has to be tested. Second, the two
rules charts.py sets out in its own docstring: one chart, one y-axis; and calls
and puts are never separated by colour alone. Both are the kind of rule that
quietly breaks next time without a test holding it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mmc_core import charts as ch
from mmc_core import theme

REPO_ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------- escaping

@pytest.mark.parametrize("raw, must_not_contain", [
    ("<script>alert(1)</script>", "<script>"),
    ('" onmouseover="x', ' onmouseover="'),
    ("<b>bold</b>", "<b>"),
])
def test_components_escape_their_input(raw, must_not_contain):
    """These components run through unsafe_allow_html and their labels come
    from the chain - symbols, expiry names, API error messages. Without
    escaping, a single unclosed tag can break the whole layout."""
    for markup in (theme.stat("label", raw), theme.stat(raw, "value"),
                   theme.badge(raw, "good"), theme.section(raw),
                   theme.empty_state("i", raw, raw),
                   theme.hero("label", raw), theme.nav_card("i", raw, raw)):
        assert must_not_contain not in markup


def test_escaping_keeps_the_text_readable():
    assert "a &amp; b" in theme.stat("x", "a & b")
    assert "1 &lt; 2" in theme.badge("1 < 2", "good")


# --------------------------------------------------------------- badges

@pytest.mark.parametrize("tone", ["good", "warn", "serious", "critical", "neutral"])
def test_every_badge_carries_a_shape_and_a_word_not_just_colour(tone):
    """Status can never rest on colour alone: on light surfaces warning and
    serious fall below 3:1, and under CVD two status colours can converge. So
    every badge carries both a shape dot and the full word."""
    markup = theme.badge("REGIME OK", tone)
    assert "REGIME OK" in markup
    assert 'class="dot"' in markup
    colour, dot = theme._STATUS[tone]
    assert dot in markup
    assert colour in markup


def test_unknown_tone_falls_back_to_neutral_not_to_a_status_colour():
    """A typo must not quietly become "good"."""
    markup = theme.badge("x", "banana")
    assert theme.STATUS_GOOD not in markup
    assert theme.INK_3 in markup


def test_status_colours_are_never_reused_as_series_colours():
    series = {theme.ACCENT_UP, theme.ACCENT_DOWN, theme.SERIES_1, theme.SERIES_2}
    status = {theme.STATUS_GOOD, theme.STATUS_WARN,
              theme.STATUS_SERIOUS, theme.STATUS_CRITICAL}
    assert series.isdisjoint(status)


# ---------------------------------------------------------------- stats

@pytest.mark.parametrize("value, good_when_positive, expected", [
    (5.0, True, "up"), (-5.0, True, "down"),
    (5.0, False, "down"), (-5.0, False, "up"),
    (0.0, True, ""), (float("nan"), True, ""),
    (None, True, ""), ("abc", True, ""),
])
def test_tone_for(value, good_when_positive, expected):
    assert theme.tone_for(value, good_when_positive) == expected


def test_stat_applies_the_tone_class():
    assert "mmc-stat-value up" in theme.stat("l", "v", tone="up")
    assert "mmc-stat-value down" in theme.stat("l", "v", tone="down")
    assert "mmc-stat-value\"" in theme.stat("l", "v")


def test_stat_ignores_a_tone_it_does_not_know():
    assert "mmc-stat-value\"" in theme.stat("l", "v", tone="sideways")


def test_stat_row_and_card_grid_wrap_their_children():
    assert theme.stat_row([theme.stat("a", 1)]).startswith('<div class="mmc-stats">')
    assert theme.card_grid([theme.nav_card("i", "t", "b")]).startswith(
        '<div class="mmc-cards">')


def test_hero_renders_with_and_without_a_badge():
    with_badge = theme.hero("BTC VIX", "55.3", badge_html=theme.badge("IN REGIME", "good"))
    assert "IN REGIME" in with_badge and "55.3" in with_badge
    assert "mmc-hero-badge" not in theme.hero("BTC VIX", "55.3")


# ------------------------------------------------- theme / config drift

def test_streamlit_config_colours_match_the_theme_tokens():
    """config.toml colours Streamlit's own widgets; theme.py colours our CSS
    and charts. If the two drift, the app splits into two halves - and that is
    hard to catch by eye, so the machine catches it."""
    text = (REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")

    def value_of(key):
        found = re.search(rf'^{key}\s*=\s*"([^"]+)"', text, re.MULTILINE)
        assert found, f"{key} not found in config.toml"
        return found.group(1).lower()

    assert value_of("base") == "dark"
    assert value_of("backgroundColor") == theme.SURFACE_0
    assert value_of("secondaryBackgroundColor") == theme.SURFACE_1
    assert value_of("textColor") == theme.INK_1
    assert value_of("primaryColor") == theme.SERIES_1


def test_injected_css_is_built_from_the_tokens():
    css = theme._css()
    for token in (theme.SURFACE_0, theme.SURFACE_1, theme.INK_1,
                  theme.ACCENT_UP, theme.ACCENT_DOWN):
        assert token in css


def test_tables_ask_for_tabular_figures():
    """Without tabular figures an option chain's digits shift row to row, and
    comparing two prices by eye becomes impossible."""
    assert "tabular-nums" in theme._css()


# ------------------------------------------------------- chart contracts

def _all_figures():
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]
    ones = [1.0] * 5
    return {
        "oi_profile": ch.oi_profile(strikes, ones, ones, 100.0),
        "volatility_smile": ch.volatility_smile(strikes, ones, strikes, ones,
                                                100.0, strikes, ones),
        "term_structure": ch.term_structure(["a", "b"], [50.0, 55.0], [7.0, 30.0]),
        "decay_curve": ch.decay_curve([1.0, 2.0], [10.0, 8.0], [0.0, 2.0]),
        "burn_bars": ch.burn_bars([1.0, 2.0], [1.0, 2.0]),
        "payoff_diagram": ch.payoff_diagram(strikes, [-1.0, 0.0, 1.0, 2.0, 3.0],
                                            100.0, [0.0] * 5, [95.0]),
        "spread_heat": ch.spread_heat(strikes, [5.0, 30.0, 5.0, 5.0, 40.0],
                                      100.0, 25.0),
        "delta_profile": ch.delta_profile(strikes, ones, strikes, ones, 100.0,
                                          (20.0, 30.0)),
    }


@pytest.mark.parametrize("name", list(_all_figures()))
def test_no_chart_has_a_second_y_axis(name):
    """Two y-scales on one plot is the most expensive charting mistake: the
    alignment is arbitrary, so the chart shows a relationship the data does not
    contain. decay_curve used to make exactly this mistake."""
    layout = _all_figures()[name].layout
    assert "yaxis2" not in layout
    assert not any(getattr(layout[k], "overlaying", None)
                   for k in layout if str(k).startswith("yaxis"))


def test_decay_curve_keeps_both_series_on_one_axis():
    """Premium remaining and cumulative burn are both rupees per lot and are
    two halves of one quantity - a single axis is the only honest option."""
    fig = ch.decay_curve([1.0, 2.0], [10.0, 8.0], [0.0, 2.0])
    assert len(fig.data) == 2
    assert all(trace.yaxis in (None, "y") for trace in fig.data)


@pytest.mark.parametrize("name", ["volatility_smile", "delta_profile"])
def test_calls_and_puts_differ_by_more_than_colour(name):
    """Green for calls and red for puts is the market's own language, but it is
    also the pair that separates worst under protanopia (CVD dE 6.5, inside the
    warn band). So a second channel alongside colour is mandatory: marker shape
    or line dash."""
    fig = _all_figures()[name]
    call = next(t for t in fig.data if t.name and t.name.startswith("Call"))
    put = next(t for t in fig.data if t.name and t.name.startswith("Put"))

    shape_differs = call.marker.symbol != put.marker.symbol
    dash_differs = (getattr(call.line, "dash", None)
                    != getattr(put.line, "dash", None))
    assert shape_differs or dash_differs, (
        f"{name}: calls and puts are separated by colour alone")


def test_every_multi_series_chart_keeps_its_legend():
    """With two or more series, identity is never left to colour alone."""
    for name, fig in _all_figures().items():
        named = [t for t in fig.data if t.name and t.showlegend is not False]
        if len(named) >= 2:
            assert fig.layout.showlegend is not False, f"{name} is missing its legend"


def test_spot_reference_line_is_ink_not_a_series_colour():
    """A reference line's job is to mark a position, not to compete with the
    series - otherwise it consumes a free colour slot."""
    fig = ch.oi_profile([90.0, 100.0], [1.0, 1.0], [1.0, 1.0], 95.0)
    vlines = [sh for sh in fig.layout.shapes if sh.type == "line"]
    assert vlines
    series = {theme.ACCENT_UP, theme.ACCENT_DOWN, theme.SERIES_1, theme.SERIES_2}
    for shape in vlines:
        assert shape.line.color not in series


# --------------------------------------------------------- table height

@pytest.mark.parametrize("rows, expected", [
    (0, 120), (1, 120), (2, 120),        # holds at the minimum
    (8, 40 + 8 * 35),                    # grows with the content
    (500, 460),                          # stops at the cap, then scrolls
])
def test_table_height_grows_with_rows_then_caps(rows, expected):
    assert theme.table_height(rows) == expected


@pytest.mark.parametrize("bad", [None, "abc", float("nan")])
def test_table_height_on_junk_input_is_still_usable(bad):
    assert theme.table_height(bad) == 120


def test_table_height_respects_a_custom_cap():
    assert theme.table_height(500, max_px=560) == 560
