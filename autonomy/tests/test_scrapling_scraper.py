from __future__ import annotations

from autonomy.tools import scrapling_scraper as mod


def _run_batch(monkeypatch, leads: list[dict], *, max_per_session: int) -> tuple[list[str], list[int], list[dict]]:
    seen: list[str] = []
    sleeps: list[int] = []

    def fake_enrich(lead: dict) -> dict:
        seen.append(str(lead["id"]))
        return lead

    monkeypatch.setattr(mod, "enrich_lead", fake_enrich)
    monkeypatch.setattr(mod.time, "sleep", lambda secs: sleeps.append(int(secs)))

    out = mod.enrich_leads_batch(leads, max_per_session=max_per_session)
    return seen, sleeps, out


def test_enrich_leads_batch_processes_all_leads_and_sleeps_between_calls(monkeypatch) -> None:
    leads = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}, {"id": "e"}]
    seen, sleeps, out = _run_batch(monkeypatch, leads, max_per_session=2)
    assert out is leads
    assert seen == ["a", "b", "c", "d", "e"]
    assert sleeps == [1, 1, 1, 1]

def test_enrich_leads_batch_clamps_nonpositive_max_per_session(monkeypatch) -> None:
    leads = [{"id": "x"}, {"id": "y"}]
    seen, sleeps, _ = _run_batch(monkeypatch, leads, max_per_session=0)
    assert seen == ["x", "y"]
    assert sleeps == [1]
