"""Skill Indexer — scans vault directory, builds searchable index.

Reads every SKILL.md in the vault, extracts YAML frontmatter (name, description)
and body keywords, then writes a compact JSON index for the matcher.

Usage:
    python -m src.indexer --vault ~/.hermes/skills-vault --output ~/.cache/skill-router/index.json

Index format:
{
    "built_at": "ISO-8601",
    "version": "1.0",
    "total_skills": 576,
    "fields": {
        "coding": {
            "path": "coding/",
            "skills": [
                {
                    "name": "python-patterns",
                    "description": "Pythonic idioms, PEP 8 standards...",
                    "keywords": ["python", "pep8", "idioms", "patterns", "type-hints"],
                    "creator": "ecc",
                    "file_count": 3,
                },
                ...
            ]
        },
        ...
    }
}
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

# ── Helpers ──────────────────────────────────────────────

STOP_WORDS: set[str] = {
    "the", "and", "for", "use", "when", "this", "with", "that", "your",
    "from", "into", "over", "each", "will", "also", "not", "are", "has",
    "was", "its", "can", "may", "all", "any", "our", "you", "have", "had",
    "been", "being", "both", "but", "did", "does", "doing", "few", "more",
    "most", "other", "same", "some", "such", "than", "too", "very", "just",
    "because", "about", "what", "which", "who", "how", "where", "why",
}


def _parse_frontmatter(text: str) -> tuple[str, dict[str, str]]:
    """Extract YAML frontmatter from SKILL.md. Returns (body, frontmatter_dict)."""
    if not text.startswith("---"):
        return text, {}

    parts = text.split("---", 2)
    if len(parts) < 3:
        return text, {}

    raw = parts[1].strip()
    body = parts[2].strip() if len(parts) > 2 else ""

    fm: dict[str, str] = {}
    current_key: str | None = None
    for line in raw.split("\n"):
        line = line.rstrip()
        # Skip empty lines
        if not line.strip():
            if current_key:
                fm[current_key] += "\n"
            continue

        # Top-level key: value
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)", line)
        if match:
            current_key = match.group(1)
            value = match.group(2).strip().strip('"').strip("'")
            if value == "|" or value == ">-":
                value = ""  # block scalar starts on next line
            fm[current_key] = value
        elif current_key:
            # Continuation line for block scalar
            stripped = line.lstrip()
            separator = " " if not fm[current_key].endswith("\n") else ""
            fm[current_key] += separator + stripped

    return body, fm


def _extract_keywords(text: str, min_length: int = 3, max_keywords: int = 30) -> list[str]:
    """Extract meaningful keywords from text, filtering stop words."""
    words = re.findall(r"[a-z0-9_]{3,}", text.lower())
    filtered = [w for w in words if w not in STOP_WORDS]
    counter = Counter(filtered)
    return [word for word, _ in counter.most_common(max_keywords)]


def _count_files(skill_dir: Path) -> int:
    """Count non-hidden files in a skill directory."""
    return sum(1 for f in skill_dir.iterdir() if not f.name.startswith(".") and f.is_file())


# ── Main Indexer ─────────────────────────────────────────

def build_index(
    vault_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Scan vault, build index dict. Optionally write to output_path."""
    vault = Path(vault_path).expanduser()
    if not vault.is_dir():
        raise ValueError(f"Vault path does not exist or is not a directory: {vault}")

    index: dict[str, Any] = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": "1.0",
        "total_skills": 0,
        "fields": {},
    }

    for field_dir in sorted(vault.iterdir()):
        if not field_dir.is_dir() or field_dir.name.startswith("."):
            continue

        field_name = field_dir.name
        skills: list[dict[str, Any]] = []

        for skill_dir in sorted(field_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("."):
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue

            text = skill_md.read_text(encoding="utf-8", errors="replace")
            body, fm = _parse_frontmatter(text)

            # Directory names are the activation identity used by vault_manager.
            # Keep the frontmatter value for display/search without breaking routing.
            name = skill_dir.name
            display_name = fm.get("name", name)
            description = fm.get("description", "").replace("\n", " ").strip()

            # Extract keywords from directory name + metadata + body (combined)
            combined = f"{name} {display_name} {description} {body[:2000]}"
            keywords = _extract_keywords(combined)

            # Infer creator from skill folder name (e.g., "ecc__python-patterns" → "ecc")
            creator = ""
            folder_name = skill_dir.name
            if "__" in folder_name:
                creator = folder_name.split("__")[0]

            skills.append({
                "name": name,
                "display_name": display_name,
                "description": description[:300],
                "keywords": keywords,
                "creator": creator,
                "file_count": _count_files(skill_dir),
            })

        if skills:
            index["fields"][field_name] = {
                "path": f"{field_name}/",
                "skills": sorted(skills, key=lambda s: s["name"]),
            }
            index["total_skills"] += len(skills)

    # Write to cache
    if output_path:
        out = Path(output_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(index, indent=2), encoding="utf-8")
        out.with_suffix(".json.tmp").unlink(missing_ok=True)  # cleanup stale temp

    return index


def load_index(index_path: str | Path) -> dict[str, Any]:
    """Load a previously built index from disk."""
    path = Path(index_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Index not found: {path}. Run `skill-router index` first.")
    return json.loads(path.read_text(encoding="utf-8"))


# ── CLI ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build skill index from vault")
    parser.add_argument("--vault", default="~/.hermes/skills-vault", help="Path to skills vault")
    parser.add_argument("--output", default="~/.cache/skill-router/index.json", help="Output path for index")
    args = parser.parse_args()

    result = build_index(args.vault, args.output)
    print(f"Indexed {result['total_skills']} skills across {len(result['fields'])} fields → {args.output}")