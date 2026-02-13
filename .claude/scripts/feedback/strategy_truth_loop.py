#!/usr/bin/env python3
"""
Strategy Truth Loop

Purpose:
1) Record strategic business Q/A responses
2) Retrieve similar prior responses (RAG-style retrieval)
3) Compare consistency/truthfulness signals
4) Generate a concrete execution plan artifact

This script is local-memory only (stored under `.claude/memory/`).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
MEMORY_DIR = SCRIPT_DIR.parent.parent / "memory"
FEEDBACK_DIR = MEMORY_DIR / "feedback"
PLANS_DIR = MEMORY_DIR / "plans"

LOG_FILE = FEEDBACK_DIR / "strategy-response-log.jsonl"
SUMMARY_FILE = FEEDBACK_DIR / "strategy-truth-summary.json"
PENDING_QUESTIONS_FILE = FEEDBACK_DIR / "pending_strategy_questions.jsonl"

URL_RE = re.compile(r"https?://\S+")
MONEY_RE = re.compile(r"\$([0-9][0-9,]*(?:\.[0-9]{1,2})?)")
DATE_RE = re.compile(
    r"(?i)\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r")\s+(\d{1,2})(?:,\s*(\d{4}))?"
)
WINDOW_RE = re.compile(
    r"(?i)\b("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r")\s+(\d{1,2})(?:,\s*(\d{4}))?\s*(?:to|-)\s*("
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
    r")\s+(\d{1,2})(?:,\s*(\d{4}))?"
)
PERCENT_RE = re.compile(r"(?i)\b(\d{1,3}(?:\.\d+)?)\s*%\s*(?:chance|probability|likelihood)")


MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dirs() -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)


def parse_money(raw: str) -> float:
    return float(raw.replace(",", ""))


def parse_human_date(month_raw: str, day_raw: str, year_raw: Optional[str]) -> Optional[datetime]:
    month = MONTHS.get(month_raw[:3].lower())
    if month is None:
        return None
    day = int(day_raw)
    year = int(year_raw) if year_raw else datetime.now(timezone.utc).year
    try:
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None


def iso_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def lexical_similarity(a: str, b: str) -> float:
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        norm_a += a * a
        norm_b += b * b
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def load_embedder() -> Tuple[Optional[Any], Optional[str]]:
    try:
        from sentence_transformers import SentenceTransformer
    except Exception:
        return None, None

    cache_dir = MEMORY_DIR / "model_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_name = "all-MiniLM-L6-v2"
    model = SentenceTransformer(model_name, cache_folder=str(cache_dir))

    def _embed(text: str) -> List[float]:
        return model.encode([text])[0].tolist()

    return _embed, model_name


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    with path.open("a") as f:
        f.write(json.dumps(obj) + "\n")


def load_pending_question() -> Optional[Dict[str, Any]]:
    pending = read_jsonl(PENDING_QUESTIONS_FILE)
    if not pending:
        return None
    return pending[-1]


def parse_question_response(args: argparse.Namespace) -> Tuple[str, str]:
    question = args.question or ""
    response = args.response or ""

    if args.question_file:
        question = Path(args.question_file).read_text().strip()
    if args.response_file:
        response = Path(args.response_file).read_text().strip()

    if args.consume_pending and not question:
        pending = load_pending_question()
        if pending:
            question = pending.get("question", "")

    if not question.strip():
        raise ValueError("Missing question. Provide --question, --question-file, or --consume-pending.")
    if not response.strip():
        raise ValueError("Missing response. Provide --response or --response-file.")

    return question.strip(), response.strip()


def extract_as_of_date(text: str) -> Optional[str]:
    as_of_re = re.compile(r"(?i)\bas of\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})")
    match = as_of_re.search(text)
    if not match:
        return None
    date_text = match.group(1)
    m = DATE_RE.search(date_text)
    if not m:
        return None
    dt = parse_human_date(m.group(1), m.group(2), m.group(3))
    return iso_date(dt) if dt else None


def extract_metrics(text: str) -> Dict[str, Any]:
    metrics: Dict[str, Any] = {}
    lowered = text.lower()

    # Current revenue (explicit lines about made/revenue/gross/net)
    revenue_candidates: List[float] = []
    for line in text.splitlines():
        line_l = line.lower()
        if any(k in line_l for k in ["made", "revenue", "gross", "net", "earned"]):
            money_match = MONEY_RE.search(line)
            if money_match:
                revenue_candidates.append(parse_money(money_match.group(1)))
    if revenue_candidates:
        metrics["current_revenue_usd"] = revenue_candidates[0]

    # Paid sessions (Stripe style)
    paid_match = re.search(r"(?i)\b(?:sessions?\s+paid|paid sessions?)\D{0,10}(\d+)", text)
    if paid_match:
        metrics["paid_sessions"] = int(paid_match.group(1))

    # Probability for time window estimates
    prob_match = PERCENT_RE.search(text)
    if prob_match:
        metrics["first_dollar_probability_pct"] = float(prob_match.group(1))

    # First-dollar window
    win_match = WINDOW_RE.search(text)
    if win_match:
        start_dt = parse_human_date(win_match.group(1), win_match.group(2), win_match.group(3))
        end_dt = parse_human_date(win_match.group(4), win_match.group(5), win_match.group(6))
        if start_dt and end_dt:
            metrics["first_dollar_window_start"] = iso_date(start_dt)
            metrics["first_dollar_window_end"] = iso_date(end_dt)

    # If explicit "$0.00" and revenue keywords exist, keep explicit zero
    if "0.00" in text and any(x in lowered for x in ["stripe", "gross", "net", "revenue"]):
        if "current_revenue_usd" not in metrics:
            metrics["current_revenue_usd"] = 0.0

    return metrics


def detect_domain(question: str, response: str) -> str:
    combined = f"{question}\n{response}".lower()
    callcatcher_terms = [
        "callcatcher",
        "missed call",
        "first dollar",
        "revenue",
        "make money",
        "local service",
        "audit",
        "stripe",
    ]
    if any(term in combined for term in callcatcher_terms):
        return "callcatcher-revenue"
    return "general-strategy"


def get_sources(args_sources: List[str], response: str) -> List[str]:
    discovered = URL_RE.findall(response)
    out = list(dict.fromkeys([*args_sources, *discovered]))
    return out


@dataclass
class SimilarResult:
    entry: Dict[str, Any]
    score: float
    method: str


def retrieve_similar_entries(
    entries: List[Dict[str, Any]],
    question: str,
    response: str,
    embedder: Optional[Any],
) -> List[SimilarResult]:
    query_text = f"{question}\n{response}"
    query_embedding: Optional[List[float]] = None
    if embedder:
        query_embedding = embedder(query_text)

    results: List[SimilarResult] = []
    for entry in entries:
        prev_text = f"{entry.get('question', '')}\n{entry.get('response', '')}"
        score = 0.0
        method = "lexical"
        if query_embedding is not None and isinstance(entry.get("embedding"), list):
            score = cosine_similarity(query_embedding, entry["embedding"])
            method = "embedding"
        else:
            score = lexical_similarity(query_text, prev_text)
        if score > 0:
            results.append(SimilarResult(entry=entry, score=score, method=method))

    results.sort(key=lambda x: x.score, reverse=True)
    return results[:5]


def compare_truthfulness(
    new_metrics: Dict[str, Any],
    new_as_of: Optional[str],
    similar: List[SimilarResult],
) -> Tuple[List[str], List[str]]:
    contradictions: List[str] = []
    consistency_notes: List[str] = []

    stable_keys = {"current_revenue_usd", "paid_sessions"}
    soft_keys = {"first_dollar_probability_pct", "first_dollar_window_start", "first_dollar_window_end"}

    for sim in similar:
        prev = sim.entry
        prev_metrics = prev.get("metrics", {})
        prev_date = prev.get("as_of_date")
        if not isinstance(prev_metrics, dict):
            continue

        for key in stable_keys:
            if key not in new_metrics or key not in prev_metrics:
                continue
            new_val = new_metrics[key]
            old_val = prev_metrics[key]
            if new_val == old_val:
                consistency_notes.append(
                    f"{key} matches prior entry {prev.get('id')} ({new_val})."
                )
                continue
            # Changed stable metric needs date context to be credible.
            if not new_as_of or not prev_date:
                contradictions.append(
                    f"{key} changed from {old_val} to {new_val} without clear as-of date context "
                    f"(prior entry {prev.get('id')})."
                )
                continue
            if new_as_of < prev_date:
                contradictions.append(
                    f"{key} appears to regress in time context: new as-of {new_as_of} is older than "
                    f"prior {prev_date} (entry {prev.get('id')})."
                )
            else:
                consistency_notes.append(
                    f"{key} changed from {old_val} to {new_val} with newer/equal as-of date "
                    f"({new_as_of} vs {prev_date})."
                )

        for key in soft_keys:
            if key in new_metrics and key in prev_metrics and new_metrics[key] == prev_metrics[key]:
                consistency_notes.append(f"{key} aligns with prior entry {prev.get('id')}.")

    return contradictions, consistency_notes


def score_truthfulness(
    response: str,
    source_count: int,
    contradictions: List[str],
    similar_count: int,
) -> int:
    score = 100
    score -= min(50, len(contradictions) * 20)
    if source_count == 0:
        score -= 15
    if similar_count == 0:
        score -= 5
    # Penalize certainty language when unsourced
    certainty_terms = ["guaranteed", "definitely", "certain", "100%", "no doubt", "will happen"]
    if source_count == 0 and any(term in response.lower() for term in certainty_terms):
        score -= 10
    return max(0, min(100, score))


def default_callcatcher_plan(metrics: Dict[str, Any]) -> List[str]:
    today = datetime.now(timezone.utc).date()
    start_72h = today + timedelta(days=3)
    day14 = today + timedelta(days=14)
    day30 = today + timedelta(days=30)
    revenue_now = float(metrics.get("current_revenue_usd", 0.0))

    if revenue_now <= 0:
        objective = f"Get first paid pilot by {day14.isoformat()} and first retained client by {day30.isoformat()}."
    else:
        objective = f"Scale from current revenue baseline (${revenue_now:.2f}) with at least 2 additional retained clients by {day30.isoformat()}."

    return [
        f"Objective: {objective}",
        f"72-hour deadline ({start_72h.isoformat()}): replace paid-audit-first CTA with free baseline + paid pilot CTA, and publish a single vertical offer page.",
        "Daily execution: send 40-60 targeted touches/day in one vertical + one geography; same-day follow-up for every reply.",
        "Conversion gate: book >=10 discovery calls and close >=2 paid pilots in 14 days; if not hit, pivot vertical immediately.",
        "Economics gate: every pilot must track recovered-booking value, telecom costs, and net margin per account before upsell.",
        "Truth gate: every weekly forecast must include source links + as-of date + explicit confidence percent.",
    ]


def default_general_plan() -> List[str]:
    today = datetime.now(timezone.utc).date()
    return [
        f"Objective: define one measurable business outcome by {(today + timedelta(days=14)).isoformat()}.",
        "Quantify baseline: current revenue, conversion rates, and cost per acquisition with explicit source of truth.",
        "Run one narrow experiment with a fixed daily execution quota and a fixed stop date.",
        "Set kill criteria before running: if metrics miss threshold, stop or pivot immediately.",
        "Write weekly truth audit: what changed, what evidence supports it, and what assumption failed.",
    ]


def write_plan_file(
    entry_id: str,
    question: str,
    metrics: Dict[str, Any],
    truth_score: int,
    contradictions: List[str],
    consistency_notes: List[str],
    similar: List[SimilarResult],
    domain: str,
) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    plan_path = PLANS_DIR / f"{timestamp}-{entry_id}.md"

    if domain == "callcatcher-revenue":
        plan_lines = default_callcatcher_plan(metrics)
    else:
        plan_lines = default_general_plan()

    similar_lines = [
        f"- {s.entry.get('id')} (score={s.score:.3f}, method={s.method})"
        for s in similar
    ] or ["- None"]
    contradiction_lines = [f"- {c}" for c in contradictions] or ["- None detected"]
    consistency_lines = [f"- {c}" for c in consistency_notes] or ["- No direct matches"]

    content = [
        "# Strategy Truth Plan",
        "",
        f"- Entry ID: `{entry_id}`",
        f"- Generated: `{utc_now_iso()}`",
        f"- Domain: `{domain}`",
        f"- Truthfulness score: `{truth_score}/100`",
        "",
        "## Question",
        question,
        "",
        "## Extracted Metrics",
        "```json",
        json.dumps(metrics, indent=2),
        "```",
        "",
        "## Similar Prior Responses",
        *similar_lines,
        "",
        "## Consistency Signals",
        *consistency_lines,
        "",
        "## Contradictions",
        *contradiction_lines,
        "",
        "## Solid Plan",
        *[f"- {line}" for line in plan_lines],
        "",
    ]

    plan_path.write_text("\n".join(content))
    return plan_path


def update_summary(entry: Dict[str, Any]) -> None:
    summary = {
        "total_entries": 0,
        "average_truthfulness_score": 0.0,
        "latest_entry_id": None,
        "last_updated": None,
        "domain_counts": {},
    }
    if SUMMARY_FILE.exists():
        try:
            summary = json.loads(SUMMARY_FILE.read_text())
        except json.JSONDecodeError:
            pass

    n = int(summary.get("total_entries", 0))
    prev_avg = float(summary.get("average_truthfulness_score", 0.0))
    score = float(entry.get("truthfulness_score", 0))
    new_n = n + 1
    new_avg = ((prev_avg * n) + score) / new_n

    summary["total_entries"] = new_n
    summary["average_truthfulness_score"] = round(new_avg, 2)
    summary["latest_entry_id"] = entry.get("id")
    summary["last_updated"] = utc_now_iso()

    domain = entry.get("domain", "unknown")
    domains = summary.get("domain_counts", {})
    domains[domain] = int(domains.get(domain, 0)) + 1
    summary["domain_counts"] = domains

    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Record strategic response + truth-check + plan.")
    parser.add_argument("--question", help="User question text")
    parser.add_argument("--response", help="Assistant response text")
    parser.add_argument("--question-file", help="Path to file containing user question")
    parser.add_argument("--response-file", help="Path to file containing assistant response")
    parser.add_argument("--consume-pending", action="store_true", help="Use latest pending strategy question if question is missing")
    parser.add_argument("--source", action="append", default=[], help="Evidence/source URL (repeatable)")
    parser.add_argument("--tag", action="append", default=[], help="Optional tag (repeatable)")
    args = parser.parse_args()

    ensure_dirs()

    try:
        question, response = parse_question_response(args)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1

    entries = read_jsonl(LOG_FILE)
    embedder, model_name = load_embedder()
    query_embedding = embedder(f"{question}\n{response}") if embedder else None

    domain = detect_domain(question, response)
    metrics = extract_metrics(response)
    as_of_date = extract_as_of_date(response)
    sources = get_sources(args.source, response)

    similar = retrieve_similar_entries(entries, question, response, embedder)
    contradictions, consistency_notes = compare_truthfulness(metrics, as_of_date, similar)
    truth_score = score_truthfulness(
        response=response,
        source_count=len(sources),
        contradictions=contradictions,
        similar_count=len(similar),
    )

    digest = hashlib.sha1(f"{question}\n{response}".encode("utf-8")).hexdigest()[:10]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    entry_id = f"strat_{timestamp}_{digest}"

    plan_path = write_plan_file(
        entry_id=entry_id,
        question=question,
        metrics=metrics,
        truth_score=truth_score,
        contradictions=contradictions,
        consistency_notes=consistency_notes,
        similar=similar,
        domain=domain,
    )

    entry: Dict[str, Any] = {
        "id": entry_id,
        "timestamp": utc_now_iso(),
        "question": question,
        "response": response,
        "domain": domain,
        "as_of_date": as_of_date,
        "metrics": metrics,
        "sources": sources,
        "tags": args.tag,
        "truthfulness_score": truth_score,
        "contradictions": contradictions,
        "consistency_notes": consistency_notes,
        "similar_entries": [
            {
                "id": s.entry.get("id"),
                "score": round(s.score, 6),
                "method": s.method,
            }
            for s in similar
        ],
        "plan_path": str(plan_path),
    }
    if query_embedding is not None:
        entry["embedding_model"] = model_name
        entry["embedding"] = query_embedding

    append_jsonl(LOG_FILE, entry)
    update_summary(entry)

    print("✅ Strategy truth loop recorded")
    print(f"   entry_id: {entry_id}")
    print(f"   truthfulness_score: {truth_score}/100")
    print(f"   contradictions: {len(contradictions)}")
    print(f"   similar_entries: {len(similar)}")
    print(f"   plan: {plan_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
