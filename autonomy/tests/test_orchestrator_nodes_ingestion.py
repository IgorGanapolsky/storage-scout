from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from autonomy.orchestrator import OrchestrationState
from autonomy.orchestrator_nodes import IngestionNode


def _state(*, tmp_path: Path, env: dict[str, str], lead_sources: list[dict[str, str]]) -> OrchestrationState:
    return OrchestrationState(
        session_id="sess-1",
        repo_root=tmp_path,
        config=SimpleNamespace(lead_sources=lead_sources),
        env=env,
        sqlite_path=tmp_path / "state.sqlite",
        audit_log_path=tmp_path / "audit.log",
    )


def test_ingestion_node_skips_when_no_csv_source(tmp_path: Path) -> None:
    state = _state(tmp_path=tmp_path, env={"AUTO_LEADGEN_LIMIT": "1"}, lead_sources=[])

    out = IngestionNode().run(state)

    assert out.metadata["ingestion_skipped"] == "no_csv_source"


def test_ingestion_node_skips_when_markets_missing(monkeypatch, tmp_path: Path) -> None:
    state = _state(
        tmp_path=tmp_path,
        env={"AUTO_LEADGEN_LIMIT": "2"},
        lead_sources=[{"type": "csv", "path": "autonomy/state/leads.csv"}],
    )

    monkeypatch.setattr("autonomy.orchestrator_nodes.get_api_key", lambda: "fake-key")

    def _raise_markets(_path, default_state: str):  # noqa: ARG001
        raise SystemExit("No market list found.")

    monkeypatch.setattr("autonomy.orchestrator_nodes.load_markets", _raise_markets)

    out = IngestionNode().run(state)

    assert out.metadata["ingestion_skipped"] == "missing_markets"


def test_ingestion_node_success_writes_csv_and_saves_index(monkeypatch, tmp_path: Path) -> None:
    state = _state(
        tmp_path=tmp_path,
        env={"AUTO_LEADGEN_LIMIT": "2", "LEADGEN_DEFAULT_STATE": "FL"},
        lead_sources=[{"type": "csv", "path": "autonomy/state/leads.csv"}],
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr("autonomy.orchestrator_nodes.get_api_key", lambda: "fake-key")
    monkeypatch.setattr(
        "autonomy.orchestrator_nodes.load_markets",
        lambda _path, default_state: [{"city": "Miami", "state": default_state}],
    )
    monkeypatch.setattr("autonomy.orchestrator_nodes.load_city_index", lambda _key: 3)
    monkeypatch.setattr("autonomy.orchestrator_nodes.load_existing", lambda _path: (set(), set(), set()))

    def _build_leads(**kwargs):  # noqa: ANN003
        captured["build_kwargs"] = kwargs
        return ([{"company": "Acme Dental"}], 5)

    def _write_leads(path: Path, leads: list[dict], replace: bool) -> None:
        captured["write"] = (path, leads, replace)

    def _save_city_index(index: int, key: str) -> None:
        captured["save"] = (index, key)

    monkeypatch.setattr("autonomy.orchestrator_nodes.build_leads", _build_leads)
    monkeypatch.setattr("autonomy.orchestrator_nodes.write_leads", _write_leads)
    monkeypatch.setattr("autonomy.orchestrator_nodes.save_city_index", _save_city_index)

    out = IngestionNode().run(state)

    assert out.leads_generated == 1
    assert captured["save"] == (5, "default:FL")
    write_path, write_leads_payload, replace = captured["write"]
    assert write_path == (tmp_path / "autonomy/state/leads.csv").resolve()
    assert write_leads_payload == [{"company": "Acme Dental"}]
    assert replace is False
