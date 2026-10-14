from __future__ import annotations

from pathlib import Path

import pytest

from gws_mcp.config import ConfigError, load_config


def test_single_account_is_default(single_account, write_config):
    config = load_config(write_config(single_account))
    account = config.resolve_account()
    assert account.alias == "work"
    assert account.email == "me@example.com"


def test_write_is_off_by_default(single_account, write_config):
    config = load_config(write_config(single_account))
    assert config.resolve_account().write is False


def test_paths_are_expanded(single_account, write_config):
    config = load_config(write_config(single_account))
    assert config.resolve_account().client_secrets == Path.home() / "clients/work.json"
    assert "~" not in str(config.downloads.dir)


def test_multiple_accounts_without_default_requires_explicit_account(two_accounts, write_config):
    config = load_config(write_config(two_accounts))
    with pytest.raises(ConfigError, match="no default_account"):
        config.resolve_account()
    assert config.resolve_account("home").email == "me@home.example"


def test_default_account_is_used(two_accounts, write_config):
    config = load_config(write_config('default_account = "home"\n' + two_accounts))
    assert config.resolve_account().alias == "home"
    assert config.resolve_account("work").write is True


def test_unknown_account_lists_available(two_accounts, write_config):
    config = load_config(write_config(two_accounts))
    with pytest.raises(ConfigError, match="Available accounts: work, home"):
        config.resolve_account("nope")


def test_default_account_must_exist(single_account, write_config):
    with pytest.raises(ConfigError, match="not a defined account"):
        load_config(write_config('default_account = "nope"\n' + single_account))


def test_no_accounts_is_an_error(write_config):
    with pytest.raises(ConfigError):
        load_config(write_config("[accounts]\n"))


@pytest.mark.parametrize("alias", ["Work", "has space", "x" * 40])
def test_invalid_alias_rejected(write_config, alias):
    body = f'[accounts."{alias}"]\nemail = "a@b.c"\nclient_secrets = "/x.json"\n'
    with pytest.raises(ConfigError, match="alias"):
        load_config(write_config(body))


def test_unknown_keys_rejected(single_account, write_config):
    with pytest.raises(ConfigError, match="writ"):
        load_config(write_config(single_account + "    writ = true\n"))


def test_missing_file_has_helpful_message(tmp_path):
    with pytest.raises(ConfigError, match="config.example.toml"):
        load_config(tmp_path / "missing.toml")


def test_invalid_toml(write_config):
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write_config("this is = = not toml"))


def test_config_path_env_override(single_account, write_config, monkeypatch):
    path = write_config(single_account)
    monkeypatch.setenv("GWS_MCP_CONFIG", str(path))
    assert load_config().resolve_account().alias == "work"
