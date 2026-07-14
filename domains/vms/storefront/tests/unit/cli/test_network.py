from __future__ import annotations

from tests._settings_overrides import settings_overrides


def test_network_join_no_id_no_config(monkeypatch, runner, app):
    import market_storefront.groups.network as network_group

    monkeypatch.setattr(network_group, "run_step", lambda *_args, **_kwargs: None)

    with settings_overrides(zerotier_network=""):
        result = runner.invoke(app, ["network", "join"])

    assert result.exit_code == 2
    assert "No network_id" in result.output


def test_network_join_from_argument(monkeypatch, runner, app):
    import market_storefront.groups.network as network_group

    calls: list[dict] = []
    monkeypatch.setattr(
        network_group,
        "run_step",
        lambda label, cmd, cwd, **kwargs: calls.append({"label": label, "cmd": cmd, "cwd": cwd, "kwargs": kwargs}),
    )

    result = runner.invoke(app, ["network", "join", "zt123"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["make", "join", "NETWORK_ID=zt123"]


def test_network_join_from_config(monkeypatch, runner, app):
    import market_storefront.groups.network as network_group

    calls: list[dict] = []
    monkeypatch.setattr(
        network_group,
        "run_step",
        lambda label, cmd, cwd, **kwargs: calls.append({"label": label, "cmd": cmd, "cwd": cwd, "kwargs": kwargs}),
    )

    with settings_overrides(zerotier_network="zt-config"):
        result = runner.invoke(app, ["network", "join"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["make", "join", "NETWORK_ID=zt-config"]


def test_network_get_peers(monkeypatch, runner, app):
    import market_storefront.groups.network as network_group

    calls: list[dict] = []
    monkeypatch.setattr(
        network_group,
        "run_step",
        lambda label, cmd, cwd, **kwargs: calls.append({"label": label, "cmd": cmd, "cwd": cwd, "kwargs": kwargs}),
    )

    result = runner.invoke(app, ["network", "get-peers"])

    assert result.exit_code == 0
    assert calls[0]["cmd"] == ["make", "get-peers"]
