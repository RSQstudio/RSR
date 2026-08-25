"""Skill Matcher — matches user intent to skills using keyword or semantic search.

Two strategies:
  - keyword (default): fast, zero API cost, uses Jaccard overlap between user tokens and skill index
  - semantic: slower, more accurate, requires embedding model (sentence-transformers)
  - hybrid: keyword first, semantic fallback for low-confidence matches

Usage:
    from src.matcher import SkillMatcher
    index = load_index("~/.cache/skill-router/index.json")
    matcher = SkillMatcher(index, strategy="keyword")
    results = matcher.match("write a cold email for enterprise prospects")
    # → [("copywriting", "cold-email-templates-34", 0.87), ("sales", "cold-outbound-optimizer", 0.72), ...]
"""

from __future__ import annotations

import re
from typing import Any


# ── Keyword matching ────────────────────────────────────

STOP_WORDS: set[str] = {
    "the", "and", "for", "use", "when", "this", "with", "that", "your",
    "from", "into", "over", "each", "will", "also", "not", "are", "has",
    "was", "its", "can", "may", "all", "any", "our", "you", "have", "had",
    "a", "an", "in", "on", "at", "to", "of", "is", "it", "be", "or", "by",
    "my", "me", "i", "we", "he", "she", "they", "do", "does", "but", "if",
    "so", "no", "up", "out", "get", "need", "want", "like", "now",
}


def _tokenize(text: str) -> set[str]:
    """Break text into normalized keyword tokens."""
    words = re.findall(r"[a-z0-9_]{2,}", text.lower())
    return {w for w in words if w not in STOP_WORDS}


def _keyword_score(user_tokens: set[str], skill_entry: dict[str, Any]) -> float:
    """Score a skill against user tokens using weighted Jaccard.

    Weights: name match ×3, keyword match ×2, description match ×1.
    """
    name_tokens = _tokenize(skill_entry.get("name", ""))
    desc_tokens = _tokenize(skill_entry.get("description", ""))
    kw_tokens = set(skill_entry.get("keywords", []))

    name_overlap = len(user_tokens & name_tokens)
    kw_overlap = len(user_tokens & kw_tokens)
    desc_overlap = len(user_tokens & desc_tokens)

    weighted_sum = (name_overlap * 3) + (kw_overlap * 2) + desc_overlap
    union = len(user_tokens | name_tokens | kw_tokens | desc_tokens)

    if union == 0:
        return 0.0

    return min(1.0, weighted_sum / union * 2.0)  # ×2 boost so good matches hit 0.7-0.9


# ── Field-level intent signals ──────────────────────────

FIELD_SIGNALS: dict[str, list[str]] = {
    "coding": [
        "code", "build", "debug", "refactor", "api", "architecture", "devops",
        "ci/cd", "test", "deploy", "python", "golang", "rust", "javascript",
        "typescript", "react", "django", "docker", "kubernetes", "sql", "ml",
        "ai model", "training", "inference", "compile", "bug", "fix", "pr",
        "backend", "frontend", "fullstack", "cli", "library", "sdk", "mcp",
    ],
    "consulting": [
        "strategy", "framework", "consulting", "board deck", "mece", "hypothesis",
        "market sizing", "m&a", "due diligence", "executive presentation",
        "mckinsey", "bain", "bcg", "problem solving", "issue tree", "pyramid",
        "pareto", "case study", "business case", "valuation", "roadmap",
    ],
    "marketing": [
        "campaign", "seo", "content", "video", "social media", "launch",
        "brand", "design", "competitive analysis", "market", "advertising",
        "ads", "tiktok", "youtube", "twitter/x", "influencer", "growth",
        "marketing", "promotion", "awareness", "analytics", "conversion",
    ],
    "sales": [
        "pipeline", "crm", "deal", "account", "abm", "outbound", "cold email",
        "sdr", "signal", "lead", "negotiation", "linkedin", "prospect",
        "close", "revenue", "quota", "territory", "enrichment", "sales",
        "bdr", "ae", "objection", "demo", "pitch", "proposal",
    ],
    "finance": [
        "accounting", "invoice", "tax", "cash flow", "p&l", "cfo",
        "financial model", "revenue", "budget", "investment", "valuation",
        "bookkeeping", "reconciliation", "payroll", "expense", "profit",
        "loss", "balance sheet", "audit", "forecast", "quickbooks",
    ],
    "hr": [
        "recruiting", "onboarding", "performance review", "hris", "compensation",
        "benefits", "policy", "compliance", "employee", "hiring", "interview",
        "offer", "termination", "dei", "diversity", "workforce", "talent",
        "hr", "people ops", "offboarding", "retention", "culture",
    ],
    "copywriting": [
        "write", "edit", "copy", "email draft", "subject line", "hook",
        "storytelling", "personalize", "headline", "copywriting", "message",
        "messaging", "tone", "voice", "cta", "copy", "phrase", "wording",
    ],
    "customer-support": [
        "support ticket", "triage", "customer help", "refund", "escalation",
        "knowledge base", "zendesk", "intercom", "helpdesk", "support",
        "complaint", "issue", "resolve", "troubleshoot",
    ],
    "finops": [
        "cloud cost", "aws", "azure", "gcp", "billing", "finops",
        "optimization", "saving", "waste", "reserved instance", "spot",
    ],
    "project-management": [
        "project plan", "sprint", "roadmap", "timeline", "risk", "stakeholder",
        "task tracking", "milestone", "jira", "asana", "deadline", "deliverable",
        "gantt", "kanban", "waterfall", "agile", "scrum",
    ],
}


# ── Matcher class ────────────────────────────────────────

class SkillMatcher:
    def __init__(
        self,
        index: dict[str, Any],
        strategy: str = "keyword",
        min_confidence: float = 0.3,
        max_results: int = 15,
    ) -> None:
        self.index = index
        self.strategy = strategy
        self.min_confidence = min_confidence
        self.max_results = max_results

    def _determine_fields(self, message: str) -> list[str]:
        """Quick field resolution: which fields does this message match?"""
        user_tokens = _tokenize(message)
        scores: dict[str, int] = {}

        for field, signals in FIELD_SIGNALS.items():
            field_tokens = set()
            for s in signals:
                field_tokens.update(_tokenize(s))
            overlap = len(user_tokens & field_tokens)
            if overlap > 0:
                scores[field] = overlap

        # Return fields that scored, sorted by score
        return [f for f, _ in sorted(scores.items(), key=lambda x: -x[1])]

    def match(self, message: str) -> list[tuple[str, str, float]]:
        """Match user message to skills. Returns [(field, skill_name, confidence_score), ...]"""

        # Step 1: determine which fields to search
        candidate_fields = self._determine_fields(message)
        if not candidate_fields:
            # Fallback: search all fields with lower confidence
            candidate_fields = list(self.index.get("fields", {}).keys())

        # Step 2: score every skill in candidate fields
        user_tokens = _tokenize(message)
        results: list[tuple[str, str, float]] = []

        for field in candidate_fields:
            field_data = self.index.get("fields", {}).get(field)
            if not field_data:
                continue

            for skill in field_data.get("skills", []):
                score = _keyword_score(user_tokens, skill)
                if score >= self.min_confidence:
                    results.append((field, skill["name"], round(score, 3)))

        # Step 3: sort and cap
        results.sort(key=lambda x: -x[2])
        return results[:self.max_results]

    def route(self, message: str) -> dict[str, Any]:
        """Full routing: match skills, group by field, return structured result."""
        matches = self.match(message)

        # Group by field
        fields: dict[str, list[dict[str, Any]]] = {}
        for field, name, score in matches:
            fields.setdefault(field, []).append({"name": name, "score": score})

        # Determine top field
        top_field = matches[0][0] if matches else "none"

        return {
            "intent_message": message[:200],
            "top_field": top_field,
            "fields_found": list(fields.keys()),
            "field_count": len(fields),
            "skill_count": len(matches),
            "recommendations": fields,
            "all_matches": [{"field": f, "skill": n, "score": s} for f, n, s in matches],
        }


# ── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from indexer import load_index

    parser = argparse.ArgumentParser(description="Match user intent to skills")
    parser.add_argument("message", help="User input to match against")
    parser.add_argument("--index", default="~/.cache/skill-router/index.json", help="Path to index file")
    parser.add_argument("--strategy", default="keyword", choices=["keyword", "hybrid"])
    parser.add_argument("--confidence", type=float, default=0.3)
    parser.add_argument("--max", type=int, default=15)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    index = load_index(args.index)
    matcher = SkillMatcher(index, strategy=args.strategy, min_confidence=args.confidence, max_results=args.max)
    result = matcher.route(args.message)

    if args.json:
        import json as _json
        print(_json.dumps(result, indent=2))
    else:
        print(f"Top field: {result['top_field']}")
        print(f"Found in: {', '.join(result['fields_found'])}")
        print(f"Skills recommended: {result['skill_count']}")
        for field, skills in result["recommendations"].items():
            print(f"\n  [{field}]")
            for s in skills:
                print(f"    {s['name']} ({s['score']})")