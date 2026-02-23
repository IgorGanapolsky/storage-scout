#!/usr/bin/env python3
"""
Funnel Watchdog

Checks that the public funnel still works:
- marketing landing page
- intake page
- thank-you page
- unsubscribe page
- external CTAs (Calendly + Stripe)

This is intentionally lightweight and safe:
- no form submissions
- no payments
- no logins
"""

from __future__ import annotations

import contextlib
import os
import random
import re
import string
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from autonomy.utils import now_utc_iso

CTA_CALENDLY_RE = re.compile(r"https?://(?:www\.)?calendly\.com/[^\s\"'>]+", re.IGNORECASE)
CTA_STRIPE_RE = re.compile(r"https?://buy\.stripe\.com/[^\s\"'>]+", re.IGNORECASE)

# Loose "broken page" markers for third-party CTAs.
CALENDLY_BAD_MARKERS = (
    "page not found",
    "event type is not available",
    "this event is not available",
    "this calendly link is not available",
)
STRIPE_BAD_MARKERS = (
    "payment link is no longer available",
    "this payment link is no longer available",
    "link is no longer available",
    "page not found",
)


@dataclass(frozen=True)
class FunnelIssue:
    name: str
    url: str
    detail: str


@dataclass
class FunnelWatchdogResult:
    as_of_utc: str
    checks_total: int = 0
    checks_ok: int = 0
    issues: list[FunnelIssue] = field(default_factory=list)

    def add_ok(self) -> None:
        self.checks_total += 1
        self.checks_ok += 1

    def add_issue(self, *, name: str, url: str, detail: str) -> None:
        self.checks_total += 1
        self.issues.append(FunnelIssue(name=name, url=url, detail=detail))

    @property
    def is_healthy(self) -> bool:
        return not self.issues


def _derive_urls(*, intake_url: str, unsubscribe_url_template: str) -> dict[str, str]:
    intake_url = (intake_url or "").strip()
    parsed = urlparse(intake_url)
    if not parsed.scheme or not parsed.netloc:
        return {}

    base_dir = intake_url.rsplit("/", 1)[0] + "/"
    landing = base_dir
    thanks = urljoin(base_dir, "thanks.html")

    unsub = (unsubscribe_url_template or "").strip()
    if "?" in unsub:
        unsub = unsub.split("?", 1)[0]
    if "{{" in unsub:
        unsub = unsub.split("{{", 1)[0].rstrip("?&")

    return {
        "landing": landing,
        "intake": intake_url,
        "thanks": thanks,
        "unsubscribe": unsub,
    }


def _http_get(url: str, *, timeout: int = 14, max_bytes: int = 320_000) -> tuple[int, str]:
    url = (url or "").strip()
    if not url:
        return 0, ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "callcatcherops-funnel-watchdog/1.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", resp.getcode() or 0) or 0)
            raw = resp.read(max_bytes)
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            return status, text
    except Exception:
        return 0, ""


def _extract_ctas_from_html(html: str) -> dict[str, str]:
    html = html or ""
    calendly = ""
    stripe = ""
    m = CTA_CALENDLY_RE.search(html)
    if m:
        calendly = m.group(0).strip()
    m = CTA_STRIPE_RE.search(html)
    if m:
        stripe = m.group(0).strip()
    out: dict[str, str] = {}
    if calendly:
        out["calendly"] = calendly
    if stripe:
        out["stripe"] = stripe
    return out


def _rand_suffix(n: int = 6) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def _agent_browser_get_text(*, repo_root: Path, url: str, timeout: int = 60) -> str:
    """
    Best-effort rendered text via agent-browser. Returns "" if unavailable.
    """
    # Import here so funnel watchdog can run without node tooling.
    import shutil  # noqa: PLC0415

    cmd = ["npx", "agent-browser"] if shutil.which("npx") else (["agent-browser"] if shutil.which("agent-browser") else None)
    if not cmd:
        return ""

    session = f"funnel-{os.getpid()}-{_rand_suffix()}"
    sock = Path.home() / ".agent-browser" / f"{session}.sock"
    pid = Path.home() / ".agent-browser" / f"{session}.pid"

    def run(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd + ["--session", session] + args,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
        )

    # Ensure a clean slate for this session name.
    with contextlib.suppress(Exception):
        run(["close"], check=False)
    with contextlib.suppress(OSError):
        sock.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        pid.unlink(missing_ok=True)

    try:
        try:
            run(["open", url], check=True)
        except subprocess.CalledProcessError as exc:
            # If the daemon got wedged, clear and retry once.
            err = (exc.stderr or "").lower()
            if "daemon failed to start" in err:
                with contextlib.suppress(OSError):
                    sock.unlink(missing_ok=True)
                with contextlib.suppress(OSError):
                    pid.unlink(missing_ok=True)
                run(["open", url], check=True)
            else:
                return ""

        # Wait is best-effort (some pages never go network-idle).
        with contextlib.suppress(Exception):
            run(["wait", "--load", "networkidle"], check=False)
        res = run(["get", "text", "body"], check=True)
        return (res.stdout or "").strip()
    except Exception:
        return ""
    finally:
        with contextlib.suppress(Exception):
            run(["close"], check=False)
        with contextlib.suppress(OSError):
            sock.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            pid.unlink(missing_ok=True)


def run_funnel_watchdog(*, repo_root: Path, intake_url: str, unsubscribe_url_template: str) -> FunnelWatchdogResult:
    res = FunnelWatchdogResult(as_of_utc=now_utc_iso())
    urls = _derive_urls(intake_url=intake_url, unsubscribe_url_template=unsubscribe_url_template)
    if not urls:
        res.add_issue(name="config", url=intake_url, detail="invalid intake_url; cannot derive funnel urls")
        return res

    # 1) Check core pages via HTTP.
    for name in ("landing", "intake", "thanks", "unsubscribe"):
        url = urls.get(name, "").strip()
        if not url:
            res.add_issue(name=name, url=url, detail="missing url")
            continue
        status, body = _http_get(url)
        if status < 200 or status >= 400:
            res.add_issue(name=name, url=url, detail=f"http_status={status or 'error'}")
            continue
        if "callcatcher" not in (body or "").lower():
            res.add_issue(name=name, url=url, detail="missing expected marker 'callcatcher' in HTML")
            continue
        res.add_ok()

    # 2) Extract external CTAs from the live intake HTML (fallback to local doc).
    intake_body = ""
    status, intake_body = _http_get(urls["intake"])
    ctas = _extract_ctas_from_html(intake_body or "")
    if not ctas:
        local_intake = repo_root / "docs" / "callcatcherops" / "intake.html"
        if local_intake.exists():
            ctas = _extract_ctas_from_html(local_intake.read_text(encoding="utf-8", errors="ignore"))

    # 3) Check external CTAs.
    for cta_name, url in ctas.items():
        status, body = _http_get(url)
        if status < 200 or status >= 400:
            res.add_issue(name=f"cta_{cta_name}", url=url, detail=f"http_status={status or 'error'}")
            continue

        # Prefer rendered text for third-party pages when possible.
        rendered = _agent_browser_get_text(repo_root=repo_root, url=url)
        haystack = (rendered or body or "").lower()

        bad_markers = CALENDLY_BAD_MARKERS if cta_name == "calendly" else STRIPE_BAD_MARKERS
        if any(m in haystack for m in bad_markers):
            res.add_issue(name=f"cta_{cta_name}", url=url, detail="matches broken-page marker")
            continue

        res.add_ok()

    if "calendly" not in ctas:
        res.add_issue(name="cta_calendly", url=urls["intake"], detail="could not find calendly link in intake html")

    return res


def main() -> int:
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(description="Check CallCatcher Ops funnel health (no submissions).")
    parser.add_argument("--intake-url", default="", help="Public intake URL")
    parser.add_argument("--unsubscribe-url-template", default="", help="Unsubscribe URL template (may include ?email={{email}})")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    result = run_funnel_watchdog(
        repo_root=repo_root,
        intake_url=args.intake_url,
        unsubscribe_url_template=args.unsubscribe_url_template,
    )

    print("Funnel watchdog")
    print(f"As-of (UTC): {result.as_of_utc}")
    print(f"Healthy: {result.is_healthy}")
    print(f"Checks: {result.checks_ok}/{result.checks_total}")
    if result.issues:
        print("")
        print("Issues:")
        for issue in result.issues:
            print(f"- {issue.name}: {issue.detail} ({issue.url})")
    return 0 if result.is_healthy else 2


if __name__ == "__main__":
    raise SystemExit(main())
