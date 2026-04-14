"""Evaluation dataset generation for skill evolution.

Three sources:
A) Synthetic — LLM reads a skill and generates test cases
B) SessionDB — mine real usage from our local SQLite FTS5 store
C) Golden — hand-curated JSONL files
"""

from __future__ import annotations

import json
import random
import sqlite3
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import dspy

from .config import EvolutionConfig


@dataclass
class EvalExample:
    """A single evaluation example."""
    task_input: str
    expected_behavior: str
    difficulty: str = "medium"
    category: str = "general"
    source: str = "synthetic"

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, d: dict) -> "EvalExample":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class EvalDataset:
    """Train/val/holdout split of evaluation examples."""
    train: list[EvalExample] = field(default_factory=list)
    val: list[EvalExample] = field(default_factory=list)
    holdout: list[EvalExample] = field(default_factory=list)

    @property
    def all_examples(self) -> list[EvalExample]:
        return self.train + self.val + self.holdout

    def save(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        for name, data in [("train", self.train), ("val", self.val), ("holdout", self.holdout)]:
            with open(path / f"{name}.jsonl", "w") as f:
                for ex in data:
                    f.write(json.dumps(ex.to_dict()) + "\n")

    @classmethod
    def load(cls, path: Path) -> "EvalDataset":
        ds = cls()
        for name in ["train", "val", "holdout"]:
            fpath = path / f"{name}.jsonl"
            if fpath.exists():
                examples = []
                with open(fpath) as f:
                    for line in f:
                        if line.strip():
                            examples.append(EvalExample.from_dict(json.loads(line)))
                setattr(ds, name, examples)
        return ds

    def to_dspy_examples(self, split: str = "train") -> list:
        import dspy
        return [
            dspy.Example(
                task_input=ex.task_input,
                expected_behavior=ex.expected_behavior,
            ).with_inputs("task_input")
            for ex in getattr(self, split)
        ]


# ─── Synthetic dataset generation ───────────────────────────────────────


class SyntheticDatasetBuilder:
    """Generate eval datasets by having an LLM read the skill and create test cases."""

    def __init__(self, config: EvolutionConfig):
        import dspy

        class GenerateTestCases(dspy.Signature):
            """Generate realistic evaluation test cases for a Copilot CLI skill.

            Given the full text of a skill, generate diverse test cases that exercise
            different aspects. Each test case needs:
            - task_input: what a user would actually ask
            - expected_behavior: rubric for what a good response should contain (NOT exact text)
            - difficulty: easy, medium, hard
            - category: what aspect of the skill this tests
            """
            artifact_text: str = dspy.InputField(desc="Full text of the skill being tested")
            num_cases: int = dspy.InputField(desc="Number of test cases to generate")
            test_cases: str = dspy.OutputField(
                desc="JSON array of objects with: task_input, expected_behavior, difficulty, category"
            )

        self.config = config
        self.generator = dspy.ChainOfThought(GenerateTestCases)

    def generate(self, artifact_text: str, num_cases: Optional[int] = None) -> EvalDataset:
        n = num_cases or self.config.eval_dataset_size
        lm = dspy.LM(self.config.judge_model)

        with dspy.context(lm=lm):
            result = self.generator(artifact_text=artifact_text, num_cases=n)

        try:
            cases_raw = json.loads(result.test_cases)
        except json.JSONDecodeError:
            match = re.search(r"\[.*\]", result.test_cases, re.DOTALL)
            if match:
                cases_raw = json.loads(match.group())
            else:
                raise ValueError(f"Could not parse test cases: {result.test_cases[:200]}")

        examples = [
            EvalExample(
                task_input=c.get("task_input", ""),
                expected_behavior=c.get("expected_behavior", ""),
                difficulty=c.get("difficulty", "medium"),
                category=c.get("category", "general"),
                source="synthetic",
            )
            for c in cases_raw
            if c.get("task_input") and c.get("expected_behavior")
        ]

        random.shuffle(examples)
        return _split(examples, self.config)


# ─── Session DB mining ──────────────────────────────────────────────────


class SessionDBMiner:
    """Mine evaluation data from Copilot CLI's native session store.

    Searches ~/.copilot/session-store.db (FTS5-indexed) for session turns
    relevant to the skill, then uses an LLM to convert them into
    (task_input, expected_behavior) eval pairs.
    """

    def __init__(self, config: EvolutionConfig):
        import dspy

        class ConvertToEval(dspy.Signature):
            """Convert a real conversation excerpt into an evaluation test case."""
            skill_name: str = dspy.InputField(desc="Name of the skill")
            conversation_snippet: str = dspy.InputField(desc="Real conversation excerpt")
            task_input: str = dspy.OutputField(desc="Generalized user request")
            expected_behavior: str = dspy.OutputField(desc="Rubric for correct response")

        self.config = config
        self.converter = dspy.ChainOfThought(ConvertToEval)

    def mine(self, skill_name: str, skill_text: str) -> EvalDataset:
        db_path = self.config.session_db_path
        if not db_path.exists():
            return EvalDataset()

        # Open read-only to avoid locking the active session store
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Escape hyphens for FTS5 — default tokenizer treats them as column operators
        safe_name = re.sub(r'(?<!")(\b\w+-\w+(?:-\w+)*\b)(?!")', r'"\1"', skill_name)

        try:
            rows = conn.execute(
                """SELECT si.session_id, si.source_type, si.content,
                          s.summary
                   FROM search_index si
                   JOIN sessions s ON si.session_id = s.id
                   WHERE search_index MATCH ?
                   ORDER BY rank
                   LIMIT 50""",
                (safe_name,),
            ).fetchall()
        except Exception:
            conn.close()
            return EvalDataset()

        if not rows:
            conn.close()
            return EvalDataset()

        # Group by session and build conversation snippets
        sessions: dict[str, list] = {}
        for row in rows:
            sid = row["session_id"]
            if sid not in sessions:
                sessions[sid] = []
            sessions[sid].append(
                f"[{row['source_type'].upper()}]: {row['content'][:500]}"
            )

        # Also load actual turns for richer context
        for sid in list(sessions.keys())[:10]:
            turn_rows = conn.execute(
                """SELECT turn_index, user_message, assistant_response
                   FROM turns WHERE session_id = ?
                   ORDER BY turn_index LIMIT 6""",
                (sid,),
            ).fetchall()
            for r in turn_rows:
                if r["user_message"]:
                    sessions[sid].append(f"[USER]: {r['user_message'][:500]}")
                if r["assistant_response"]:
                    sessions[sid].append(f"[ASSISTANT]: {r['assistant_response'][:500]}")

        conn.close()

        # Convert each session's snippet into eval examples
        lm = dspy.LM(self.config.judge_model)
        examples = []

        with dspy.context(lm=lm):
            for sid, turns in list(sessions.items())[:10]:
                snippet = "\n\n".join(turns[:6])
                try:
                    result = self.converter(
                        skill_name=skill_name,
                        conversation_snippet=snippet,
                    )
                    examples.append(
                        EvalExample(
                            task_input=result.task_input,
                            expected_behavior=result.expected_behavior,
                            source="sessiondb",
                        )
                    )
                except Exception:
                    continue

        random.shuffle(examples)
        return _split(examples, self.config)


# ─── Golden dataset loading ─────────────────────────────────────────────


class GoldenDatasetLoader:
    @staticmethod
    def load(path: Path, config: EvolutionConfig) -> EvalDataset:
        if (path / "train.jsonl").exists():
            return EvalDataset.load(path)

        golden_file = path if path.suffix == ".jsonl" else path / "golden.jsonl"
        if not golden_file.exists():
            raise FileNotFoundError(f"No golden dataset at {golden_file}")

        examples = []
        with open(golden_file) as f:
            for line in f:
                if line.strip():
                    examples.append(EvalExample.from_dict(json.loads(line)))

        random.shuffle(examples)
        return _split(examples, config)


# ─── Helpers ────────────────────────────────────────────────────────────


def _split(examples: list[EvalExample], config: EvolutionConfig) -> EvalDataset:
    n = len(examples)
    n_train = max(1, int(n * config.train_ratio))
    n_val = max(1, int(n * config.val_ratio))
    return EvalDataset(
        train=examples[:n_train],
        val=examples[n_train : n_train + n_val],
        holdout=examples[n_train + n_val :],
    )
