import json

import mcp_config


def write(tmp_path, data):
    path = tmp_path / ".mcp.json"
    path.write_text(json.dumps(data))
    return path


def test_env_vars_are_expanded_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    path = write(tmp_path, {"mcpServers": {"github": {"env": {"TOKEN": "${GITHUB_TOKEN}"}}}})

    assert mcp_config.load(path)["github"]["env"]["TOKEN"] == "ghp_secret"


def test_the_secret_is_never_in_the_committed_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    path = write(tmp_path, {"mcpServers": {"github": {"env": {"TOKEN": "${GITHUB_TOKEN}"}}}})
    mcp_config.load(path)

    assert "ghp_secret" not in path.read_text()


def test_expansion_reaches_into_lists(tmp_path, monkeypatch):
    monkeypatch.setenv("REGION", "eu")
    path = write(tmp_path, {"mcpServers": {"s": {"args": ["--region", "${REGION}"]}}})

    assert mcp_config.load(path)["s"]["args"] == ["--region", "eu"]


def test_an_unset_variable_resolves_to_empty_rather_than_crashing(tmp_path, monkeypatch):
    monkeypatch.delenv("NOT_SET", raising=False)
    path = write(tmp_path, {"mcpServers": {"s": {"env": {"T": "${NOT_SET}"}}}})

    assert mcp_config.load(path)["s"]["env"]["T"] == ""


def test_unset_variables_are_named_so_the_loss_is_not_silent(tmp_path, monkeypatch):
    monkeypatch.delenv("NOT_SET", raising=False)
    monkeypatch.setenv("SET_ONE", "x")
    path = write(tmp_path, {"mcpServers": {"s": {"env": {"A": "${NOT_SET}", "B": "${SET_ONE}"}}}})

    assert mcp_config.missing_credentials(path) == ["NOT_SET"]


def test_a_missing_config_is_not_an_error(tmp_path):
    assert mcp_config.load(tmp_path / "absent.json") == {}
    assert mcp_config.missing_credentials(tmp_path / "absent.json") == []
