from __future__ import annotations

import sys
from pathlib import Path

import autonomy.run as run_entry


def test_run_main_uses_default_live_config_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_load_config(path: str) -> dict[str, str]:
        captured["path"] = path
        return {"mode": "live"}

    class _FakeEngine:
        def __init__(self, cfg) -> None:  # noqa: ANN001
            captured["cfg"] = cfg

        def run(self) -> dict[str, int]:
            return {"sent_initial": 0, "sent_followup": 0}

    monkeypatch.setattr(run_entry, "load_config", _fake_load_config)
    monkeypatch.setattr(run_entry, "Engine", _FakeEngine)
    monkeypatch.setattr(sys, "argv", ["run.py"])

    run_entry.main()

    expected = (Path(run_entry.__file__).resolve().parents[1] / "autonomy" / "state" / "config.ai-seo.live.json").resolve()
    assert captured["path"] == str(expected)
    assert captured["cfg"] == {"mode": "live"}


def test_run_main_resolves_relative_override_from_repo_root(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_load_config(path: str) -> dict[str, str]:
        captured["path"] = path
        return {"mode": "dry-run"}

    class _FakeEngine:
        def __init__(self, _cfg) -> None:  # noqa: ANN001
            pass

        def run(self) -> dict[str, int]:
            return {"sent_initial": 1, "sent_followup": 1}

    monkeypatch.setattr(run_entry, "load_config", _fake_load_config)
    monkeypatch.setattr(run_entry, "Engine", _FakeEngine)
    monkeypatch.setattr(sys, "argv", ["run.py", "--config", "autonomy/config.ai-seo.json"])

    run_entry.main()

    expected = (Path(run_entry.__file__).resolve().parents[1] / "autonomy" / "config.ai-seo.json").resolve()
    assert captured["path"] == str(expected)


def test_run_main_preserves_absolute_override(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}
    cfg_path = (tmp_path / "cfg.live.json").resolve()

    def _fake_load_config(path: str) -> dict[str, str]:
        captured["path"] = path
        return {"mode": "live"}

    class _FakeEngine:
        def __init__(self, _cfg) -> None:  # noqa: ANN001
            pass

        def run(self) -> dict[str, int]:
            return {"sent_initial": 2, "sent_followup": 1}

    monkeypatch.setattr(run_entry, "load_config", _fake_load_config)
    monkeypatch.setattr(run_entry, "Engine", _FakeEngine)
    monkeypatch.setattr(sys, "argv", ["run.py", "--config", str(cfg_path)])

    run_entry.main()

    assert captured["path"] == str(cfg_path)
