#!/usr/bin/env python3
"""
TruthGuard (Lite)

Goal: keep a local, retrieval-first memory of "what I got wrong / overpromised"
and inject that context at the start of each session.

This is intentionally dependency-free (stdlib only). It uses lexical retrieval
(token overlap + BM25-ish scoring) across local feedback + lessons.

Inputs (all gitignored):
- .claude/memory/feedback/feedback-log.jsonl              (Node capture-feedback.js)
- .claude/memory/feedback/pending_cortex_sync.jsonl       (hook queue)
- .claude/memory/lessons-learned.md                       (auto-lesson-creator.js)

Usage:
  python3 truth_rag_lite.py --start-context
  python3 truth_rag_lite.py --query "imap uid edge case"
"""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
MEMORY_DIR = REPO_ROOT / ".claude" / "memory"
FEEDBACK_DIR = MEMORY_DIR / "feedback"

FEEDBACK_LOG = FEEDBACK_DIR / "feedback-log.jsonl"
PENDING_SYNC = FEEDBACK_DIR / "pending_cortex_sync.jsonl"
REVENUE_LEARNING_LOG = FEEDBACK_DIR / "revenue-learning-log.jsonl"
STRATEGY_LOG = FEEDBACK_DIR / "strategy-response-log.jsonl"
LESSONS_MD = MEMORY_DIR / "lessons-learned.md"


WORD_RE = re.compile(r"[a-z0-9]+")
# "Lie" vocabulary users actually type (include past tense).
LIE_TERMS_RE = re.compile(r"(?i)\b(lie|lies|lying|lied|dishonest|false\s+promise|made\s+up|hallucinat)\b")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tokenize(text: str) -> list[str]:
    return WORD_RE.findall(text.lower())


def _safe_iso_date(ts: str) -> str:
    # Accept "2026-02-14T..." or "2026-02-14" and return YYYY-MM-DD if possible.
    if not ts:
        return "unknown"
    try:
        if len(ts) == 10 and ts[4] == "-" and ts[7] == "-":
            return ts
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.date().isoformat()
    except Exception:
        return ts[:10]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@dataclass(frozen=True)
class Doc:
    doc_id: str
    kind: str  # "feedback" | "lesson"
    ts: str
    text: str
    tags: list[str]
    weight: float = 1.0


class BM25:
    # Small, dependency-free BM25 for lexical retrieval.
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freqs: dict[str, int] = {}
        self.doc_lengths: list[int] = []
        self.avg_doc_length: float = 0.0
        self.corpus: list[list[str]] = []
        self.n_docs = 0

    def fit(self, documents: list[str]) -> None:
        self.corpus = [_tokenize(doc) for doc in documents]
        self.n_docs = len(self.corpus)
        self.doc_lengths = [len(doc) for doc in self.corpus]
        self.avg_doc_length = (sum(self.doc_lengths) / self.n_docs) if self.n_docs else 0.0

        self.doc_freqs = {}
        for doc in self.corpus:
            seen = set()
            for term in doc:
                if term in seen:
                    continue
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1
                seen.add(term)

    def _idf(self, term: str) -> float:
        df = self.doc_freqs.get(term, 0)
        # Standard BM25-ish idf (smoothed).
        return math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query: str, doc_idx: int) -> float:
        query_terms = _tokenize(query)
        doc_terms = self.corpus[doc_idx]
        doc_len = self.doc_lengths[doc_idx]

        if not doc_terms:
            return 0.0

        tf: dict[str, int] = {}
        for t in doc_terms:
            tf[t] = tf.get(t, 0) + 1

        score = 0.0
        for t in query_terms:
            if t not in tf:
                continue
            f = tf[t]
            idf = self._idf(t)
            denom = f + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avg_doc_length or 1.0)))
            score += idf * (f * (self.k1 + 1.0)) / (denom or 1.0)
        return score

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        scores = [(i, self.score(query, i)) for i in range(self.n_docs)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


def _looks_like_machine_context(text: str) -> bool:
    # Common noisy shape: serialized JSON with transcript paths / hook metadata
    # instead of human text.
    t = (text or "").strip()
    if not t:
        return True
    if "transcript_path" in t:
        return True
    return bool(t.startswith("{") and ("session_id" in t or "sessionId" in t) and ("cwd" in t or "hook_event" in t or "hookEvent" in t))


def _extract_human_context(raw: Any) -> str:
    """
    Normalize context fields:
    - If raw is plain text: return it
    - If raw is a JSON-encoded string from hook instrumentation: extract the 'prompt' field when possible
    """
    if raw is None:
        return ""
    if not isinstance(raw, str):
        return str(raw).strip()

    s = raw.strip()
    if not s:
        return ""

    # If it's a JSON string, try to extract the human prompt.
    if s.startswith("{") and ("prompt" in s or "transcript_path" in s or "session_id" in s or "sessionId" in s):
        try:
            obj = json.loads(s)
            prompt = obj.get("prompt")
            if isinstance(prompt, str) and prompt.strip():
                return prompt.strip()
        except json.JSONDecodeError:
            return s

    return s


def _load_feedback_docs() -> list[Doc]:
    docs: list[Doc] = []

    # Preferred: node-based RLHF log with explicit reward.
    for obj in _read_jsonl(FEEDBACK_LOG):
        is_negative = False
        if "reward" in obj:
            try:
                is_negative = float(obj.get("reward", 0)) < 0
            except Exception:
                is_negative = False
        elif str(obj.get("signal", "")).lower() == "negative":
            is_negative = True

        if not is_negative:
            continue

        ts = str(obj.get("timestamp", "")) or ""
        context_text = _extract_human_context(obj.get("context", ""))
        if not context_text:
            continue
        if _looks_like_machine_context(context_text):
            # Avoid polluting retrieval with hook/instrumentation blobs.
            continue

        tags = obj.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        docs.append(
            Doc(
                doc_id=str(obj.get("id", f"fb_{len(docs)}")),
                kind="feedback",
                ts=ts,
                text=context_text,
                tags=[str(t) for t in tags if t],
                weight=1.0,
            )
        )

    # Fallback: hook queue (no reward field, just signal/intensity).
    for obj in _read_jsonl(PENDING_SYNC):
        if str(obj.get("signal", "")).lower() != "negative":
            continue
        ts = str(obj.get("timestamp", "")) or ""
        context_text = _extract_human_context(obj.get("context", ""))
        if not context_text:
            continue
        if _looks_like_machine_context(context_text):
            continue

        domain = str(obj.get("domain", "")).strip()
        tags = [domain] if domain else []
        docs.append(
            Doc(
                doc_id=f"pending_{len(docs)}",
                kind="feedback",
                ts=ts,
                text=context_text,
                tags=tags,
                weight=0.6,  # lower confidence than explicit RLHF
            )
        )

    # Newest first helps in --start-context.
    docs.sort(key=lambda d: d.ts or "", reverse=True)
    return docs


def _load_lesson_docs() -> list[Doc]:
    if not LESSONS_MD.exists():
        return []
    text = LESSONS_MD.read_text(encoding="utf-8", errors="ignore")
    # Very lightweight parsing: split by headings, keep the chunk text.
    chunks: list[tuple[str, str]] = []
    current_title = "Lessons Learned"
    buf: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if buf:
                chunks.append((current_title, "\n".join(buf).strip()))
            current_title = line[3:].strip()
            buf = []
        else:
            buf.append(line)
    if buf:
        chunks.append((current_title, "\n".join(buf).strip()))

    docs: list[Doc] = []
    for i, (title, chunk) in enumerate(chunks):
        chunk = chunk.strip()
        if not chunk:
            continue
        # Prefer higher weight for critical/high sections if the header implies it.
        title_l = title.lower()
        weight = 0.7
        if "critical" in title_l or "high" in title_l:
            weight = 1.2
        docs.append(
            Doc(
                doc_id=f"lesson_{i}",
                kind="lesson",
                ts="",  # lessons md may not be timestamped per chunk
                text=f"{title}\n{chunk}".strip(),
                tags=[],
                weight=weight,
            )
        )
    return docs


def _load_revenue_docs() -> list[Doc]:
    docs: list[Doc] = []
    for i, obj in enumerate(_read_jsonl(REVENUE_LEARNING_LOG)):
        if not isinstance(obj, dict):
            continue
        ts = str(obj.get("as_of_utc") or obj.get("timestamp") or "")
        bottleneck = str(obj.get("bottleneck") or "").strip()
        leading = str(obj.get("leading_signal") or "").strip()
        hypothesis = str(obj.get("hypothesis") or "").strip()
        confidence = obj.get("confidence_pct")
        next_actions = obj.get("next_actions") or []
        metrics = obj.get("metrics") or {}
        if not isinstance(next_actions, list):
            next_actions = []
        if not isinstance(metrics, dict):
            metrics = {}

        text_lines = [
            f"Revenue lesson: bottleneck={bottleneck or 'unknown'}",
            f"Leading signal: {leading or 'none'}",
            f"Hypothesis: {hypothesis or 'n/a'}",
            f"Confidence: {confidence}",
            f"Metrics: {json.dumps(metrics, sort_keys=True)}",
        ]
        for action in next_actions[:3]:
            text_lines.append(f"Next action: {str(action)}")

        docs.append(
            Doc(
                doc_id=str(obj.get("signature") or f"revenue_{i}"),
                kind="lesson",
                ts=ts,
                text="\n".join(text_lines),
                tags=["revenue", "callcatcherops"],
                weight=1.0,
            )
        )
    docs.sort(key=lambda d: d.ts or "", reverse=True)
    return docs


def _load_strategy_docs() -> list[Doc]:
    docs: list[Doc] = []
    for i, obj in enumerate(_read_jsonl(STRATEGY_LOG)):
        if not isinstance(obj, dict):
            continue
        ts = str(obj.get("timestamp") or "")
        domain = str(obj.get("domain") or "")
        question = str(obj.get("question") or "").strip()
        response = str(obj.get("response") or "").strip()
        truth_score = obj.get("truthfulness_score")
        if not question and not response:
            continue

        metrics = obj.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        sources = obj.get("sources") or []
        if not isinstance(sources, list):
            sources = []

        text_lines = [
            f"Strategy domain: {domain or 'unknown'}",
            f"Question: {question}",
            f"Response: {response}",
            f"Truth score: {truth_score}",
            f"Metrics: {json.dumps(metrics, sort_keys=True)}",
        ]
        if sources:
            text_lines.append(f"Sources: {', '.join([str(s) for s in sources[:5]])}")

        docs.append(
            Doc(
                doc_id=str(obj.get("id") or f"strategy_{i}"),
                kind="lesson",
                ts=ts,
                text="\n".join(text_lines),
                tags=["strategy", domain] if domain else ["strategy"],
                weight=0.9,
            )
        )
    docs.sort(key=lambda d: d.ts or "", reverse=True)
    return docs


def _build_corpus() -> list[Doc]:
    return _load_feedback_docs() + _load_lesson_docs() + _load_revenue_docs() + _load_strategy_docs()


def _extract_critical_high_lessons(max_per_section: int = 5) -> list[tuple[str, str]]:
    """
    Pull a few lesson titles from the markdown under the Critical/High sections.
    Returns list of (severity, title).
    """
    if not LESSONS_MD.exists():
        return []

    severity: str | None = None
    out: list[tuple[str, str]] = []
    counts: dict[str, int] = {"critical": 0, "high": 0}

    for line in LESSONS_MD.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("## "):
            h = line[3:].strip().lower()
            if "critical" in h:
                severity = "critical"
            elif "high" in h:
                severity = "high"
            else:
                severity = None
            continue

        if severity in ("critical", "high") and line.startswith("### "):
            title = line[4:].strip()
            if not title:
                continue
            if counts[severity] >= max_per_section:
                continue
            out.append((severity, title))
            counts[severity] += 1

    return out


def _score_query(docs: list[Doc], query: str, top_k: int = 8) -> list[tuple[Doc, float]]:
    if not docs or not query.strip():
        return []

    bm25 = BM25()
    bm25.fit([d.text for d in docs])
    scored: list[tuple[Doc, float]] = []
    for idx, s in bm25.search(query, top_k=top_k * 2):
        d = docs[idx]
        # Small boost if query is about lies and doc contains lie terms.
        boost = 0.15 if LIE_TERMS_RE.search(query) and LIE_TERMS_RE.search(d.text) else 0.0
        scored.append((d, (s * d.weight) + boost))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _print_start_context() -> int:
    docs_feedback = _load_feedback_docs()
    docs_revenue = _load_revenue_docs()
    docs_strategy = _load_strategy_docs()
    lie_hits = [d for d in docs_feedback if LIE_TERMS_RE.search(d.text)]

    print("\n" + "=" * 52)
    print("TRUTHGUARD (Lite) CONTEXT")
    print("=" * 52)
    print(f"As-of (UTC): {_utc_now_iso()}")

    if lie_hits:
        print("\nRECENT 'LIE / FALSE PROMISE' FLAGS (USER SAID SO):")
        for d in lie_hits[:5]:
            day = _safe_iso_date(d.ts)
            snippet = re.sub(r"\s+", " ", d.text).strip()
            print(f"- [{day}] {snippet[:160]}")

    if docs_feedback:
        print("\nRECENT NEGATIVE FEEDBACK (WHAT TO AVOID REPEATING):")
        for d in docs_feedback[:5]:
            day = _safe_iso_date(d.ts)
            snippet = re.sub(r"\s+", " ", d.text).strip()
            print(f"- [{day}] {snippet[:160]}")
    else:
        print("\nNo negative feedback recorded yet (nothing to retrieve).")

    lessons = _extract_critical_high_lessons(max_per_section=3)
    if lessons:
        print("\nCRITICAL/HIGH LESSONS (DON'T REPEAT):")
        for sev, title in lessons:
            print(f"- [{sev}] {title[:140]}")

    if docs_revenue:
        print("\nRECENT REVENUE LESSONS (RAG):")
        for d in docs_revenue[:3]:
            day = _safe_iso_date(d.ts)
            snippet = re.sub(r"\s+", " ", d.text).strip()
            print(f"- [{day}] {snippet[:200]}")

    if docs_strategy:
        print("\nRECENT STRATEGY ENTRIES (RAG):")
        for d in docs_strategy[:2]:
            day = _safe_iso_date(d.ts)
            snippet = re.sub(r"\s+", " ", d.text).strip()
            print(f"- [{day}] {snippet[:200]}")

    print("=" * 52 + "\n")
    return 0


def _print_query(query: str) -> int:
    docs = _build_corpus()
    results = _score_query(docs, query, top_k=10)

    print("\n" + "=" * 52)
    print("TRUTHGUARD (Lite) QUERY")
    print("=" * 52)
    print(f"Query: {query.strip()}")

    if not results:
        print("\nNo results. (No memory yet, or query too specific.)")
        print("=" * 52 + "\n")
        return 0

    print("\nTOP MATCHES:")
    for d, score in results:
        day = _safe_iso_date(d.ts)
        snippet = re.sub(r"\s+", " ", d.text).strip()
        print(f"- [{d.kind}] [{day}] score={score:.3f} {snippet[:200]}")

    print("=" * 52 + "\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TruthGuard Lite: local retrieval for 'lies/false promises'.")
    parser.add_argument("--start-context", action="store_true", help="Print start-of-session context")
    parser.add_argument("--query", default="", help="Search local memory for relevant past misses")
    args = parser.parse_args()

    if args.start_context:
        return _print_start_context()
    if args.query.strip():
        return _print_query(args.query)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
