"""Skill file utilities — find, load, and reassemble SKILL.md files.

No DSPy wrapping. GEPA optimize_anything operates on raw skill text directly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .config import EvolutionConfig


def find_skill(skill_name: str, config: EvolutionConfig) -> Optional[Path]:
    """Find a skill by name across repo and user skill directories.

    Search order:
    1. .github/skills/<name>/SKILL.md (repo-level)
    2. ~/.copilot/skills/<name>/SKILL.md (user-level)
    3. Fuzzy match on 'name:' in frontmatter
    """
    for skills_dir in [config.repo_skills_path, config.user_skills_path]:
        if not skills_dir.exists():
            continue
        # Direct match
        direct = skills_dir / skill_name / "SKILL.md"
        if direct.exists():
            return direct
        # Recursive search
        for skill_md in skills_dir.rglob("SKILL.md"):
            if skill_md.parent.name == skill_name:
                return skill_md

    # Fuzzy: check frontmatter name field
    for skills_dir in [config.repo_skills_path, config.user_skills_path]:
        if not skills_dir.exists():
            continue
        for skill_md in skills_dir.rglob("SKILL.md"):
            try:
                header = skill_md.read_text(encoding="utf-8")[:500]
                if f"name: {skill_name}" in header or f'name: "{skill_name}"' in header:
                    return skill_md
            except Exception:
                continue

    return None


def load_skill(skill_path: Path) -> dict:
    """Load and parse a SKILL.md into components.

    Returns:
        {
            "path": Path,
            "raw": str,
            "frontmatter": str,
            "body": str,
            "name": str,
            "description": str,
        }
    """
    raw = skill_path.read_text(encoding="utf-8")

    frontmatter = ""
    body = raw
    if raw.strip().startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            body = parts[2].strip()

    name = ""
    description = ""
    for line in frontmatter.split("\n"):
        stripped = line.strip()
        if stripped.startswith("name:"):
            name = stripped.split(":", 1)[1].strip().strip("'\"")
        elif stripped.startswith("description:"):
            description = stripped.split(":", 1)[1].strip().strip("'\"")

    return {
        "path": skill_path,
        "raw": raw,
        "frontmatter": frontmatter,
        "body": body,
        "name": name,
        "description": description,
    }


def reassemble_skill(frontmatter: str, evolved_body: str) -> str:
    """Reassemble a skill file from frontmatter + evolved body."""
    return f"---\n{frontmatter}\n---\n\n{evolved_body}\n"
