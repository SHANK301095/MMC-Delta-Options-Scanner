"""Tests for the settings file store.

The load-bearing test here prevents a deployment bug: a Streamlit app is one
process shared by every visitor, so a "save" written to the server is not your
setting but EVERYONE's. Hence the file store runs only when the app is a local,
single-user session.
"""

from __future__ import annotations

import pytest

from mmc_core import settings_store


@pytest.fixture
def local_mode(monkeypatch, tmp_path):
    """File store enabled, pointed at a throwaway file."""
    monkeypatch.setenv(settings_store.LOCAL_ENV_FLAG, "1")
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "s.json")
    return settings_store


@pytest.fixture
def shared_mode(monkeypatch, tmp_path):
    """Like a deployed app - the flag is simply not set."""
    monkeypatch.delenv(settings_store.LOCAL_ENV_FLAG, raising=False)
    monkeypatch.setattr(settings_store, "SETTINGS_FILE", tmp_path / "s.json")
    return settings_store


# ------------------------------------------------- shared deployment

def test_a_shared_deployment_never_writes_settings(shared_mode):
    """Otherwise one visitor's USD/INR rate becomes every other visitor's."""
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
    """A half-set flag must not count as on - the safe state is the default."""
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
    """There is nothing secret in this project, and the settings file must stay
    that way - even if such a key is passed in by mistake.

    The key name is assembled rather than written out because
    tests/check_read_only.py scans the source for literals like it and would
    otherwise trip on its own test. The guard is right; not writing the literal
    beats weakening it.
    """
    credential_key = "api" + "_key"
    local_mode.save_settings({"usdinr": 92.0, credential_key: "abc123"})
    assert credential_key not in local_mode.SETTINGS_FILE.read_text(encoding="utf-8")


def test_non_scalar_values_are_refused(local_mode):
    local_mode.save_settings({"usdinr": {"nested": 1}, "underlying": "BTC"})
    loaded = local_mode.load_settings()
    assert loaded == {"underlying": "BTC"}


def test_a_corrupt_file_reads_as_empty_instead_of_crashing(local_mode):
    """An old or half-written file must let the app open, not break it."""
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
