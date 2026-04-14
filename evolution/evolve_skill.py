"""Evolve a Copilot CLI skill using DSPy + GEPA.

Usage:
    python -m evolution.evolve_skill --skill self-learning --iterations 10
    python -m evolution.evolve_skill --skill adr-creator --eval-source sessiondb
    python -m evolution.evolve_skill --skill git-manager --eval-source golden --dataset-path datasets/git-manager/
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

import click

from .config import EvolutionConfig
from .skill_module import SkillModule, find_skill, load_skill, reassemble_skill
from .fitness import skill_fitness_metric, LLMJudge
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
    from rich.table import Table

    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

    class _FallbackConsole:
        def print(self, *args, **kwargs):
            # Strip rich markup
            import re
            text = " ".join(str(a) for a in args)
            text = re.sub(r"\[/?[a-z_ ]+\]", "", text)
            print(text)

    console = _FallbackConsole()


def evolve(
    skill_name: str,
    iterations: int = 10,
    eval_source: str = "synthetic",
    dataset_path: Optional[str] = None,
    optimizer_model: str = "openai/gpt-4.1",
    eval_model: str = "openai/gpt-4.1-mini",
    dry_run: bool = False,
):
    """Main evolution loop — orchestrates the full optimization pipeline."""

    import dspy

    config = EvolutionConfig(
        iterations=iterations,
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

    if dry_run:
        console.print(f"\n[bold green]DRY RUN — setup OK.[/bold green]")
        console.print(f"  Would generate eval dataset (source: {eval_source})")
        console.print(f"  Would run GEPA optimization ({iterations} iterations)")
        return

    # ── 2. Build or load evaluation dataset ─────────────────────────────
    console.print(f"\n[bold]Building eval dataset[/bold] (source: {eval_source})")

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

    # ── 4. Set up DSPy + GEPA ───────────────────────────────────────────
    console.print(f"\n[bold]Configuring optimizer[/bold]")
    console.print(f"  Engine: GEPA ({iterations} iterations)")
    console.print(f"  Optimizer model: {optimizer_model}")
    console.print(f"  Eval model: {eval_model}")

    lm = dspy.LM(eval_model)
    dspy.configure(lm=lm)

    baseline_module = SkillModule(skill["body"])
    trainset = dataset.to_dspy_examples("train")
    valset = dataset.to_dspy_examples("val")

    # ── 5. Run GEPA optimization ────────────────────────────────────────
    console.print(f"\n[bold cyan]Running GEPA optimization...[/bold cyan]\n")
    start_time = time.time()

    try:
        optimizer = dspy.GEPA(
            metric=skill_fitness_metric,
            max_steps=iterations,
        )
        optimized_module = optimizer.compile(
            baseline_module,
            trainset=trainset,
            valset=valset,
        )
    except Exception as e:
        console.print(f"[yellow]GEPA unavailable ({e}), falling back to MIPROv2[/yellow]")
        optimizer = dspy.MIPROv2(
            metric=skill_fitness_metric,
            auto="light",
        )
        optimized_module = optimizer.compile(
            baseline_module,
            trainset=trainset,
        )

    elapsed = time.time() - start_time
    console.print(f"  Completed in {elapsed:.1f}s")

    # ── 6. Extract evolved skill ────────────────────────────────────────
    evolved_body = optimized_module.skill_text
    evolved_full = reassemble_skill(skill["frontmatter"], evolved_body)

    # ── 7. Validate evolved skill ───────────────────────────────────────
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

    # ── 8. Evaluate on holdout ──────────────────────────────────────────
    console.print(f"\n[bold]Holdout evaluation ({len(dataset.holdout)} examples)[/bold]")
    holdout = dataset.to_dspy_examples("holdout")

    baseline_scores, evolved_scores = [], []
    for ex in holdout:
        with dspy.context(lm=lm):
            b_pred = baseline_module(task_input=ex.task_input)
            baseline_scores.append(skill_fitness_metric(ex, b_pred))

            e_pred = optimized_module(task_input=ex.task_input)
            evolved_scores.append(skill_fitness_metric(ex, e_pred))

    avg_base = sum(baseline_scores) / max(1, len(baseline_scores))
    avg_evolved = sum(evolved_scores) / max(1, len(evolved_scores))
    improvement = avg_evolved - avg_base

    # ── 9. Report ───────────────────────────────────────────────────────
    console.print(f"\n  Baseline score:  {avg_base:.3f}")
    console.print(f"  Evolved score:   {avg_evolved:.3f}")
    if improvement > 0:
        console.print(f"  [bold green]Improvement:   {improvement:+.3f} ({improvement/max(0.001, avg_base)*100:+.1f}%)[/bold green]")
    else:
        console.print(f"  [yellow]Change:        {improvement:+.3f}[/yellow]")

    # ── 10. Save output ─────────────────────────────────────────────────
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = config.output_dir / skill_name / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "evolved_skill.md").write_text(evolved_full)
    (out_dir / "baseline_skill.md").write_text(skill["raw"])
    (out_dir / "metrics.json").write_text(json.dumps({
        "skill_name": skill_name,
        "timestamp": timestamp,
        "iterations": iterations,
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
        console.print(f"\n[yellow]⚠ No improvement. Try: more iterations, better eval data, or stronger model.[/yellow]")


@click.command()
@click.option("--skill", required=True, help="Skill name to evolve")
@click.option("--iterations", default=10, help="GEPA iterations")
@click.option("--eval-source", default="synthetic",
              type=click.Choice(["synthetic", "golden", "sessiondb"]))
@click.option("--dataset-path", default=None, help="Path to existing eval dataset")
@click.option("--optimizer-model", default="openai/gpt-4.1")
@click.option("--eval-model", default="openai/gpt-4.1-mini")
@click.option("--dry-run", is_flag=True, help="Validate setup only")
def main(skill, iterations, eval_source, dataset_path, optimizer_model, eval_model, dry_run):
    """Evolve a Copilot CLI skill using DSPy + GEPA."""
    evolve(
        skill_name=skill,
        iterations=iterations,
        eval_source=eval_source,
        dataset_path=dataset_path,
        optimizer_model=optimizer_model,
        eval_model=eval_model,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    main()
