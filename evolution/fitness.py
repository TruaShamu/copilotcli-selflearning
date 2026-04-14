"""Fitness functions for evaluating evolved skills.

Uses LLM-as-judge with rubrics to score agent outputs on:
- Correctness (50%) — did the agent produce correct output?
- Procedure following (30%) — did it follow the skill's steps?
- Conciseness (20%) — appropriately concise?
- Length penalty — penalizes skill bloat near size limit

Returns both scalar scores AND textual feedback for GEPA's reflector.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import dspy

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

    Scores agent outputs on multiple dimensions and provides
    textual feedback that GEPA uses for reflective mutation.
    """

    def __init__(self, config: EvolutionConfig):
        import dspy

        class JudgeSignature(dspy.Signature):
            """Evaluate an agent's response against an expected behavior rubric.

            Score on three dimensions (0.0 to 1.0 each):
            1. correctness: Did the response correctly address the task?
            2. procedure_following: Did it follow the expected approach?
            3. conciseness: Was it appropriately concise?

            Provide specific, actionable feedback on what could be improved.
            """
            task_input: str = dspy.InputField(desc="The task the agent was given")
            expected_behavior: str = dspy.InputField(desc="Rubric for what a good response looks like")
            agent_output: str = dspy.InputField(desc="The agent's actual response")
            skill_text: str = dspy.InputField(desc="The skill instructions the agent followed")
            correctness: float = dspy.OutputField(desc="Score 0.0-1.0: correctness")
            procedure_following: float = dspy.OutputField(desc="Score 0.0-1.0: procedure following")
            conciseness: float = dspy.OutputField(desc="Score 0.0-1.0: conciseness")
            feedback: str = dspy.OutputField(desc="Specific, actionable feedback for improvement")

        self.config = config
        self.judge = dspy.ChainOfThought(JudgeSignature)

    def score(
        self,
        task_input: str,
        expected_behavior: str,
        agent_output: str,
        skill_text: str,
        artifact_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> FitnessScore:
        import dspy
        lm = dspy.LM(self.config.eval_model)
        with dspy.context(lm=lm):
            result = self.judge(
                task_input=task_input,
                expected_behavior=expected_behavior,
                agent_output=agent_output,
                skill_text=skill_text,
            )

        length_penalty = 0.0
        if artifact_size and max_size:
            ratio = artifact_size / max_size
            if ratio > 0.9:
                length_penalty = min(0.3, (ratio - 0.9) * 3.0)

        return FitnessScore(
            correctness=_parse_score(result.correctness),
            procedure_following=_parse_score(result.procedure_following),
            conciseness=_parse_score(result.conciseness),
            length_penalty=length_penalty,
            feedback=str(result.feedback),
        )


def skill_fitness_metric(
    example: dspy.Example,
    prediction: dspy.Prediction,
    trace=None,
) -> float:
    """DSPy-compatible metric for dspy.GEPA(metric=...).

    Fast heuristic scoring for optimization loop speed.
    Use LLMJudge for full evaluation on holdout set.
    """
    agent_output = getattr(prediction, "output", "") or ""
    expected = getattr(example, "expected_behavior", "") or ""

    if not agent_output.strip():
        return 0.0

    # Keyword overlap as fast proxy for correctness
    expected_words = set(expected.lower().split())
    output_words = set(agent_output.lower().split())
    if expected_words:
        overlap = len(expected_words & output_words) / len(expected_words)
        return min(1.0, 0.3 + (0.7 * overlap))

    return 0.5


def _parse_score(value) -> float:
    if isinstance(value, (int, float)):
        return min(1.0, max(0.0, float(value)))
    try:
        return min(1.0, max(0.0, float(str(value).strip())))
    except (ValueError, TypeError):
        return 0.5
