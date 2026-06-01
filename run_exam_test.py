"""
Exam test pipeline runner.

Purpose:
    Provide a single entrypoint for staged RAG ingest testing.

Default behavior:
    Run PDF extraction, canonical markdown generation, and semantic
    verification, then stop before chunking.

Policy basis:
    Chunking and embedding require human semantic verification approval.
    This runner does not bypass the semantic gate enforced by the step scripts.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().with_name("00_config.py")


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    script: str
    requires_approval: bool = False
    manifest_requires_final: bool = False


STEPS: tuple[Step, ...] = (
    Step("extract", "PDF text extraction", "01_pdf_extract.py"),
    Step("canonical", "Canonical markdown generation", "02_canonicalize_md.py"),
    Step("verify", "Semantic verification report", "03_semantic_verify_report.py"),
    Step("chunks", "Table-aware chunking", "04_chunk_table_aware.py", True),
    Step("embeddings", "Chunk embedding", "05_embed_chunks.py", True),
    Step(
        "manifest",
        "Reproducibility manifest snapshot",
        "06_manifest_snapshot.py",
        True,
        True,
    ),
)
STEP_KEYS = tuple(step.key for step in STEPS)


def load_config() -> Any:
    spec = importlib.util.spec_from_file_location("exam_test_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config from {CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the exam_test RAG ingest pipeline in governed stages."
    )
    parser.add_argument(
        "--until",
        choices=STEP_KEYS,
        default="verify",
        help="Last stage to run. Defaults to verify so chunking waits for approval.",
    )
    parser.add_argument(
        "--from-step",
        choices=STEP_KEYS,
        default="extract",
        help="First stage to run. Defaults to extract.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional LACP_RAG_RUN_ID override shared by every step.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the planned command sequence without running step scripts.",
    )
    parser.add_argument(
        "--step-dry-run",
        action="store_true",
        help="Run each selected step with its own --dry-run flag.",
    )
    parser.add_argument(
        "--allow-approved-stages",
        action="store_true",
        help="Allow chunks, embeddings, or manifest stages when the gate is approved.",
    )
    parser.add_argument(
        "--skip-final-requirement",
        action="store_true",
        help="Do not pass --require-final-artifacts to manifest snapshot.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    selected_steps = select_steps(args.from_step, args.until)
    run_id = args.run_id or config.RUN_ID

    if needs_approval(selected_steps) and not args.allow_approved_stages:
        print(
            json.dumps(
                {
                    "step": "run_exam_test",
                    "status": "blocked",
                    "reason": "requested stages after semantic verification require explicit approval flag",
                    "requested_until": args.until,
                    "required_flag": "--allow-approved-stages",
                    "safe_default": "--until verify",
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    env = os.environ.copy()
    env["LACP_RAG_RUN_ID"] = run_id
    plan = build_plan(config, selected_steps, run_id, args)

    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps(plan, ensure_ascii=False, indent=2))
    for step in selected_steps:
        command = build_step_command(config, step, args)
        print(f"\n==> {step.key}: {step.label}")
        result = subprocess.run(command, cwd=config.EXAM_TEST_DIR, env=env)
        if result.returncode != 0:
            print(
                json.dumps(
                    {
                        "step": "run_exam_test",
                        "status": "failed",
                        "failed_stage": step.key,
                        "returncode": result.returncode,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return result.returncode

    print(
        json.dumps(
            {
                "step": "run_exam_test",
                "status": "completed",
                "run_id": run_id,
                "completed_until": selected_steps[-1].key,
                "next_action": next_action(selected_steps[-1].key),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def select_steps(from_step: str, until: str) -> tuple[Step, ...]:
    start_index = STEP_KEYS.index(from_step)
    end_index = STEP_KEYS.index(until)
    if start_index > end_index:
        raise ValueError("--from-step must not come after --until")
    return STEPS[start_index : end_index + 1]


def needs_approval(steps: tuple[Step, ...]) -> bool:
    return any(step.requires_approval for step in steps)


def build_step_command(config: Any, step: Step, args: argparse.Namespace) -> list[str]:
    command = [str(config.PYTHON_BIN), step.script]
    if args.step_dry_run:
        command.append("--dry-run")
    if step.manifest_requires_final and not args.skip_final_requirement:
        command.append("--require-final-artifacts")
    return command


def build_plan(
    config: Any,
    steps: tuple[Step, ...],
    run_id: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "step": "run_exam_test",
        "dry_run": args.dry_run,
        "step_dry_run": args.step_dry_run,
        "run_id": run_id,
        "python": str(config.PYTHON_BIN),
        "working_directory": str(config.EXAM_TEST_DIR),
        "target_pdf": str(config.TARGET_PDF),
        "selected_stages": [step.key for step in steps],
        "commands": [
            " ".join(build_step_command(config, step, args)) for step in steps
        ],
        "policy": {
            "default_stops_after": "verify",
            "approval_required_after_verify": True,
            "approved_stages_allowed": args.allow_approved_stages,
            "runner_bypasses_gate": False,
        },
        "expected_outputs": expected_outputs(config, run_id),
    }


def expected_outputs(config: Any, run_id: str) -> dict[str, str]:
    prefix = f"{config.ARTIFACT_PREFIX}_{run_id}"
    return {
        "extracted_text": str(config.DIRS.extracted / f"{prefix}_extracted.txt"),
        "canonical_md": str(config.DIRS.canonical_md / f"{prefix}_canonical.md"),
        "semantic_report": str(config.DIRS.manifest / f"{prefix}_semantic_report.md"),
        "semantic_gate": str(config.DIRS.manifest / f"{prefix}_semantic_gate.json"),
        "chunks_jsonl": str(config.DIRS.chunks / f"{prefix}_chunks.jsonl"),
        "embeddings_npy": str(config.DIRS.embeddings / f"{prefix}_embeddings.npy"),
        "embedding_metadata_jsonl": str(
            config.DIRS.embeddings / f"{prefix}_embedding_metadata.jsonl"
        ),
        "manifest_json": str(config.DIRS.manifest / f"{prefix}_manifest.json"),
        "final_summary": str(config.DIRS.logs / f"{prefix}_final_summary.md"),
    }


def next_action(completed_until: str) -> str:
    if completed_until == "verify":
        return "review semantic report and approve before chunking"
    if completed_until == "chunks":
        return "approve embedding stage"
    if completed_until == "embeddings":
        return "run manifest snapshot"
    if completed_until == "manifest":
        return "review final manifest and logs"
    return "continue with the next staged command"


if __name__ == "__main__":
    raise SystemExit(main())
