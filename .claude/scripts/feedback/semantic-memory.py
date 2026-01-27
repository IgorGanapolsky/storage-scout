#!/usr/bin/env python3
"""
Semantic Memory System for Storage Scout - LanceDB + Hybrid Search

Architecture (2026 Best Practices):
┌─────────────────────────────────────────────────────────┐
│  HYBRID SEARCH ENGINE                                   │
│  ┌────────────────┐  ┌────────────────┐                │
│  │ BM25 (Keywords)│ + │ Vector (Semantic)│ = Fusion    │
│  └────────────────┘  └────────────────┘                │
└─────────────────────────────────────────────────────────┘
                         │
              ┌──────────┴──────────┐
              │  LanceDB Storage    │
              │  + Similarity Filter │
              │  + LRU Cache        │
              └─────────────────────┘

LOCAL ONLY - Never commit to repository

Usage:
  python semantic-memory.py --index              # Index all feedback
  python semantic-memory.py --query "spread"     # Hybrid search
  python semantic-memory.py --context            # Get session context
  python semantic-memory.py --metrics            # Show query metrics
"""

import os
import sys
import json
import re
import hashlib
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import OrderedDict

# Configuration
SCRIPT_DIR = Path(__file__).parent
MEMORY_DIR = SCRIPT_DIR.parent.parent / "memory"
FEEDBACK_DIR = MEMORY_DIR / "feedback"
LANCE_DIR = FEEDBACK_DIR / "lancedb"
INDEX_STATE_FILE = FEEDBACK_DIR / "lance-index-state.json"
METRICS_FILE = FEEDBACK_DIR / "query-metrics.jsonl"
FEEDBACK_LOG = FEEDBACK_DIR / "feedback-log.jsonl"
LESSONS_DIR = MEMORY_DIR / "lessons"

# Model options
EMBEDDING_MODELS = {
    "fast": "all-MiniLM-L6-v2",       # 384 dims, ~50ms
    "better": "intfloat/e5-small-v2",  # 384 dims, ~80ms, better quality
}
DEFAULT_MODEL = "fast"  # Use fast for this project

# Search configuration
SIMILARITY_THRESHOLD = 0.7
BM25_WEIGHT = 0.3
VECTOR_WEIGHT = 0.7

# Table names
FEEDBACK_TABLE = "rlhf_feedback"
LESSONS_TABLE = "lessons_learned"


class EmbeddingCache:
    """LRU cache for embeddings"""
    def __init__(self, maxsize: int = 500):
        self.cache = OrderedDict()
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0

    def get(self, text: str) -> Optional[List[float]]:
        if text in self.cache:
            self.cache.move_to_end(text)
            self.hits += 1
            return self.cache[text]
        self.misses += 1
        return None

    def put(self, text: str, embedding: List[float]):
        if text in self.cache:
            self.cache.move_to_end(text)
        else:
            if len(self.cache) >= self.maxsize:
                self.cache.popitem(last=False)
            self.cache[text] = embedding

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        hit_rate = self.hits / total if total > 0 else 0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.2%}",
            "size": len(self.cache),
        }


_embedding_cache = EmbeddingCache()


class MetricsLogger:
    """Log query metrics for observability"""
    def __init__(self, metrics_file: Path):
        self.metrics_file = metrics_file
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, data: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            **data
        }
        with open(self.metrics_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def get_summary(self, days: int = 7) -> Dict[str, Any]:
        if not self.metrics_file.exists():
            return {"error": "No metrics found"}

        cutoff = datetime.now().timestamp() - (days * 86400)
        queries = []

        with open(self.metrics_file) as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        entry_time = datetime.fromisoformat(entry["timestamp"]).timestamp()
                        if entry_time > cutoff:
                            queries.append(entry)
                    except (json.JSONDecodeError, ValueError):
                        continue

        if not queries:
            return {"queries": 0, "period_days": days}

        query_events = [q for q in queries if q.get("event") == "query"]
        latencies = [q.get("latency_ms", 0) for q in query_events]

        return {
            "period_days": days,
            "total_queries": len(query_events),
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "feedback_events": len([q for q in queries if q.get("event") == "feedback"]),
            "cache_stats": _embedding_cache.stats(),
        }


_metrics = MetricsLogger(METRICS_FILE)


def get_table_names(db) -> List[str]:
    """Get table names from LanceDB"""
    result = db.list_tables()
    if hasattr(result, 'tables'):
        return result.tables
    return list(result)


def table_exists(db, table_name: str) -> bool:
    return table_name in get_table_names(db)


def get_lance_db():
    """Initialize LanceDB"""
    try:
        import lancedb
        LANCE_DIR.mkdir(parents=True, exist_ok=True)
        return lancedb.connect(str(LANCE_DIR))
    except ImportError:
        print("lancedb not installed. Run: pip install lancedb")
        sys.exit(1)


def get_embedding_model(model_key: str = DEFAULT_MODEL):
    """Get sentence transformer model"""
    try:
        from sentence_transformers import SentenceTransformer
        model_name = EMBEDDING_MODELS.get(model_key, EMBEDDING_MODELS["fast"])

        cache_dir = MEMORY_DIR / "model_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(cache_dir))

        return SentenceTransformer(model_name)
    except ImportError:
        print("sentence-transformers not installed. Run: pip install sentence-transformers")
        sys.exit(1)


def get_embedding_with_cache(text: str, model) -> List[float]:
    """Get embedding with LRU cache"""
    cached = _embedding_cache.get(text)
    if cached is not None:
        return cached

    embedding = model.encode([text])[0].tolist()
    _embedding_cache.put(text, embedding)
    return embedding


class BM25:
    """Simple BM25 for hybrid search"""
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_freqs = {}
        self.doc_lengths = []
        self.avg_doc_length = 0
        self.corpus = []
        self.n_docs = 0

    def fit(self, documents: List[str]):
        self.corpus = [self._tokenize(doc) for doc in documents]
        self.n_docs = len(self.corpus)
        self.doc_lengths = [len(doc) for doc in self.corpus]
        self.avg_doc_length = sum(self.doc_lengths) / self.n_docs if self.n_docs > 0 else 0

        self.doc_freqs = {}
        for doc in self.corpus:
            seen = set()
            for term in doc:
                if term not in seen:
                    self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1
                    seen.add(term)

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r'\w+', text.lower())

    def _idf(self, term: str) -> float:
        import math
        df = self.doc_freqs.get(term, 0)
        return math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1)

    def score(self, query: str, doc_idx: int) -> float:
        query_terms = self._tokenize(query)
        doc = self.corpus[doc_idx]
        doc_len = self.doc_lengths[doc_idx]

        score = 0.0
        term_freqs = {}
        for term in doc:
            term_freqs[term] = term_freqs.get(term, 0) + 1

        for term in query_terms:
            if term not in term_freqs:
                continue
            tf = term_freqs[term]
            idf = self._idf(term)
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avg_doc_length)
            score += idf * numerator / denominator

        return score

    def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        scores = [(i, self.score(query, i)) for i in range(self.n_docs)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


def load_feedback() -> List[Dict[str, Any]]:
    """Load RLHF feedback for indexing"""
    if not FEEDBACK_LOG.exists():
        return []

    patterns = []
    with open(FEEDBACK_LOG) as f:
        for line in f:
            if line.strip():
                try:
                    entry = json.loads(line)
                    doc_text = f"Feedback: {entry.get('feedback', 'unknown')}\n"
                    doc_text += f"Context: {entry.get('context', '')}\n"
                    doc_text += f"Tags: {', '.join(entry.get('tags', []))}\n"
                    doc_text += f"Action: {entry.get('actionType', 'unknown')}"

                    patterns.append({
                        "id": entry.get("id", f"fb_{len(patterns)}"),
                        "type": "feedback",
                        "feedback_type": entry.get("feedback", "unknown"),
                        "reward": entry.get("reward", 0),
                        "context": entry.get("context", "")[:200],
                        "tags": ",".join(entry.get("tags", [])),
                        "full_text": doc_text,
                        "timestamp": entry.get("timestamp", datetime.now().isoformat()),
                    })
                except json.JSONDecodeError:
                    continue

    return patterns


def load_lessons() -> List[Dict[str, Any]]:
    """Load lessons from lessons directory"""
    if not LESSONS_DIR.exists():
        return []

    lessons = []
    for lesson_file in LESSONS_DIR.glob("*.json"):
        try:
            with open(lesson_file) as f:
                lesson = json.load(f)

            doc_text = f"Title: {lesson.get('title', 'Unknown')}\n"
            doc_text += f"What went wrong: {lesson.get('whatWentWrong', '')}\n"
            doc_text += f"Prevention: {lesson.get('prevention', '')}\n"
            doc_text += f"Severity: {lesson.get('severity', 'medium')}"

            lessons.append({
                "id": lesson.get("id", lesson_file.stem),
                "type": "lesson",
                "title": lesson.get("title", "Unknown"),
                "severity": lesson.get("severity", "medium"),
                "domain": lesson.get("domain", "general"),
                "tags": ",".join(lesson.get("tags", [])),
                "full_text": doc_text,
                "timestamp": lesson.get("createdAt", datetime.now().isoformat()),
            })
        except (json.JSONDecodeError, IOError):
            continue

    return lessons


def index_all(model_key: str = DEFAULT_MODEL):
    """Index all feedback and lessons into LanceDB"""
    print(f"\nIndexing into LanceDB...")
    print(f"   Model: {EMBEDDING_MODELS.get(model_key, model_key)}")
    print(f"   Storage: {LANCE_DIR}")

    db = get_lance_db()
    model = get_embedding_model(model_key)

    # Index feedback
    print("\n[1/2] Indexing RLHF feedback...")
    feedback = load_feedback()

    if feedback:
        print(f"   Generating embeddings for {len(feedback)} entries...")
        texts = [f["full_text"] for f in feedback]
        embeddings = model.encode(texts, show_progress_bar=True)

        for i, fb in enumerate(feedback):
            fb["vector"] = embeddings[i].tolist()
            _embedding_cache.put(texts[i], fb["vector"])

        if table_exists(db, FEEDBACK_TABLE):
            db.drop_table(FEEDBACK_TABLE)

        db.create_table(FEEDBACK_TABLE, feedback)
        print(f"   Indexed {len(feedback)} feedback entries")
    else:
        print("   No feedback found yet")

    # Index lessons
    print("\n[2/2] Indexing lessons...")
    lessons = load_lessons()

    if lessons:
        print(f"   Generating embeddings for {len(lessons)} lessons...")
        texts = [l["full_text"] for l in lessons]
        embeddings = model.encode(texts, show_progress_bar=True)

        for i, lesson in enumerate(lessons):
            lesson["vector"] = embeddings[i].tolist()
            _embedding_cache.put(texts[i], lesson["vector"])

        if table_exists(db, LESSONS_TABLE):
            db.drop_table(LESSONS_TABLE)

        db.create_table(LESSONS_TABLE, lessons)
        print(f"   Indexed {len(lessons)} lessons")
    else:
        print("   No lessons found yet")

    # Save index state
    state = {
        "last_indexed": datetime.now().isoformat(),
        "feedback_count": len(feedback),
        "lessons_count": len(lessons),
        "model": EMBEDDING_MODELS.get(model_key, model_key),
        "db_type": "lancedb",
        "version": "1.0",
        "features": ["similarity_threshold", "lru_cache", "bm25_hybrid"],
    }
    with open(INDEX_STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

    _metrics.log("index", {
        "feedback_count": len(feedback),
        "lessons_count": len(lessons),
        "model": model_key,
    })

    print(f"\nIndexing complete!")
    print(f"   Total documents: {len(feedback) + len(lessons)}")


def hybrid_search(
    query_text: str,
    n_results: int = 5,
    threshold: float = SIMILARITY_THRESHOLD,
    table_name: str = None,
    use_bm25: bool = True,
) -> List[Dict[str, Any]]:
    """Hybrid search combining BM25 + vector similarity"""
    start_time = time.time()

    db = get_lance_db()
    model = get_embedding_model()

    query_vector = get_embedding_with_cache(query_text, model)

    results = []
    tables_to_search = [table_name] if table_name else [FEEDBACK_TABLE, LESSONS_TABLE]

    for tbl_name in tables_to_search:
        try:
            if not table_exists(db, tbl_name):
                continue

            table = db.open_table(tbl_name)
            all_docs = table.to_pandas()

            vector_results = table.search(query_vector).limit(n_results * 2).to_list()

            bm25_scores = {}
            if use_bm25 and len(all_docs) > 0:
                bm25 = BM25()
                bm25.fit(all_docs["full_text"].tolist())
                bm25_results = bm25.search(query_text, top_k=n_results * 2)

                max_bm25 = max(s for _, s in bm25_results) if bm25_results else 1
                for idx, score in bm25_results:
                    doc_id = all_docs.iloc[idx]["id"]
                    bm25_scores[doc_id] = score / max_bm25 if max_bm25 > 0 else 0

            for r in vector_results:
                distance = r.get("_distance", 1.0)

                if distance > threshold:
                    continue

                vector_score = 1 - (distance / threshold)
                bm25_score = bm25_scores.get(r.get("id"), 0)
                combined_score = (VECTOR_WEIGHT * vector_score) + (BM25_WEIGHT * bm25_score)

                results.append({
                    "id": r.get("id", "unknown"),
                    "table": tbl_name,
                    "title": r.get("title", r.get("context", "Unknown")[:50]),
                    "text": r.get("full_text", "")[:200],
                    "distance": distance,
                    "combined_score": combined_score,
                    "metadata": {
                        "severity": r.get("severity"),
                        "tags": r.get("tags"),
                        "reward": r.get("reward"),
                    }
                })
        except Exception as e:
            print(f"   Error searching {tbl_name}: {e}")

    results.sort(key=lambda x: x['combined_score'], reverse=True)
    results = results[:n_results]

    latency_ms = (time.time() - start_time) * 1000
    _metrics.log("query", {
        "query": query_text[:50],
        "result_count": len(results),
        "latency_ms": latency_ms,
        "threshold": threshold,
        "use_bm25": use_bm25,
    })

    return results


def get_session_context() -> Dict[str, Any]:
    """Get relevant context for session start"""
    context = {
        "timestamp": datetime.now().isoformat(),
        "critical_lessons": [],
        "negative_patterns": [],
        "recommendations": [],
    }

    try:
        db = get_lance_db()

        # Get critical lessons
        if table_exists(db, LESSONS_TABLE):
            results = hybrid_search("critical high severity error mistake", n_results=5, table_name=LESSONS_TABLE)
            for r in results:
                severity = r.get("metadata", {}).get("severity", "medium")
                if severity in ["critical", "high"]:
                    context["critical_lessons"].append({
                        "title": r.get("title"),
                        "severity": severity,
                    })

        # Get negative feedback patterns
        if table_exists(db, FEEDBACK_TABLE):
            results = hybrid_search("negative thumbs down mistake error", n_results=5, table_name=FEEDBACK_TABLE)
            for r in results:
                if r.get("metadata", {}).get("reward", 0) < 0:
                    context["negative_patterns"].append({
                        "context": r.get("text", "")[:100],
                        "tags": r.get("metadata", {}).get("tags", ""),
                    })

        # Generate recommendations
        if context["critical_lessons"]:
            context["recommendations"].append("Review critical lessons before responding")

        tags = " ".join([p.get("tags", "") for p in context["negative_patterns"]])
        if "spread" in tags:
            context["recommendations"].append("Double-check spread calculations")
        if "testing" in tags:
            context["recommendations"].append("Remember to write tests (TDD)")
        if "security" in tags:
            context["recommendations"].append("Never commit tokens or secrets")

    except Exception as e:
        context["error"] = str(e)

    return context


def print_session_context():
    """Print session context for hooks"""
    context = get_session_context()

    print("\n" + "=" * 50)
    print("SEMANTIC MEMORY CONTEXT (LanceDB)")
    print("=" * 50)

    if context.get("error"):
        print(f"\nError: {context['error']}")
        print("   Run: python semantic-memory.py --index")
        return

    if context["critical_lessons"]:
        print("\nCRITICAL LESSONS:")
        for lesson in context["critical_lessons"]:
            print(f"   [{lesson['severity'].upper()}] {lesson['title']}")

    if context["negative_patterns"]:
        print("\nNEGATIVE PATTERNS TO AVOID:")
        for p in context["negative_patterns"]:
            print(f"   - {p['context']}")

    if context["recommendations"]:
        print("\nRECOMMENDATIONS:")
        for rec in context["recommendations"]:
            print(f"   * {rec}")

    print("\n" + "=" * 50)


def show_status():
    """Show index status"""
    print("\nSemantic Memory Status (LanceDB)")
    print("=" * 50)

    if INDEX_STATE_FILE.exists():
        with open(INDEX_STATE_FILE) as f:
            state = json.load(f)
        print(f"   Last indexed: {state.get('last_indexed', 'Never')}")
        print(f"   Feedback: {state.get('feedback_count', 0)}")
        print(f"   Lessons: {state.get('lessons_count', 0)}")
        print(f"   Model: {state.get('model', 'Unknown')}")
    else:
        print("   Index not built yet. Run --index first.")

    try:
        db = get_lance_db()
        tables = get_table_names(db)
        print(f"\n   Tables: {len(tables)}")
        for tbl_name in tables:
            table = db.open_table(tbl_name)
            print(f"      {tbl_name}: {len(table)} documents")
    except Exception as e:
        print(f"   LanceDB error: {e}")

    print("=" * 50)


def show_metrics():
    """Show query metrics"""
    summary = _metrics.get_summary(days=7)

    print("\nQuery Metrics (Last 7 Days)")
    print("=" * 50)
    print(f"   Total queries: {summary.get('total_queries', 0)}")
    print(f"   Avg latency: {summary.get('avg_latency_ms', 0):.1f}ms")
    print(f"   Feedback events: {summary.get('feedback_events', 0)}")
    print("=" * 50)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Semantic Memory (LanceDB + Hybrid Search)")
    parser.add_argument("--index", action="store_true", help="Index all feedback and lessons")
    parser.add_argument("--query", type=str, help="Hybrid search query")
    parser.add_argument("--context", action="store_true", help="Get session context")
    parser.add_argument("--status", action="store_true", help="Show index status")
    parser.add_argument("--metrics", action="store_true", help="Show query metrics")
    parser.add_argument("--model", type=str, choices=list(EMBEDDING_MODELS.keys()), default=DEFAULT_MODEL)
    parser.add_argument("-n", "--results", type=int, default=5, help="Number of results")

    args = parser.parse_args()

    if args.index:
        index_all(args.model)
    elif args.query:
        results = hybrid_search(args.query, n_results=args.results)
        print(f"\nFound {len(results)} results:\n")
        for i, r in enumerate(results, 1):
            print(f"{i}. [{r['table']}] {r['title']}")
            print(f"   Score: {r['combined_score']:.3f}")
            print(f"   Preview: {r['text'][:100]}...")
            print()
    elif args.context:
        print_session_context()
    elif args.status:
        show_status()
    elif args.metrics:
        show_metrics()
    else:
        parser.print_help()
        print("\nQuick Start:")
        print("   1. pip install lancedb sentence-transformers")
        print("   2. python semantic-memory.py --index")
        print("   3. python semantic-memory.py --query 'spread calculation'")
        print("   4. python semantic-memory.py --context")


if __name__ == "__main__":
    main()
