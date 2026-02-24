from __future__ import annotations

from pathlib import Path

from autonomy.tools.install_launchd_tollfree_watchdog import LABEL, _plist_content


def test_launchd_tollfree_watchdog_plist_contains_expected_settings(tmp_path: Path) -> None:
    xml = _plist_content(python_exe="/opt/homebrew/bin/python3.12", repo_root=tmp_path)
    assert LABEL in xml
    assert "<key>StartInterval</key>" in xml
    assert "<integer>3600</integer>" in xml
    assert "twilio_tollfree_watchdog.py" in xml
    assert "autonomy/state/twilio_tollfree_watchdog_state.json" in xml

