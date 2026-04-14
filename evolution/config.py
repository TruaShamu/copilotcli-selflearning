"""Configuration for skill evolution runs."""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class EvolutionConfig:
    """Configuration for a skill evolution optimization run."""

    # Skill search paths (in priority order)
    repo_skills_path: Path = field(default_factory=lambda: _find_repo_skills())
    user_skills_path: Path = field(default_factory=lambda: Path.home() / ".copilot" / "skills")

    # Session DB for eval data mining (Copilot CLI's native store)
    session_db_path: Path = field(
        default_factory=lambda: Path.home() / ".copilot" / "session-store.db"
    )

    # Optimization parameters
    iterations: int = 10
    population_size: int = 5

    # LLM configuration
    optimizer_model: str = "openai/gpt-4.1"
    eval_model: str = "openai/gpt-4.1-mini"
    judge_model: str = "openai/gpt-4.1"

    # Constraints
    max_skill_size: int = 20_000  # 20KB max
    max_prompt_growth: float = 0.25  # 25% max growth over baseline

    # Eval dataset
    eval_dataset_size: int = 20
    train_ratio: float = 0.5
    val_ratio: float = 0.25
    holdout_ratio: float = 0.25

    # Output
    output_dir: Path = field(default_factory=lambda: Path.home() / ".copilot" / "self-learning" / "evolution-runs")


def _find_repo_skills() -> Path:
    """Find the repo-level skills directory.

    Walks up from CWD looking for .github/skills/.
    """
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / ".github" / "skills"
        if candidate.is_dir():
            return candidate
        # Also check for git root marker
        if (parent / ".git").exists():
            return parent / ".github" / "skills"
    return cwd / ".github" / "skills"
