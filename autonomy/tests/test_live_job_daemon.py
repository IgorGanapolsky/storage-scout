from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from autonomy.tools import live_job_daemon
from autonomy.tools.live_job_daemon import CompactionResult, compact_jsonl_file


def _write_lines(path: Path, count: int) -> list[str]:
    lines = [f'{{"n":{idx},"msg":"line-{idx}"}}\n' for idx in range(count)]
    path.write_text("".join(lines), encoding="utf-8")
    return lines


def test_compact_jsonl_file_keeps_tail_and_archives_head(tmp_path: Path) -> None:
    log_path = tmp_path / "audit.jsonl"
    lines = _write_lines(log_path, 12)

    result = compact_jsonl_file(
        path=log_path,
        max_bytes=10,
        keep_tail_lines=5,
    )
    assert result.compacted is True
    assert result.lines_before == 12
    assert result.lines_kept == 5
    assert result.lines_archived == 7
    assert result.archived_path != ""

    kept = log_path.read_text(encoding="utf-8").splitlines()
    assert kept == [line.strip() for line in lines[-5:]]

    archived = Path(result.archived_path).read_text(encoding="utf-8").splitlines()
    assert archived == [line.strip() for line in lines[:7]]


def test_compact_jsonl_file_noop_below_threshold(tmp_path: Path) -> None:
    log_path = tmp_path / "small.jsonl"
    lines = _write_lines(log_path, 3)

    result = compact_jsonl_file(
        path=log_path,
        max_bytes=1_000_000,
        keep_tail_lines=2,
    )
    assert result.compacted is False
    assert result.archived_path == ""
    assert log_path.read_text(encoding="utf-8").splitlines() == [line.strip() for line in lines]


def test_compact_jsonl_file_missing_path_returns_noop(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    result = compact_jsonl_file(path=missing, max_bytes=1, keep_tail_lines=10)
    assert result.compacted is False
    assert result.path == str(missing.resolve())
    assert result.bytes_before == 0
    assert result.bytes_after == 0


def test_compact_jsonl_file_noop_when_tail_keeps_all_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "small.jsonl"
    _write_lines(log_path, 3)
    result = compact_jsonl_file(path=log_path, max_bytes=10, keep_tail_lines=10)
    assert result.compacted is False
    assert result.lines_before == 3
    assert result.lines_archived == 0


def test_run_live_job_once_passes_expected_command(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    tool_path = repo_root / "autonomy" / "tools"
    tool_path.mkdir(parents=True, exist_ok=True)
    (tool_path / "live_job.py").write_text("print('ok')\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(live_job_daemon.subprocess, "run", _fake_run)
    rc = live_job_daemon.run_live_job_once(
        repo_root=repo_root,
        config_rel="autonomy/state/config.json",
        env_file=".env",
    )
    assert rc == 7
    assert str((tool_path / "live_job.py").resolve()) in seen["cmd"]  # type: ignore[index]
    assert "--config" in seen["cmd"]  # type: ignore[operator]
    assert "--env-file" in seen["cmd"]  # type: ignore[operator]
    assert seen["kwargs"]["check"] is False  # type: ignore[index]
    assert seen["kwargs"]["cwd"] == str(repo_root)  # type: ignore[index]


def test_compact_many_handles_errors_and_blank_entries(monkeypatch, tmp_path: Path) -> None:
    ok_path = tmp_path / "ok.jsonl"
    bad_path = tmp_path / "bad.jsonl"
    ok_path.write_text('{"ok":true}\n', encoding="utf-8")
    bad_path.write_text('{"bad":true}\n', encoding="utf-8")

    def _fake_compact_jsonl_file(*, path, max_bytes, keep_tail_lines):  # noqa: ANN001, ANN003
        if path == bad_path.resolve():
            raise RuntimeError("boom")
        return CompactionResult(
            path=str(path),
            archived_path="",
            compacted=False,
            lines_before=1,
            lines_kept=1,
            lines_archived=0,
            bytes_before=10,
            bytes_after=10,
        )

    monkeypatch.setattr(live_job_daemon, "compact_jsonl_file", _fake_compact_jsonl_file)
    results = live_job_daemon._compact_many(
        repo_root=tmp_path,
        files=["", "ok.jsonl", str(bad_path.resolve())],
        max_bytes=100,
        keep_tail_lines=5,
    )
    assert len(results) == 2
    assert results[0].path == str(ok_path.resolve())
    assert results[1].path == str(bad_path.resolve())
    assert results[1].compacted is False
    assert results[1].bytes_before == 0


def test_main_runs_two_cycles_and_reports_payload(monkeypatch, tmp_path: Path, capsys) -> None:
    calls = {"run": 0, "sleep": []}
    compaction_stub = [
        CompactionResult(
            path=str(tmp_path / "audit.jsonl"),
            archived_path="",
            compacted=False,
            lines_before=0,
            lines_kept=0,
            lines_archived=0,
            bytes_before=0,
            bytes_after=0,
        )
    ]

    def _fake_run_live_job_once(*, repo_root, config_rel, env_file):  # noqa: ANN001, ANN003
        calls["run"] += 1
        return 1 if calls["run"] == 1 else 0

    def _fake_compact_many(*, repo_root, files, max_bytes, keep_tail_lines):  # noqa: ANN001, ANN003
        return compaction_stub

    def _fake_sleep(seconds):  # noqa: ANN001
        calls["sleep"].append(int(seconds))

    monkeypatch.setattr(live_job_daemon, "run_live_job_once", _fake_run_live_job_once)
    monkeypatch.setattr(live_job_daemon, "_compact_many", _fake_compact_many)
    monkeypatch.setattr(live_job_daemon.time, "sleep", _fake_sleep)
    monkeypatch.setattr(
        "sys.argv",
        [
            "live_job_daemon.py",
            "--max-cycles",
            "2",
            "--interval-seconds",
            "1",
            "--compact-files",
            "autonomy/state/audit.jsonl",
        ],
    )
    live_job_daemon.main()

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    second = json.loads(lines[1])
    assert first["cycle"] == 1
    assert second["cycle"] == 2
    assert first["exit_code"] == 1
    assert first["compaction"] == [asdict(compaction_stub[0])]
    # interval is clamped to >=15; first cycle fails so failure backoff triggers.
    assert calls["sleep"][0] == 15
