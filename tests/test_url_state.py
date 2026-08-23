"""URL view-state ke tests.

URL params bahar se aate hain — koi bhi kuch bhi bhej sakta hai. Isliye yahan
ka asli kaam ye check karna hai ki galat value CHUP-CHAAP GIRE, guess na ho:
ek kharab param se app default par chale, crash na kare aur galat view na
dikhaye.
"""

from __future__ import annotations

import pytest

from mmc_core import url_state as us


# ------------------------------------------------------------- round trip

def test_a_full_view_survives_encode_then_decode():
    """Link bhejne ka poora point yahi hai: kholne wale ko wahi screen mile."""
    state = {
        "underlying": "BTC",
        "expiry_api_date": "29-08-2026",
        "price_mode": "Mid",
        "usdinr": 88.5,
        "delta_band_main": (15, 25),
        "vol_regime_band": (40, 80),
    }
    assert us.decode(us.encode(state)) == state


def test_encode_leaves_out_what_it_does_not_know():
    """URL `?u=&e=&p=` jaise khaali kachre se nahi bharni chahiye."""
    assert us.encode({"underlying": "BTC"}) == {"u": "BTC"}
    assert us.encode({}) == {}


@pytest.mark.parametrize("junk", [None, "abc", 42, [], "u=BTC"])
def test_decode_and_encode_survive_non_dict_input(junk):
    assert us.decode(junk) == {}
    assert us.encode(junk) == {}


# ---------------------------------------------------------- underlying

@pytest.mark.parametrize("raw, expected", [
    ("btc", "BTC"), ("  eth  ", "ETH"), ("SOL", "SOL"),
])
def test_underlying_is_normalised(raw, expected):
    assert us.decode({"u": raw})["underlying"] == expected


@pytest.mark.parametrize("bad", [
    "<script>alert(1)</script>", "BTC-USD", "", "   ",
    "A" * 20, 123, None, "../../etc/passwd",
])
def test_a_bad_underlying_is_dropped_not_guessed(bad):
    assert "underlying" not in us.decode({"u": bad})


# --------------------------------------------------------------- expiry

def test_expiry_accepts_the_api_date_format():
    assert us.decode({"e": "01-01-2027"})["expiry_api_date"] == "01-01-2027"


@pytest.mark.parametrize("bad", [
    "2026-08-29",      # ulta format
    "1-8-2026",        # padding nahi
    "29-13-2026",      # month 13
    "32-08-2026",      # day 32
    "00-08-2026",      # day 0
    "aa-bb-cccc", "29-08", "", None, 20260829,
])
def test_a_bad_expiry_is_dropped(bad):
    assert "expiry_api_date" not in us.decode({"e": bad})


# ---------------------------------------------------------- price basis

@pytest.mark.parametrize("code, label", [
    ("realistic", "Realistic (buy ask / sell bid)"),
    ("mid", "Mid"), ("mark", "Mark"), ("MARK", "Mark"), (" mid ", "Mid"),
])
def test_price_codes_map_to_the_labels_the_app_uses(code, label):
    assert us.decode({"p": code})["price_mode"] == label


@pytest.mark.parametrize("bad", ["theoretical", "", None, 1, "realistic!"])
def test_an_unknown_price_code_is_dropped(bad):
    assert "price_mode" not in us.decode({"p": bad})


def test_every_price_code_round_trips():
    for code, label in us.PRICE_CODES.items():
        assert us.encode({"price_mode": label})["p"] == code


# ----------------------------------------------------------------- fx

@pytest.mark.parametrize("raw, expected", [
    ("88.5", 88.5), ("50", 50.0), ("150", 150.0),
    ("10", 50.0),        # neeche se clamp
    ("9999", 150.0),     # upar se clamp
])
def test_usdinr_is_clamped_into_a_sane_range(raw, expected):
    """Ek galat rate har ₹ number ko chup-chaap galat kar deta hai, isliye
    clamp — reject nahi, kyunki nazdeeki value abhi bhi kaam ki hai."""
    assert us.decode({"fx": raw})["usdinr"] == expected


@pytest.mark.parametrize("bad", ["abc", "", None, "nan", "inf", "-inf"])
def test_a_non_numeric_rate_is_dropped(bad):
    assert "usdinr" not in us.decode({"fx": bad})


# --------------------------------------------------------------- bands

def test_a_band_round_trips():
    assert us.decode({"d": "15-25"})["delta_band_main"] == (15, 25)
    assert us.decode({"v": "40-80"})["vol_regime_band"] == (40, 80)


def test_a_reversed_band_is_read_as_a_range():
    """(25, 15) bhejne par user ka matlab wahi hai jo (15, 25) ka hai."""
    assert us.decode({"d": "25-15"})["delta_band_main"] == (15, 25)


def test_band_values_are_clamped_to_the_slider_range():
    assert us.decode({"d": "0-500"})["delta_band_main"] == (0, 100)
    assert us.decode({"d": "200-300"})["delta_band_main"] == (100, 100)


@pytest.mark.parametrize("ambiguous", ["-50-500", "15--25", "-15-25"])
def test_a_band_with_negatives_is_dropped_not_guessed(ambiguous):
    """Sliders 0-100 par hain; "-50" ka matlab hi nahi, aur aisi string do
    tarah se padhi ja sakti hai. Do matlab wali input guess nahi karni."""
    assert "delta_band_main" not in us.decode({"d": ambiguous})


@pytest.mark.parametrize("bad", ["", "15", "abc-def", None, 15, "15-", "-"])
def test_a_malformed_band_is_dropped(bad):
    assert "delta_band_main" not in us.decode({"d": bad})


# ------------------------------------------------------- partial links

def test_one_bad_param_does_not_discard_the_good_ones():
    """Ek tooti hui key poore link ko bekaar nahi karni chahiye."""
    out = us.decode({"u": "BTC", "e": "garbage", "fx": "88"})
    assert out["underlying"] == "BTC"
    assert out["usdinr"] == 88.0
    assert "expiry_api_date" not in out


def test_unknown_params_are_ignored():
    """Analytics ya tracking params link mein aa jaate hain — unse app ko
    farak nahi padna chahiye."""
    out = us.decode({"u": "BTC", "utm_source": "whatsapp", "fbclid": "xyz"})
    assert out == {"underlying": "BTC"}
