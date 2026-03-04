from __future__ import annotations

from autonomy.tools import scrapling_scraper as mod


def test_enrich_leads_batch_processes_all_leads_and_sleeps_between_calls(monkeypatch) -> None:
    leads = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}, {"id": "e"}]
    seen: list[str] = []
    sleeps: list[int] = []

    def fake_enrich(lead: dict) -> dict:
        seen.append(str(lead["id"]))
        return lead

    monkeypatch.setattr(mod, "enrich_lead", fake_enrich)
    monkeypatch.setattr(mod.time, "sleep", lambda secs: sleeps.append(int(secs)))

    out = mod.enrich_leads_batch(leads, max_per_session=2)

    assert out is leads
    assert seen == ["a", "b", "c", "d", "e"]
    assert sleeps == [1, 1, 1, 1]


def test_enrich_leads_batch_clamps_nonpositive_max_per_session(monkeypatch) -> None:
    leads = [{"id": "x"}, {"id": "y"}]
    seen: list[str] = []
    sleeps: list[int] = []

    monkeypatch.setattr(mod, "enrich_lead", lambda lead: seen.append(str(lead["id"])) or lead)
    monkeypatch.setattr(mod.time, "sleep", lambda secs: sleeps.append(int(secs)))

    mod.enrich_leads_batch(leads, max_per_session=0)

    assert seen == ["x", "y"]
    assert sleeps == [1]
