"""Fitness functions for evaluating evolved skills.

Uses LLM-as-judge with rubrics to score agent outputs on:
- Correctness (50%) — did the agent produce correct output?
- Procedure following (30%) — did it follow the skill's steps?
- Conciseness (20%) — appropriately concise?
- Length penalty — penalizes skill bloat near size limit

Returns both scalar scores AND textual feedback for GEPA's reflector
via oa.log() in the evaluator.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from .config import EvolutionConfig


@dataclass
class FitnessScore:
    """Multi-dimensional fitness score with feedback for GEPA."""
    correctness: float = 0.0
    procedure_following: float = 0.0
    conciseness: float = 0.0
    length_penalty: float = 0.0
    feedback: str = ""

    @property
    def composite(self) -> float:
        raw = (
            0.5 * self.correctness
            + 0.3 * self.procedure_following
            + 0.2 * self.conciseness
        )
        return max(0.0, raw - self.length_penalty)


class LLMJudge:
    """LLM-as-judge scorer with rubric-based evaluation.

    Scores skill quality on multiple dimensions and provides
    textual feedback that GEPA uses for reflective mutation via oa.log().

    Uses the OpenAI API directly (no DSPy dependency).
    """

    JUDGE_PROMPT = """\
You are evaluating the quality of a Copilot CLI skill (markdown instructions
that an AI coding agent follows to complete tasks).

Given:
- task_input: what the user asked
- expected_behavior: rubric for a correct response
- skill_text: the skill instructions being evaluated
- agent_output: what the agent produced (may be empty for text-only evaluation)

Score on three dimensions (0.0 to 1.0 each):
1. correctness: Would following this skill produce the correct output for this task?
2. procedure_following: Does the skill clearly define the right steps/approach?
3. conciseness: Is the skill appropriately concise without missing key steps?

Respond in JSON:
{
  "correctness": 0.0-1.0,
  "procedure_following": 0.0-1.0,
  "conciseness": 0.0-1.0,
  "feedback": "Specific, actionable feedback on what could be improved in the skill text"
}"""

    def __init__(self, config: EvolutionConfig):
        self.config = config

    def score(
        self,
        task_input: str,
        expected_behavior: str,
        agent_output: str,
        skill_text: str,
        artifact_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> FitnessScore:
        from openai import OpenAI

        client = OpenAI()

        user_msg = (
            f"## Task Input\n{task_input}\n\n"
            f"## Expected Behavior\n{expected_behavior}\n\n"
            f"## Skill Text\n{skill_text}\n\n"
            f"## Agent Output\n{agent_output or '(no agent output — evaluate skill text quality only)'}"
        )

        try:
            response = client.chat.completions.create(
                model=self.config.eval_model.removeprefix("openai/"),
                messages=[
                    {"role": "system", "content": self.JUDGE_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            result = json.loads(response.choices[0].message.content)
        except Exception as e:
            return FitnessScore(feedback=f"Judge error: {e}")

        length_penalty = 0.0
        if artifact_size and max_size:
            ratio = artifact_size / max_size
            if ratio > 0.9:
                length_penalty = min(0.3, (ratio - 0.9) * 3.0)

        return FitnessScore(
            correctness=_parse_score(result.get("correctness", 0.5)),
            procedure_following=_parse_score(result.get("procedure_following", 0.5)),
            conciseness=_parse_score(result.get("conciseness", 0.5)),
            length_penalty=length_penalty,
            feedback=str(result.get("feedback", "")),
        )


def _parse_score(value) -> float:
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    try:
        return min(1.0, max(0.0, float(str(value).strip())))
    except (ValueError, TypeError):
        return 0.5
