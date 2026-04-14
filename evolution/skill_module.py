"""Wraps a SKILL.md as a DSPy module for GEPA optimization.

The skill body (markdown after frontmatter) is the optimizable parameter.
GEPA mutates this text, evaluates results, and reflects on failures.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import dspy

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


class SkillModule:
    """DSPy module wrapping a skill for GEPA optimization.

    The skill_text is the parameter GEPA evolves. On each forward pass,
    the module injects the current skill text as instructions and asks
    the LLM to complete a task following those instructions.

    Requires dspy to be installed. Import is deferred to __init__.
    """

    def __init__(self, skill_text: str):
        import dspy

        class TaskWithSkill(dspy.Signature):
            """Complete a task following the provided skill instructions."""
            skill_instructions: str = dspy.InputField(desc="The skill instructions to follow")
            task_input: str = dspy.InputField(desc="The task to complete")
            output: str = dspy.OutputField(desc="Your response following the skill instructions")

        class _Module(dspy.Module):
            def __init__(self, text):
                super().__init__()
                self.skill_text = text
                self.predictor = dspy.ChainOfThought(TaskWithSkill)

            def forward(self, task_input: str):
                result = self.predictor(
                    skill_instructions=self.skill_text,
                    task_input=task_input,
                )
                return dspy.Prediction(output=result.output)

        self._module = _Module(skill_text)

    @property
    def skill_text(self):
        return self._module.skill_text

    def __call__(self, **kwargs):
        return self._module(**kwargs)

    def __getattr__(self, name):
        return getattr(self._module, name)
