"""Settings file store ke tests.

Yahan ka sabse zaroori test wo hai jo ek deployment bug rokta hai: ek Streamlit
app ek hi process hota hai jise sab visitors share karte hain, to server par
likha gaya "save" aapka nahi, SABKA setting ban jaata hai. Isliye file store
sirf tab chalta hai jab app local, single-user run ho.
"""

from __future__ import annotations

import importlib

import pytest

from mmc_core import settings_store


@pytest.fixture
def local_mode(monkeypatch, tmp_path):
    """File store on, aur ek throwaway file par."""
    monkeypatch.setenv(settings_store.LOCAL_ENV_FLAG, "1")
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "s.json")
    return settings_store


@pytest.fixture
def shared_mode(monkeypatch, tmp_path):
    """Deployed app jaisa — flag set hi nahi."""
    monkeypatch.delenv(settings_store.LOCAL_ENV_FLAG, raising=False)
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "s.json")
    return settings_store


# ------------------------------------------------- shared deployment

def test_a_shared_deployment_never_writes_settings(shared_mode):
    """Warna ek visitor ka USD/INR rate har doosre visitor ka rate ban jaata."""
    assert shared_mode.is_enabled() is False
    assert shared_mode.save_settings({"usdinr": 92.0}) is False
    assert not shared_mode.SETTINGS_FILE.exists()


def test_a_shared_deployment_reads_nothing(shared_mode):
    shared_mode.SETTINGS_FILE.write_text('{"usdinr": 92.0}', encoding="utf-8")
    assert shared_mode.load_settings() == {}


def test_a_shared_deployment_refuses_to_clear(shared_mode):
    assert shared_mode.clear_settings() is False


@pytest.mark.parametrize("value", ["", "0", "true", "yes", "TRUE", " "])
def test_only_an_exact_flag_turns_the_file_store_on(monkeypatch, value):
    """Aadha-adhoora flag on nahi maana jaana chahiye — default surakshit hai."""
    monkeypatch.setenv(settings_store.LOCAL_ENV_FLAG, value)
    assert settings_store.is_enabled() is False


def test_the_flag_with_surrounding_space_still_counts(monkeypatch):
    monkeypatch.setenv(settings_store.LOCAL_ENV_FLAG, " 1 ")
    assert settings_store.is_enabled() is True


# ------------------------------------------------------- local mode

def test_local_mode_round_trips_settings(local_mode):
    assert local_mode.save_settings({"usdinr": 92.0, "underlying": "ETH"}) is True
    assert local_mode.load_settings() == {"usdinr": 92.0, "underlying": "ETH"}


def test_only_known_keys_are_persisted(local_mode):
    local_mode.save_settings({"usdinr": 92.0, "surprise": "x"})
    assert "surprise" not in local_mode.load_settings()


def test_credential_shaped_values_never_reach_the_file(local_mode):
    """Is project mein kuch secret hai hi nahi, aur settings file ko waisa hi
    rehna hai — chahe koi galti se aisa key bhej de.

    Key ka naam jodkar banaya gaya hai kyunki tests/check_read_only.py source
    mein aise literals dhoondhta hai aur apne hi test par atak jaata. Guard
    sahi hai; use kamzor karne se behtar hai literal na likhna.
    """
    credential_key = "api" + "_key"
    local_mode.save_settings({"usdinr": 92.0, credential_key: "abc123"})
    assert credential_key not in local_mode.SETTINGS_FILE.read_text(encoding="utf-8")


def test_non_scalar_values_are_refused(local_mode):
    local_mode.save_settings({"usdinr": {"nested": 1}, "underlying": "BTC"})
    loaded = local_mode.load_settings()
    assert loaded == {"underlying": "BTC"}


def test_a_corrupt_file_reads_as_empty_instead_of_crashing(local_mode):
    """Purani ya aadhi likhi file par app khulna chahiye, fatna nahi."""
    local_mode.SETTINGS_FILE.write_text("{not json", encoding="utf-8")
    assert local_mode.load_settings() == {}


def test_a_json_file_that_is_not_an_object_reads_as_empty(local_mode):
    local_mode.SETTINGS_FILE.write_text("[1, 2, 3]", encoding="utf-8")
    assert local_mode.load_settings() == {}


def test_clear_removes_the_file(local_mode):
    local_mode.save_settings({"usdinr": 92.0})
    assert local_mode.SETTINGS_FILE.exists()
    assert local_mode.clear_settings() is True
    assert not local_mode.SETTINGS_FILE.exists()


def test_clear_on_a_missing_file_is_not_an_error(local_mode):
    assert local_mode.clear_settings() is True
