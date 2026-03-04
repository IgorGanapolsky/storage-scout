from __future__ import annotations

from pathlib import Path

FORBIDDEN_TERMS = ("callcatcher", "callcatcherops", "missed-call")


def _iter_text_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in {".py", ".md", ".html", ".txt", ".json", ".xml"}]


def test_aeo_brand_guardrails_no_legacy_terms_in_runtime_and_docs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scoped_roots = [
        repo_root / "autonomy",
        repo_root / "docs" / "ai-seo",
    ]
    offenders: list[str] = []
    for root in scoped_roots:
        for path in _iter_text_files(root):
            if path.is_relative_to(repo_root / "autonomy" / "tests"):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for term in FORBIDDEN_TERMS:
                if term in text:
                    offenders.append(f"{path.relative_to(repo_root)} => {term}")
    assert not offenders, "legacy branding terms found:\n" + "\n".join(offenders)
