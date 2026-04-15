"""Evolve a Copilot CLI skill using GEPA optimize_anything.

Usage:
    python -m evolution.evolve_skill --skill self-learning --max-calls 100
    python -m evolution.evolve_skill --skill adr-creator --eval-source sessiondb
    python -m evolution.evolve_skill --skill git-manager --eval-source golden --dataset-path datasets/git-manager/
    python -m evolution.evolve_skill --skill self-learning --resume  # resume from log_dir
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import click

from .config import EvolutionConfig
from .skill_module import find_skill, load_skill, reassemble_skill
from .fitness import LLMJudge, FitnessScore
from .constraints import ConstraintValidator
from .dataset_builder import (
    SyntheticDatasetBuilder,
    SessionDBMiner,
    GoldenDatasetLoader,
    EvalDataset,
)

# Optional rich console — fall back to print if not installed
try:
    from rich.console import Console

    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

    class _FallbackConsole:
        def print(self, *args, **kwargs):
            import re
            text = " ".join(str(a) for a in args)
            text = re.sub(r"\[/?[a-z_ ]+\]", "", text)
            print(text)

    console = _FallbackConsole()


def evolve(
    skill_name: str,
    max_calls: int = 100,
    eval_source: str = "synthetic",
    dataset_path: Optional[str] = None,
    optimizer_model: str = "openai/gpt-4.1",
    eval_model: str = "openai/gpt-4.1-mini",
    dry_run: bool = False,
    resume: bool = False,
):
    """Main evolution loop — GEPA optimize_anything on SKILL.md body."""

    import gepa.optimize_anything as oa
    from gepa.optimize_anything import optimize_anything, GEPAConfig, EngineConfig

    config = EvolutionConfig(
        iterations=max_calls,
        optimizer_model=optimizer_model,
        eval_model=eval_model,
        judge_model=optimizer_model,
    )

    # ── 1. Find and load the skill ──────────────────────────────────────
    console.print(f"\n[bold cyan]🧬 Skill Evolution[/bold cyan] — {skill_name}\n")

    skill_path = find_skill(skill_name, config)
    if not skill_path:
        console.print(f"[red]✗ Skill '{skill_name}' not found[/red]")
        console.print(f"  Searched: {config.repo_skills_path}")
        console.print(f"  Searched: {config.user_skills_path}")
        sys.exit(1)

    skill = load_skill(skill_path)
    console.print(f"  Loaded: {skill_path}")
    console.print(f"  Name: {skill['name']}")
    console.print(f"  Size: {len(skill['raw']):,} chars")

    # ── 2. Build or load evaluation dataset ─────────────────────────────
    console.print(f"\n[bold]Building eval dataset[/bold] (source: {eval_source})")

    dataset = _build_dataset(eval_source, dataset_path, skill_name, skill, config)

    if dry_run:
        console.print(f"\n[bold green]DRY RUN — setup OK.[/bold green]")
        console.print(f"  Dataset: {len(dataset.all_examples)} examples")
        console.print(f"  Would run GEPA optimize_anything (max {max_calls} metric calls)")
        return

    # Save dataset for reuse
    save_path = config.output_dir / "datasets" / skill_name
    dataset.save(save_path)
    console.print(f"  Split: {len(dataset.train)} train / {len(dataset.val)} val / {len(dataset.holdout)} holdout")

    # ── 3. Validate baseline constraints ────────────────────────────────
    console.print(f"\n[bold]Baseline constraints[/bold]")
    validator = ConstraintValidator(config)
    for c in validator.validate_all(skill["body"]):
        icon = "✓" if c.passed else "✗"
        console.print(f"  {icon} {c.constraint_name}: {c.message}")

    # ── 4. Set up evaluator + GEPA ──────────────────────────────────────
    console.print(f"\n[bold]Configuring optimizer[/bold]")
    console.print(f"  Engine: GEPA optimize_anything")
    console.print(f"  Optimizer model: {optimizer_model}")
    console.print(f"  Eval model: {eval_model}")
    console.print(f"  Max metric calls: {max_calls}")

    judge = LLMJudge(config)

    def evaluate(candidate: str, example) -> tuple[float, dict]:
        """Evaluate a candidate skill text against one example.

        Returns (score, side_info) where side_info is fed to GEPA's
        reflector as Actionable Side Information (ASI).
        """
        # Constraint check — reject invalid candidates early
        constraint_results = validator.validate_all(candidate, baseline_text=skill["body"])
        failed = [c for c in constraint_results if not c.passed]
        if failed:
            reasons = "; ".join(f"{c.constraint_name}: {c.message}" for c in failed)
            oa.log(f"REJECTED — constraint failure: {reasons}")
            return 0.0, {"rejected": True, "reason": reasons}

        # LLM-judge scoring
        task_input = example.get("task_input", "") if isinstance(example, dict) else getattr(example, "task_input", "")
        expected = example.get("expected_behavior", "") if isinstance(example, dict) else getattr(example, "expected_behavior", "")

        fitness = judge.score(
            task_input=task_input,
            expected_behavior=expected,
            agent_output="",  # TODO: replace with harness output when batch_runner is built
            skill_text=candidate,
            artifact_size=len(candidate),
            max_size=config.max_skill_size,
        )

        # Log feedback as ASI for GEPA's reflector
        oa.log(f"Score: {fitness.composite:.3f} | Correctness: {fitness.correctness:.2f} "
               f"| Procedure: {fitness.procedure_following:.2f} | Conciseness: {fitness.conciseness:.2f}")
        oa.log(f"Feedback: {fitness.feedback}")

        return fitness.composite, {
            "correctness": fitness.correctness,
            "procedure_following": fitness.procedure_following,
            "conciseness": fitness.conciseness,
            "length_penalty": fitness.length_penalty,
            "feedback": fitness.feedback,
        }

    # Build dataset dicts for GEPA
    train_data = [{"task_input": ex.task_input, "expected_behavior": ex.expected_behavior} for ex in dataset.train]
    val_data = [{"task_input": ex.task_input, "expected_behavior": ex.expected_behavior} for ex in dataset.val]

    # Log dir for resume support
    log_dir = config.output_dir / skill_name / "gepa_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # ── 5. Run GEPA optimize_anything ───────────────────────────────────
    console.print(f"\n[bold cyan]Running GEPA optimize_anything...[/bold cyan]\n")
    start_time = time.time()

    gepa_config = GEPAConfig(
        engine=EngineConfig(
            max_metric_calls=max_calls,
            log_dir=str(log_dir),
        ),
    )

    # Resume from previous run if requested
    if resume and (log_dir / "frontier.json").exists():
        console.print(f"  [bold yellow]Resuming from {log_dir}[/bold yellow]")

    result = optimize_anything(
        seed_candidate=skill["body"],
        evaluator=evaluate,
        dataset=train_data if train_data else None,
        valset=val_data if val_data else None,
        objective=f"Optimize this Copilot CLI skill named '{skill['name']}' to produce "
                  f"more correct, well-structured outputs when an AI agent follows these instructions. "
                  f"The skill text is markdown that an autonomous agent reads before executing tasks.",
        background=(
            "Copilot CLI skills are markdown instruction files (SKILL.md) read by an AI coding agent. "
            "The agent has access to tools (shell, file read/write, grep, etc.) and follows the skill "
            "instructions to complete user tasks. Good skills are: specific about steps, clear about "
            "when to use which tool, concise (not verbose), and structured with headers. "
            "Bad skills are: vague, overly long, contradictory, or missing key steps."
        ),
        config=gepa_config,
    )

    elapsed = time.time() - start_time
    console.print(f"\n  Completed in {elapsed:.1f}s")

    # ── 6. Extract and validate evolved skill ───────────────────────────
    evolved_body = result.best_candidate
    evolved_full = reassemble_skill(skill["frontmatter"], evolved_body)

    console.print(f"\n[bold]Validating evolved skill[/bold]")
    results = validator.validate_all(evolved_body, baseline_text=skill["body"])
    all_pass = all(c.passed for c in results)
    for c in results:
        icon = "✓" if c.passed else "✗"
        console.print(f"  {icon} {c.constraint_name}: {c.message}")

    if not all_pass:
        console.print("[red]✗ Constraints failed — not deploying[/red]")
        fail_path = config.output_dir / skill_name / "evolved_FAILED.md"
        fail_path.parent.mkdir(parents=True, exist_ok=True)
        fail_path.write_text(evolved_full)
        console.print(f"  Saved failed variant: {fail_path}")
        return

    # ── 7. Evaluate on holdout ──────────────────────────────────────────
    console.print(f"\n[bold]Holdout evaluation ({len(dataset.holdout)} examples)[/bold]")

    baseline_scores, evolved_scores = [], []
    for ex in dataset.holdout:
        b_score = judge.score(
            task_input=ex.task_input,
            expected_behavior=ex.expected_behavior,
            agent_output="",
            skill_text=skill["body"],
        )
        baseline_scores.append(b_score.composite)

        e_score = judge.score(
            task_input=ex.task_input,
            expected_behavior=ex.expected_behavior,
            agent_output="",
            skill_text=evolved_body,
        )
        evolved_scores.append(e_score.composite)

    avg_base = sum(baseline_scores) / max(1, len(baseline_scores))
    avg_evolved = sum(evolved_scores) / max(1, len(evolved_scores))
    improvement = avg_evolved - avg_base

    # ── 8. Report ───────────────────────────────────────────────────────
    console.print(f"\n  Baseline score:  {avg_base:.3f}")
    console.print(f"  Evolved score:   {avg_evolved:.3f}")
    if improvement > 0:
        console.print(f"  [bold green]Improvement:   {improvement:+.3f} ({improvement/max(0.001, avg_base)*100:+.1f}%)[/bold green]")
    else:
        console.print(f"  [yellow]Change:        {improvement:+.3f}[/yellow]")

    # ── 9. Save output ─────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = config.output_dir / skill_name / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "evolved_skill.md").write_text(evolved_full)
    (out_dir / "baseline_skill.md").write_text(skill["raw"])
    (out_dir / "metrics.json").write_text(json.dumps({
        "skill_name": skill_name,
        "timestamp": timestamp,
        "max_metric_calls": max_calls,
        "optimizer_model": optimizer_model,
        "eval_model": eval_model,
        "baseline_score": avg_base,
        "evolved_score": avg_evolved,
        "improvement": improvement,
        "baseline_size": len(skill["body"]),
        "evolved_size": len(evolved_body),
        "dataset_sizes": {
            "train": len(dataset.train),
            "val": len(dataset.val),
            "holdout": len(dataset.holdout),
        },
        "elapsed_seconds": elapsed,
        "constraints_passed": all_pass,
    }, indent=2))

    console.print(f"\n  Output: {out_dir}/")

    if improvement > 0:
        console.print(f"\n[bold green]✓ Skill improved! Review the diff:[/bold green]")
        console.print(f"  diff {out_dir / 'baseline_skill.md'} {out_dir / 'evolved_skill.md'}")
    else:
        console.print(f"\n[yellow]⚠ No improvement. Try: more metric calls, better eval data, or stronger model.[/yellow]")


def _build_dataset(
    eval_source: str,
    dataset_path: Optional[str],
    skill_name: str,
    skill: dict,
    config: EvolutionConfig,
) -> EvalDataset:
    """Build evaluation dataset from the specified source."""
    if eval_source == "golden" and dataset_path:
        dataset = GoldenDatasetLoader.load(Path(dataset_path), config)
        console.print(f"  Loaded golden: {len(dataset.all_examples)} examples")
    elif eval_source == "sessiondb":
        miner = SessionDBMiner(config)
        dataset = miner.mine(skill_name, skill["raw"])
        if not dataset.all_examples:
            console.print("[yellow]⚠ No session data found, falling back to synthetic[/yellow]")
            builder = SyntheticDatasetBuilder(config)
            dataset = builder.generate(skill["raw"])
        else:
            console.print(f"  Mined {len(dataset.all_examples)} examples from session DB")
    elif eval_source == "synthetic":
        builder = SyntheticDatasetBuilder(config)
        dataset = builder.generate(skill["raw"])
        console.print(f"  Generated {len(dataset.all_examples)} synthetic examples")
    elif dataset_path:
        dataset = EvalDataset.load(Path(dataset_path))
        console.print(f"  Loaded: {len(dataset.all_examples)} examples")
    else:
        console.print("[red]✗ Specify --dataset-path or use --eval-source synthetic[/red]")
        sys.exit(1)
    return dataset


@click.command()
@click.option("--skill", required=True, help="Skill name to evolve")
@click.option("--max-calls", default=100, help="Max GEPA metric evaluations")
@click.option("--eval-source", default="synthetic",
              type=click.Choice(["synthetic", "golden", "sessiondb"]))
@click.option("--dataset-path", default=None, help="Path to existing eval dataset")
@click.option("--optimizer-model", default="openai/gpt-4.1")
@click.option("--eval-model", default="openai/gpt-4.1-mini")
@click.option("--dry-run", is_flag=True, help="Validate setup only")
@click.option("--resume", is_flag=True, help="Resume from previous run's log_dir")
def main(skill, max_calls, eval_source, dataset_path, optimizer_model, eval_model, dry_run, resume):
    """Evolve a Copilot CLI skill using GEPA optimize_anything."""
    evolve(
        skill_name=skill,
        max_calls=max_calls,
        eval_source=eval_source,
        dataset_path=dataset_path,
        optimizer_model=optimizer_model,
        eval_model=eval_model,
        dry_run=dry_run,
        resume=resume,
    )


if __name__ == "__main__":
    main()
