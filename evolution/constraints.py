"""Constraint validators for evolved skills.

Every candidate must pass ALL constraints or it's rejected.
"""

from dataclasses import dataclass
from typing import Optional

from .config import EvolutionConfig


@dataclass
class ConstraintResult:
    passed: bool
    constraint_name: str
    message: str
    details: Optional[str] = None


class ConstraintValidator:
    """Validates evolved skills against hard constraints."""

    def __init__(self, config: EvolutionConfig):
        self.config = config

    def validate_all(
        self,
        artifact_text: str,
        baseline_text: Optional[str] = None,
    ) -> list[ConstraintResult]:
        results = []
        results.append(self._check_size(artifact_text))
        results.append(self._check_non_empty(artifact_text))
        results.append(self._check_structure(artifact_text))
        if baseline_text:
            results.append(self._check_growth(artifact_text, baseline_text))
        return results

    def _check_size(self, text: str) -> ConstraintResult:
        size = len(text)
        limit = self.config.max_skill_size
        if size <= limit:
            return ConstraintResult(True, "size_limit", f"Size OK: {size:,}/{limit:,} chars")
        return ConstraintResult(False, "size_limit", f"Size exceeded: {size:,}/{limit:,} chars")

    def _check_growth(self, text: str, baseline: str) -> ConstraintResult:
        growth = (len(text) - len(baseline)) / max(1, len(baseline))
        limit = self.config.max_prompt_growth
        if growth <= limit:
            return ConstraintResult(True, "growth_limit", f"Growth OK: {growth:+.1%} (max {limit:+.1%})")
        return ConstraintResult(False, "growth_limit", f"Growth exceeded: {growth:+.1%} (max {limit:+.1%})")

    def _check_non_empty(self, text: str) -> ConstraintResult:
        if text.strip():
            return ConstraintResult(True, "non_empty", "Non-empty")
        return ConstraintResult(False, "non_empty", "Artifact is empty")

    def _check_structure(self, text: str) -> ConstraintResult:
        """Copilot CLI skills need YAML frontmatter with name + description."""
        issues = []
        full = text if text.strip().startswith("---") else ""
        if not full:
            # Body-only text (frontmatter already stripped) — skip structure check
            return ConstraintResult(True, "structure", "Body-only text (frontmatter preserved separately)")

        if "name:" not in text[:500]:
            issues.append("name field")
        if "description:" not in text[:1000]:
            issues.append("description field")

        if not issues:
            return ConstraintResult(True, "structure", "Valid frontmatter (name + description)")
        return ConstraintResult(False, "structure", f"Missing: {', '.join(issues)}")
