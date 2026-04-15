"""Evaluation dataset generation for skill evolution.

Three sources:
A) Synthetic — LLM reads a skill and generates test cases
B) SessionDB — mine real usage from our local SQLite FTS5 store
C) Golden — hand-curated JSONL files
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

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


# ─── Synthetic dataset generation ───────────────────────────────────────


SYNTHETIC_PROMPT = """\
Generate realistic evaluation test cases for a Copilot CLI skill.

Given the full text of a skill, generate diverse test cases that exercise
different aspects. Each test case needs:
- task_input: what a user would actually ask
- expected_behavior: rubric for what a good response should contain (NOT exact text)
- difficulty: easy, medium, hard
- category: what aspect of the skill this tests

Respond in JSON: {{"test_cases": [<{num_cases} objects with task_input, expected_behavior, difficulty, category>]}}"""


class SyntheticDatasetBuilder:
    """Generate eval datasets by having an LLM read the skill and create test cases."""

    def __init__(self, config: EvolutionConfig):
        from openai import OpenAI
        self.config = config
        self.client = OpenAI()

    def generate(self, artifact_text: str, num_cases: Optional[int] = None) -> EvalDataset:
        n = num_cases or self.config.eval_dataset_size

        response = self.client.chat.completions.create(
            model=self.config.judge_model.removeprefix("openai/"),
            messages=[
                {"role": "system", "content": SYNTHETIC_PROMPT.format(num_cases=n)},
                {"role": "user", "content": f"## Skill Text\n\n{artifact_text}"},
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )

        try:
            raw = json.loads(response.choices[0].message.content)
            cases_raw = raw.get("test_cases", raw.get("cases", []))
        except (json.JSONDecodeError, AttributeError):
            text = response.choices[0].message.content
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                cases_raw = json.loads(match.group())
            else:
                raise ValueError(f"Could not parse test cases: {text[:200]}")

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


CONVERT_PROMPT = """\
Convert a real Copilot CLI conversation excerpt into an evaluation test case.
Extract:
- task_input: a generalized version of what the user was trying to do
- expected_behavior: rubric for what a correct response should contain

Respond in JSON: {"task_input": "...", "expected_behavior": "..."}"""


class SessionDBMiner:
    """Mine evaluation data from Copilot CLI's native session store.

    Searches ~/.copilot/session-store.db (FTS5-indexed) for session turns
    relevant to the skill, then uses an LLM to convert them into
    (task_input, expected_behavior) eval pairs.
    """

    def __init__(self, config: EvolutionConfig):
        from openai import OpenAI
        self.config = config
        self.client = OpenAI()

    def mine(self, skill_name: str, skill_text: str) -> EvalDataset:
        db_path = self.config.session_db_path
        if not db_path.exists():
            return EvalDataset()

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Escape hyphens for FTS5
        _fts5_hyphen_re = re.compile(r'(?<!")(\b\w+-\w+(?:-\w+)*\b)(?!")')
        safe_name = _fts5_hyphen_re.sub(r'"\1"', skill_name)

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

        # Load actual turns for richer context
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
        examples = []

        for sid, turns in list(sessions.items())[:10]:
            snippet = "\n\n".join(turns[:6])
            try:
                response = self.client.chat.completions.create(
                    model=self.config.judge_model.removeprefix("openai/"),
                    messages=[
                        {"role": "system", "content": CONVERT_PROMPT},
                        {"role": "user", "content": f"Skill: {skill_name}\n\n{snippet}"},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3,
                )
                result = json.loads(response.choices[0].message.content)
                examples.append(
                    EvalExample(
                        task_input=result.get("task_input", ""),
                        expected_behavior=result.get("expected_behavior", ""),
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
