#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc


@dataclass(frozen=True)
class CompactionResult:
    path: str
    archived_path: str
    compacted: bool
    lines_before: int
    lines_kept: int
    lines_archived: int
    bytes_before: int
    bytes_after: int


def compact_jsonl_file(
    *,
    path: Path,
    max_bytes: int,
    keep_tail_lines: int,
) -> CompactionResult:
    target = Path(path).resolve()
    if not target.exists() or not target.is_file():
        return CompactionResult(
            path=str(target),
            archived_path="",
            compacted=False,
            lines_before=0,
            lines_kept=0,
            lines_archived=0,
            bytes_before=0,
            bytes_after=0,
        )

    bytes_before = int(target.stat().st_size)
    if bytes_before <= int(max_bytes):
        return CompactionResult(
            path=str(target),
            archived_path="",
            compacted=False,
            lines_before=0,
            lines_kept=0,
            lines_archived=0,
            bytes_before=bytes_before,
            bytes_after=bytes_before,
        )

    keep_n = max(1, int(keep_tail_lines))
    all_lines = 0
    tail = deque(maxlen=keep_n)
    with target.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            all_lines += 1
            tail.append(line)

    if all_lines <= keep_n:
        return CompactionResult(
            path=str(target),
            archived_path="",
            compacted=False,
            lines_before=all_lines,
            lines_kept=all_lines,
            lines_archived=0,
            bytes_before=bytes_before,
            bytes_after=bytes_before,
        )

    archive_dir = (target.parent / "archive").resolve()
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    archived = archive_dir / f"{target.stem}.{stamp}{target.suffix}"
    tmp = target.with_suffix(f"{target.suffix}.tmp")

    archive_limit = all_lines - keep_n
    with target.open("r", encoding="utf-8", errors="ignore") as src, archived.open("w", encoding="utf-8") as out:
        for idx, line in enumerate(src):
            if idx >= archive_limit:
                break
            out.write(line)

    with tmp.open("w", encoding="utf-8") as out:
        for line in tail:
            out.write(line)
    tmp.replace(target)

    bytes_after = int(target.stat().st_size) if target.exists() else 0
    return CompactionResult(
        path=str(target),
        archived_path=str(archived),
        compacted=True,
        lines_before=all_lines,
        lines_kept=keep_n,
        lines_archived=all_lines - keep_n,
        bytes_before=bytes_before,
        bytes_after=bytes_after,
    )


def run_live_job_once(*, repo_root: Path, config_rel: str, env_file: str) -> int:
    cmd = [
        sys.executable,
        str((repo_root / "autonomy" / "tools" / "live_job.py").resolve()),
        "--config",
        str(config_rel),
        "--env-file",
        str(env_file),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(repo_root),
        check=False,
        capture_output=False,
        text=True,
    )
    return int(completed.returncode)


def _compact_many(
    *,
    repo_root: Path,
    files: list[str],
    max_bytes: int,
    keep_tail_lines: int,
) -> list[CompactionResult]:
    results: list[CompactionResult] = []
    for rel in files:
        candidate = Path(rel.strip())
        if not str(candidate):
            continue
        path = candidate if candidate.is_absolute() else (repo_root / candidate).resolve()
        try:
            results.append(
                compact_jsonl_file(
                    path=path,
                    max_bytes=max_bytes,
                    keep_tail_lines=keep_tail_lines,
                )
            )
        except Exception:
            results.append(
                CompactionResult(
                    path=str(path),
                    archived_path="",
                    compacted=False,
                    lines_before=0,
                    lines_kept=0,
                    lines_archived=0,
                    bytes_before=0,
                    bytes_after=0,
                )
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Long-running AEO live job loop with lightweight state compaction.")
    parser.add_argument("--config", default="autonomy/state/config.ai-seo.live.json", help="Live config path.")
    parser.add_argument("--env-file", default=".env", help="Env file path.")
    parser.add_argument("--interval-seconds", type=int, default=900, help="Sleep interval between cycles.")
    parser.add_argument("--max-cycles", type=int, default=0, help="0 means run forever.")
    parser.add_argument("--compact-max-bytes", type=int, default=2_500_000, help="Compact JSONL once file exceeds this size.")
    parser.add_argument("--compact-keep-lines", type=int, default=5000, help="How many trailing lines to keep in compacted JSONL.")
    parser.add_argument(
        "--compact-files",
        default="autonomy/state/audit_live.jsonl,autonomy/state/autonomy_live.jsonl,autonomy/state/agent_api_metering.jsonl",
        help="Comma-separated JSONL files to compact.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    interval = max(15, int(args.interval_seconds))
    max_cycles = max(0, int(args.max_cycles))
    files = [f.strip() for f in str(args.compact_files).split(",") if f.strip()]

    cycle = 0
    while True:
        cycle += 1
        started = datetime.now(UTC).replace(microsecond=0).isoformat()
        rc = run_live_job_once(
            repo_root=repo_root,
            config_rel=str(args.config),
            env_file=str(args.env_file),
        )
        compacted = _compact_many(
            repo_root=repo_root,
            files=files,
            max_bytes=int(args.compact_max_bytes),
            keep_tail_lines=int(args.compact_keep_lines),
        )
        payload = {
            "cycle": cycle,
            "started_at_utc": started,
            "completed_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "exit_code": rc,
            "compaction": [asdict(r) for r in compacted],
        }
        print(json.dumps(payload, sort_keys=True))
        sys.stdout.flush()

        if rc != 0:
            # Back off briefly on failure; continue autonomous loop.
            time.sleep(min(60, interval))
        if max_cycles and cycle >= max_cycles:
            break
        time.sleep(interval)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        main()
