from __future__ import annotations

from pathlib import Path

from autonomy.tools.live_job import _resolve_config_path


def test_resolve_config_path_falls_back_for_default_relative(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy").mkdir(parents=True, exist_ok=True)
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)
    alt = repo_root / "autonomy" / "config.callcatcherops.json"
    alt.write_text("{}", encoding="utf-8")

    cfg = _resolve_config_path(repo_root=repo_root, config_arg="autonomy/state/config.callcatcherops.live.json")
    assert cfg == alt.resolve()


def test_resolve_config_path_falls_back_for_default_absolute(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy").mkdir(parents=True, exist_ok=True)
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)
    alt = repo_root / "autonomy" / "config.callcatcherops.json"
    alt.write_text("{}", encoding="utf-8")

    live_abs = (repo_root / "autonomy" / "state" / "config.callcatcherops.live.json").resolve()
    cfg = _resolve_config_path(repo_root=repo_root, config_arg=str(live_abs))
    assert cfg == alt.resolve()


def test_resolve_config_path_does_not_fallback_for_custom_path(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy").mkdir(parents=True, exist_ok=True)
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)
    (repo_root / "autonomy" / "config.callcatcherops.json").write_text("{}", encoding="utf-8")

    cfg = _resolve_config_path(repo_root=repo_root, config_arg="custom.json")
    assert cfg == (repo_root / "custom.json").resolve()


def test_resolve_config_path_prefers_live_when_present(tmp_path: Path) -> None:
    repo_root = tmp_path
    (repo_root / "autonomy").mkdir(parents=True, exist_ok=True)
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)
    live = repo_root / "autonomy" / "state" / "config.callcatcherops.live.json"
    live.write_text("{}", encoding="utf-8")
    (repo_root / "autonomy" / "config.callcatcherops.json").write_text("{}", encoding="utf-8")

    cfg = _resolve_config_path(repo_root=repo_root, config_arg="autonomy/state/config.callcatcherops.live.json")
    assert cfg == live.resolve()

