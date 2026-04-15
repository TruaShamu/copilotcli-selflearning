"""Copilot CLI batch runner — run real agent sessions for evaluation.

Injects an evolved skill into a temp config dir, runs copilot -p with
--output-format json, and extracts the assistant's output for scoring.

Architecture:
    1. Create temp config dir with the candidate skill
    2. Copy user's existing config (instructions, MCP, etc.) to temp dir
    3. Run: copilot --config-dir <tmp> -p <prompt> --allow-all --no-ask-user -s --output-format json
    4. Parse JSON output → extract assistant messages as agent_output
    5. Return agent_output string for the LLM judge
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class RunResult:
    """Result of a single Copilot CLI run."""
    agent_output: str
    exit_code: int
    elapsed_seconds: float
    tool_calls: list[str] = field(default_factory=list)
    error: Optional[str] = None
    raw_output: str = ""

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.error


@dataclass
class HarnessConfig:
    """Configuration for the batch runner harness."""
    timeout: int = 180
    max_retries: int = 2
    retry_delay: float = 5.0
    copilot_binary: str = "copilot"
    # Copy these from the user's real config dir
    user_config_dir: Path = field(
        default_factory=lambda: Path.home() / ".copilot"
    )


class CopilotCLIHarness:
    """Run Copilot CLI sessions with injected skill text.

    Uses --config-dir to point at a temp directory containing the
    candidate skill, so the user's real skills are never modified.
    """

    def __init__(self, config: Optional[HarnessConfig] = None):
        self.config = config or HarnessConfig()

    def run(
        self,
        prompt: str,
        skill_name: str,
        skill_text: str,
    ) -> RunResult:
        """Run a single Copilot CLI session with the given skill.

        Args:
            prompt: The user prompt to send to Copilot
            skill_name: Name of the skill (used for directory structure)
            skill_text: Full SKILL.md content (frontmatter + body)

        Returns:
            RunResult with extracted agent_output
        """
        for attempt in range(self.config.max_retries + 1):
            result = self._run_once(prompt, skill_name, skill_text)
            if result.success:
                return result
            if attempt < self.config.max_retries:
                time.sleep(self.config.retry_delay * (attempt + 1))
        return result

    def _run_once(
        self,
        prompt: str,
        skill_name: str,
        skill_text: str,
    ) -> RunResult:
        """Execute a single copilot run in a temp config dir."""
        start = time.time()

        with tempfile.TemporaryDirectory(prefix="copilot-eval-") as tmp:
            tmp_path = Path(tmp)

            # Set up temp config dir with the candidate skill
            self._setup_config_dir(tmp_path, skill_name, skill_text)

            # Build command
            cmd = [
                self.config.copilot_binary,
                "--config-dir", str(tmp_path),
                "-p", prompt,
                "--allow-all",
                "--no-ask-user",
                "-s",  # non-interactive
                "--output-format", "json",
            ]

            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.config.timeout,
                    encoding="utf-8",
                    env={**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"},
                )

                elapsed = time.time() - start
                raw = proc.stdout or ""

                if proc.returncode != 0:
                    return RunResult(
                        agent_output="",
                        exit_code=proc.returncode,
                        elapsed_seconds=elapsed,
                        error=proc.stderr[:500] if proc.stderr else f"Exit code {proc.returncode}",
                        raw_output=raw,
                    )

                agent_output, tool_calls = self._parse_json_output(raw)

                return RunResult(
                    agent_output=agent_output,
                    exit_code=proc.returncode,
                    elapsed_seconds=elapsed,
                    tool_calls=tool_calls,
                    raw_output=raw,
                )

            except subprocess.TimeoutExpired:
                return RunResult(
                    agent_output="",
                    exit_code=-1,
                    elapsed_seconds=self.config.timeout,
                    error=f"Timeout after {self.config.timeout}s",
                )
            except FileNotFoundError:
                return RunResult(
                    agent_output="",
                    exit_code=-1,
                    elapsed_seconds=time.time() - start,
                    error=f"Copilot binary not found: {self.config.copilot_binary}",
                )

    def _setup_config_dir(
        self,
        tmp_path: Path,
        skill_name: str,
        skill_text: str,
    ):
        """Create a temp config dir with the candidate skill + user's config."""
        user_cfg = self.config.user_config_dir

        # Copy user's copilot-instructions.md if it exists
        instructions = user_cfg / "copilot-instructions.md"
        if instructions.exists():
            shutil.copy2(instructions, tmp_path / "copilot-instructions.md")

        # Copy MCP config if it exists
        mcp_config = user_cfg / "mcp-config.json"
        if mcp_config.exists():
            shutil.copy2(mcp_config, tmp_path / "mcp-config.json")

        # Copy AGENTS.md if it exists
        agents = user_cfg / "AGENTS.md"
        if agents.exists():
            shutil.copy2(agents, tmp_path / "AGENTS.md")

        # Write the candidate skill
        skill_dir = tmp_path / "skills" / skill_name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")

        # Copy skill resources if they exist (e.g., memory_cli.py)
        user_skill_resources = user_cfg / "skills" / skill_name / "resources"
        if user_skill_resources.is_dir():
            shutil.copytree(
                user_skill_resources,
                skill_dir / "resources",
                dirs_exist_ok=True,
            )

    @staticmethod
    def _parse_json_output(raw: str) -> tuple[str, list[str]]:
        """Parse copilot --output-format json event stream.

        The output is JSONL with event objects like:
          {"type": "assistant.message", "data": {"content": "...", "toolRequests": [...]}}
          {"type": "tool.execution_complete", "data": {"toolName": "..."}}

        Extracts assistant message content and tool call names.
        Returns (agent_output, tool_call_names).
        """
        assistant_parts = []
        tool_calls = []

        for line in raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = obj.get("type", "")
            data = obj.get("data", {})

            if event_type == "assistant.message":
                content = data.get("content", "")
                if content:
                    assistant_parts.append(content)
                # Extract tool call names from toolRequests
                for tr in data.get("toolRequests", []):
                    name = tr.get("toolName", "") or tr.get("name", "")
                    if name:
                        tool_calls.append(name)

            elif event_type == "tool.execution_complete":
                name = data.get("toolName", "")
                if name:
                    tool_calls.append(name)

        agent_output = "\n\n".join(assistant_parts)
        return agent_output, tool_calls
