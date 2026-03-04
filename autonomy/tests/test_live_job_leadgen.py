from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autonomy.tools import live_job


def _cfg_with_csv(path: str) -> SimpleNamespace:
    return SimpleNamespace(lead_sources=[{"type": "csv", "path": path}])


def test_maybe_run_leadgen_uses_market_cursor_and_persists_index(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg_with_csv("autonomy/state/leads.csv")
    env = {"DAILY_LEADGEN_LIMIT": "2", "LEADGEN_DEFAULT_STATE": "FL"}
    repo_root = tmp_path
    captured: dict[str, object] = {}

    monkeypatch.setattr(live_job, "get_api_key", lambda: "fake-api-key")
    monkeypatch.setattr(live_job, "load_markets", lambda _path, default_state: [{"city": "Miami", "state": default_state}])

    def fake_load_city_index(index_key: str) -> int:
        captured["index_key"] = index_key
        return 7

    def fake_build_leads(**kwargs):  # noqa: ANN003
        captured["build_kwargs"] = kwargs
        return ([{"company": "Dental Office"}], 9)

    def fake_write_leads(path: Path, leads: list[dict], replace: bool) -> None:
        captured["write_path"] = path
        captured["write_leads"] = leads
        captured["replace"] = replace

    def fake_save_city_index(index: int, index_key: str) -> None:
        captured["saved"] = (index, index_key)

    monkeypatch.setattr(live_job, "load_city_index", fake_load_city_index)
    monkeypatch.setattr(live_job, "load_existing", lambda _path: (set(), set(), set()))
    monkeypatch.setattr(live_job, "build_leads", fake_build_leads)
    monkeypatch.setattr(live_job, "write_leads", fake_write_leads)
    monkeypatch.setattr(live_job, "save_city_index", fake_save_city_index)

    generated = live_job._maybe_run_leadgen(cfg=cfg, env=env, repo_root=repo_root)

    assert generated == 1
    assert captured["index_key"] == "default:FL"
    assert captured["saved"] == (9, "default:FL")
    assert captured["replace"] is False
    assert captured["write_path"] == (repo_root / "autonomy/state/leads.csv").resolve()
    build_kwargs = captured["build_kwargs"]
    assert build_kwargs["start_index"] == 7
    assert build_kwargs["categories"] == live_job.DEFAULT_CATEGORIES


def test_maybe_run_leadgen_returns_zero_when_markets_missing(monkeypatch, tmp_path: Path) -> None:
    cfg = _cfg_with_csv("autonomy/state/leads.csv")
    env = {"DAILY_LEADGEN_LIMIT": "1"}

    monkeypatch.setattr(live_job, "get_api_key", lambda: "fake-api-key")

    def raise_missing_markets(_path, default_state: str):  # noqa: ARG001
        raise SystemExit("No market list found.")

    monkeypatch.setattr(live_job, "load_markets", raise_missing_markets)

    generated = live_job._maybe_run_leadgen(cfg=cfg, env=env, repo_root=tmp_path)

    assert generated == 0
