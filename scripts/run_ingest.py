"""
Production ingest pipeline runner.

Purpose:
    Provide a single interactive entrypoint for governed RAG ingest processing.

Default behavior:
    Let the user choose a PDF from raw/, run extraction, canonical markdown, and
    semantic verification, then ask whether to continue with chunking,
    embedding, and the final manifest.

Policy basis:
    Chunking and embedding require human semantic verification approval.
    This runner records the user's in-run approval in the semantic gate before
    continuing beyond step 03.
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


CONFIG_PATH = Path(__file__).resolve().with_name("ingest_config.py")


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
STEP_BY_KEY = {step.key: step for step in STEPS}

LOG_ROLE_DESCRIPTIONS = {
    "pdf_extract": "PDF text extraction log: parser, page counts, empty pages, input/output hashes.",
    "canonicalize": "Canonical markdown log: normalization counts, semantic tags, table-like line counts.",
    "chunking": "Chunking log: block counts, chunk counts, chunk warnings, table-aware policy metadata.",
    "embedding": "Embedding log: chunk count, vector shape, embedding model, vector artifact hashes.",
    "final_summary": "Final summary: artifact existence, JSONL counts, gate state, final readiness.",
}

SECTION_REVIEW_GUIDANCE = {
    "dense_marker_line": (
        "한 줄에 여러 의미 태그가 겹친 항목입니다. 급여/대상/절차/예외가 같은 규칙 단위로 "
        "붙어 있으면 통과, 서로 다른 규칙이 억지로 합쳐졌으면 보류합니다."
    ),
    "eligibility_exception_overlap": (
        "지원대상과 제외조건이 같은 문장 또는 인접 맥락에 있는 항목입니다. 대상 조건과 "
        "제외 조건이 함께 보존되어야 하는 규칙이면 통과, 둘 중 하나가 잘려 의미가 바뀌면 보류합니다."
    ),
    "exception_without_condition_context": (
        "예외/중지/불가 표현이 조건 설명 없이 보이는 항목입니다. 앞뒤 문맥에서 조건을 확인할 수 "
        "있거나 독립 규칙이면 통과, 예외 사유가 분리되어 해석 불가하면 보류합니다."
    ),
    "possible_footer_noise": (
        "쪽번호, 반복 머리말/꼬리말 같은 문서 장식 후보입니다. 검색 품질을 크게 해치지 않는 "
        "소량 반복이면 통과, 본문보다 잡음이 두드러지거나 chunk 주제를 흐리면 보류합니다."
    ),
    "table_start_sample": (
        "표 시작 후보입니다. 표 제목, 헤더, 행 순서가 유지되고 표 중간이 분리되지 않을 것으로 "
        "보이면 통과, 헤더 누락이나 행 깨짐이 보이면 보류합니다."
    ),
    "untagged_eligibility_like_phrase": (
        "대상자/해당자처럼 자격 조건으로 보이지만 태그가 붙지 않은 항목입니다. 단순 제출서류나 "
        "부가 설명이면 통과, 핵심 선정/지원 조건인데 태그가 빠졌으면 보류합니다."
    ),
    "untagged_section_hint": (
        "보호해야 할 섹션 제목처럼 보이지만 의미 태그가 없는 항목입니다. 실제 제목/목차가 "
        "markdown heading으로 살아 있으면 통과, 본문 문장이 잘못 heading 처리되어 구조가 흔들리면 보류합니다."
    ),
}

DEFAULT_SECTION_REVIEW_GUIDANCE = (
    "report 샘플을 원문 맥락과 비교하세요. 의미 보존, 표/목록 연속성, 검색 잡음 수준이 "
    "수용 가능하면 04 진행, 의미 손실 가능성이 있으면 보류합니다."
)


def load_config() -> Any:
    spec = importlib.util.spec_from_file_location("ingest_config", CONFIG_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load config from {CONFIG_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the production RAG ingest pipeline in governed stages."
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Source PDF path. If omitted, choose from raw/ by number.",
    )
    parser.add_argument(
        "--source-label",
        default=None,
        help="Optional ASCII artifact label. Defaults to a slug/hash from --source.",
    )
    parser.add_argument(
        "--until",
        choices=STEP_KEYS,
        default=None,
        help="Non-interactive last stage. Omit for the guided workflow.",
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
        help="Allow non-interactive chunks, embeddings, or manifest stages.",
    )
    parser.add_argument(
        "--yes-after-verify",
        action="store_true",
        help="After step 03, approve the gate and continue through manifest.",
    )
    parser.add_argument(
        "--skip-final-requirement",
        action="store_true",
        help="Do not pass --require-final-artifacts to manifest snapshot.",
    )
    parser.add_argument(
        "--skip-dblog-sync",
        action="store_true",
        help="Do not sync iMac ingest logs and manifests to dblog after manifest.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    source_path = resolve_source_for_run(config, args)
    source_arg = source_arg_for_env(config, source_path)
    run_id = args.run_id or config.RUN_ID

    interactive = args.until is None
    until = args.until or "verify"
    selected_steps = select_steps(args.from_step, until)

    if needs_approval(selected_steps) and not args.allow_approved_stages:
        print_blocked(until)
        return 2

    env = build_env(run_id, source_arg, args.source_label)
    plan = build_plan(config, selected_steps, run_id, args, source_path, source_arg)

    if args.dry_run:
        print_json(plan)
        return 0

    print_json(plan)
    result = run_steps(config, selected_steps, args, env)
    if result != 0:
        return result

    if interactive and selected_steps[-1].key == "verify":
        outputs = expected_outputs(
            config,
            artifact_prefix_for(config, source_path, args.source_label),
            run_id,
        )
        review_completed = show_verification_summary(
            outputs, require_section_confirmation=not args.yes_after_verify
        )
        if not review_completed:
            print_completion(run_id, "verify")
            print("Next action: 보류된 섹션을 확인한 뒤 다시 실행하세요.")
            print_log_report(config, artifact_prefix_for(config, source_path, args.source_label), run_id)
            return 0

        if args.yes_after_verify or prompt_yes_no(
            "모든 report 섹션 확인이 완료되었습니다. 04 chunking, 05 embedding, 06 manifest까지 계속 진행할까요?",
            False,
        ):
            approve_gate(Path(outputs["semantic_gate"]))
            continuation = (
                STEP_BY_KEY["chunks"],
                STEP_BY_KEY["embeddings"],
                STEP_BY_KEY["manifest"],
            )
            result = run_steps(config, continuation, args, env)
            if result != 0:
                return result
            result = sync_dblog_after_manifest(config, args, env)
            if result != 0:
                return result
            print_completion(run_id, "manifest")
            print_log_report(config, artifact_prefix_for(config, source_path, args.source_label), run_id)
            return 0

        print_completion(run_id, "verify")
        print("Next action: semantic report review is complete only if you approve step 04 later.")
        print_log_report(config, artifact_prefix_for(config, source_path, args.source_label), run_id)
        return 0

    if selected_steps[-1].key == "manifest":
        result = sync_dblog_after_manifest(config, args, env)
        if result != 0:
            return result
    print_completion(run_id, selected_steps[-1].key)
    print_log_report(config, artifact_prefix_for(config, source_path, args.source_label), run_id)
    return 0


def resolve_source_for_run(config: Any, args: argparse.Namespace) -> Path:
    if args.source:
        path = resolve_plan_source(config, args.source)
        if not path.exists():
            raise FileNotFoundError(f"Source PDF not found: {path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Only PDF sources are supported by this runner: {path}")
        return path
    return choose_raw_pdf(config)


def choose_raw_pdf(config: Any) -> Path:
    pdfs = sorted(config.DIRS.raw.glob("*.pdf"), key=lambda path: path.name)
    if not pdfs:
        raise FileNotFoundError(f"No PDF files found in {config.DIRS.raw}")

    print("\nraw/ PDF 목록")
    for index, path in enumerate(pdfs, start=1):
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"{index:2d}. {path.name} ({size_mb:.1f} MB)")

    while True:
        choice = input(f"변환할 PDF 번호를 선택하세요 [1-{len(pdfs)}]: ").strip()
        if not choice:
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(pdfs):
            return pdfs[int(choice) - 1]
        print("유효한 번호를 입력하세요.")


def source_arg_for_env(config: Any, source_path: Path) -> str:
    try:
        return str(source_path.relative_to(config.PROJECT_ROOT))
    except ValueError:
        return str(source_path)


def build_env(run_id: str, source: str, source_label: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["LACP_RAG_RUN_ID"] = run_id
    env["LACP_RAG_SOURCE"] = source
    if source_label:
        env["LACP_RAG_SOURCE_LABEL"] = source_label
    else:
        env.pop("LACP_RAG_SOURCE_LABEL", None)
    return env


def print_blocked(until: str) -> None:
    print_json(
        {
            "step": "run_ingest",
            "status": "blocked",
            "reason": "requested stages after semantic verification require explicit approval flag",
            "requested_until": until,
            "required_flag": "--allow-approved-stages",
            "guided_alternative": "omit --until and answer the in-run prompt after step 03",
        },
        stream=sys.stderr,
    )


def run_steps(
    config: Any,
    steps: tuple[Step, ...],
    args: argparse.Namespace,
    env: dict[str, str],
) -> int:
    for step in steps:
        command = build_step_command(config, step, args)
        print(f"\n==> {step.key}: {step.label}")
        result = subprocess.run(command, cwd=config.SCRIPTS_DIR, env=env)
        if result.returncode != 0:
            print_json(
                {
                    "step": "run_ingest",
                    "status": "failed",
                    "failed_stage": step.key,
                    "returncode": result.returncode,
                },
                stream=sys.stderr,
            )
            return result.returncode
    return 0


def sync_dblog_after_manifest(
    config: Any,
    args: argparse.Namespace,
    env: dict[str, str],
) -> int:
    if args.skip_dblog_sync:
        print("\n==> dblog_sync: skipped by --skip-dblog-sync")
        return 0
    command = [str(config.PYTHON_BIN), "07_sync_logs_to_dblog.py"]
    print("\n==> dblog_sync: Sync iMac logs and manifests to dblog")
    result = subprocess.run(command, cwd=config.SCRIPTS_DIR, env=env)
    if result.returncode != 0:
        print_json(
            {
                "step": "run_ingest",
                "status": "failed",
                "failed_stage": "dblog_sync",
                "returncode": result.returncode,
            },
            stream=sys.stderr,
        )
    return result.returncode


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
    source_path: Path,
    source_arg: str,
) -> dict[str, Any]:
    artifact_prefix = artifact_prefix_for(config, source_path, args.source_label)
    return {
        "step": "run_ingest",
        "dry_run": args.dry_run,
        "step_dry_run": args.step_dry_run,
        "run_id": run_id,
        "python": str(config.PYTHON_BIN),
        "working_directory": str(config.SCRIPTS_DIR),
        "source": source_arg,
        "source_label": args.source_label,
        "target_pdf": str(source_path),
        "selected_stages": [step.key for step in steps],
        "commands": [
            " ".join(build_step_command(config, step, args)) for step in steps
        ],
        "policy": {
            "default_stops_after": "verify",
            "approval_required_after_verify": True,
            "runner_bypasses_gate": False,
        },
        "embedding_output_directory": str(config.DIRS.embeddings),
        "embedding_output_note": "현재 설정은 ~/embeddings가 아니라 프로젝트 내부 embeddings/입니다.",
        "expected_outputs": expected_outputs(config, artifact_prefix, run_id),
    }


def resolve_plan_source(config: Any, source: str) -> Path:
    path = Path(source).expanduser()
    if path.is_absolute():
        return path
    if len(path.parts) > 1:
        return config.PROJECT_ROOT / path
    return config.DIRS.raw / path


def artifact_prefix_for(config: Any, source_path: Path, source_label: str | None) -> str:
    label = config._source_label(source_path, source_label or "")
    return f"rag_{label}"


def expected_outputs(config: Any, artifact_prefix: str, run_id: str) -> dict[str, str]:
    prefix = f"{artifact_prefix}_{run_id}"
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


def show_verification_summary(
    outputs: dict[str, str], require_section_confirmation: bool
) -> bool:
    report_path = Path(outputs["semantic_report"])
    gate_path = Path(outputs["semantic_gate"])
    print("\nStep 03 semantic verification 결과")
    print(f"- report: {report_path}")
    print(f"- gate: {gate_path}")

    if gate_path.exists():
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        print(f"- approved_for_chunking: {gate.get('approved_for_chunking')}")
        print(f"- semantic_comment_count: {gate.get('semantic_comment_count')}")
        print(f"- marker_hit_line_count: {gate.get('marker_hit_line_count')}")
        risk_categories = gate.get("risk_categories", {})
        if risk_categories:
            print("- risk_categories:")
            for name, count in sorted(risk_categories.items()):
                print(f"  - {name}: {count}")

    if report_path.exists():
        print("\n검토할 report 섹션별 점검 내용:")
        sections = parse_suspicious_sections(report_path)
        if sections:
            for section_name, items in sections:
                print(
                    f"\n[{section_name}] (총 점검항목 {len(items)}개) "
                    f"{section_review_guidance(section_name)}"
                )
                for index, item in enumerate(items, start=1):
                    print(f"- {index}/{len(items)} {item}")
                if require_section_confirmation and not prompt_yes_no(
                    f"{section_name} 섹션의 모든 점검항목을 확인했고 통과조건을 만족합니까?",
                    False,
                ):
                    print(f"{section_name} 섹션 확인이 보류되었습니다.")
                    return False
        else:
            print("- Suspicious Samples 섹션을 찾지 못했습니다. report 파일을 직접 확인하세요.")
            if require_section_confirmation:
                return prompt_yes_no("report 파일을 직접 확인했고 04 진행 조건을 만족합니까?", False)
    return True


def parse_suspicious_sections(report_path: Path) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_items: list[str] = []
    current_item: list[str] = []
    in_suspicious = False

    def flush_item() -> None:
        nonlocal current_item
        if current_item:
            current_items.append(" ".join(part.strip() for part in current_item).strip())
        current_item = []

    def flush_section() -> None:
        nonlocal current_name, current_items
        flush_item()
        if current_name is not None:
            sections.append((current_name, current_items))
        current_name = None
        current_items = []

    for line in report_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## ") and line != "## Suspicious Samples":
            if in_suspicious:
                flush_section()
                break
        if line == "## Suspicious Samples":
            in_suspicious = True
            continue
        if not in_suspicious:
            continue
        if line.startswith("### "):
            flush_section()
            current_name = line[4:].strip()
            continue
        if current_name is None:
            continue
        if line.startswith("- "):
            flush_item()
            current_item = [line[2:].strip()]
            continue
        if current_item and line.strip():
            current_item.append(line.strip())

    if in_suspicious:
        flush_section()
    return [(name, items) for name, items in sections if items]


def section_review_guidance(section_name: str) -> str:
    return SECTION_REVIEW_GUIDANCE.get(
        section_name, DEFAULT_SECTION_REVIEW_GUIDANCE
    )


def approve_gate(gate_path: Path) -> None:
    if not gate_path.exists():
        raise FileNotFoundError(f"Semantic gate not found: {gate_path}")
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["approved_for_chunking"] = True
    gate["approval_required_by"] = "human"
    gate["approved_by"] = "run_ingest_interactive_user"
    gate["approval_note"] = "User approved continuation after reviewing step 03 summary."
    gate_path.write_text(
        json.dumps(gate, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nsemantic gate approved: {gate_path}")


def prompt_yes_no(question: str, default: bool) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{question} {suffix}: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("y 또는 n으로 입력하세요.")


def print_completion(run_id: str, completed_until: str) -> None:
    print_json(
        {
            "step": "run_ingest",
            "status": "completed",
            "run_id": run_id,
            "completed_until": completed_until,
            "next_action": next_action(completed_until),
        }
    )


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


def print_log_report(config: Any, artifact_prefix: str, run_id: str) -> None:
    prefix = f"{artifact_prefix}_{run_id}"
    print("\n생성된 log 파일 목록")
    log_specs = [
        ("pdf_extract", config.DIRS.logs / f"{prefix}_pdf_extract.json"),
        ("canonicalize", config.DIRS.logs / f"{prefix}_canonicalize.json"),
        ("chunking", config.DIRS.logs / f"{prefix}_chunking.json"),
        ("embedding", config.DIRS.logs / f"{prefix}_embedding.json"),
        ("final_summary", config.DIRS.logs / f"{prefix}_final_summary.md"),
    ]
    found_any = False
    for key, path in log_specs:
        if path.exists():
            found_any = True
            print(f"- {path}")
            print(f"  role: {LOG_ROLE_DESCRIPTIONS[key]}")
    if not found_any:
        print("- No run log files were created yet.")

    print("\n관련 manifest 파일")
    manifest_specs = [
        ("semantic_report", config.DIRS.manifest / f"{prefix}_semantic_report.md"),
        ("semantic_gate", config.DIRS.manifest / f"{prefix}_semantic_gate.json"),
        ("manifest", config.DIRS.manifest / f"{prefix}_manifest.json"),
        ("pip_freeze", config.DIRS.manifest / f"{prefix}_pip_freeze.txt"),
    ]
    for key, path in manifest_specs:
        if path.exists():
            print(f"- {path}")
            print(f"  role: {manifest_role(key)}")

    print("\nEmbedding output directory check")
    print(f"- configured embeddings dir: {config.DIRS.embeddings}")
    print("- expected by current code: project-local embeddings/ under /Users/morophi/lacp_rag")
    print("- not currently configured: ~/embeddings")


def manifest_role(key: str) -> str:
    roles = {
        "semantic_report": "Human-readable semantic verification report created after step 03.",
        "semantic_gate": "JSON approval gate checked before chunking and embedding.",
        "manifest": "Final reproducibility manifest with hashes, counts, model/runtime metadata.",
        "pip_freeze": "Python environment package snapshot for reproducibility.",
    }
    return roles[key]


def print_json(payload: dict[str, Any], stream: Any = sys.stdout) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2), file=stream)


if __name__ == "__main__":
    raise SystemExit(main())
