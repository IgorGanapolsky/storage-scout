from __future__ import annotations

from pathlib import Path

from autonomy.tools.live_job_daemon import compact_jsonl_file


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
