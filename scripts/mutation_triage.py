"""Classify baseline mutation findings into per-task remediation manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

TRIAGE_SCHEMA_VERSION = 1

# Task plan IDs for the dependency-ordered waves.
_WAVE: dict[str, str] = {}
for _mod in (
    "utils.config",
    "utils.config.impl",
    "utils.config.contracts",
    "utils.encryption",
    "utils.exceptions",
    "utils.atomic_write",
    "utils.file_permissions",
    "utils.cookies",
    "utils.session_token",
    "utils.retry",
    "utils.version",
    "utils.upstream_contracts",
    "envelope",
    "exit_codes",
    "ndjson",
    "contracts.query",
    "_types",
    "config.models",
    "utils.async_bridge",
    "utils.file_handler",
    "utils.logging.impl",
    "utils.style_manager",
    "runners.models",
    "models.model_config",
):
    _WAVE[f"perplexity_cli.{_mod}"] = "T007"
for _mod in ("api.client", "api.endpoints", "api.models", "api.rest_client", "api.contracts"):
    _WAVE[f"perplexity_cli.{_mod}"] = "T008"
for _mod in ("auth.token_manager", "auth.models", "auth.utils"):
    _WAVE[f"perplexity_cli.{_mod}"] = "T009"
for _mod in (
    "formatting.base",
    "formatting.rich",
    "formatting.markdown",
    "formatting.plain",
    "formatting.json",
    "formatting.registry",
    "formatting.context",
):
    _WAVE[f"perplexity_cli.{_mod}"] = "T010"
_WAVE["perplexity_cli.auth.oauth_handler"] = "T011"
_WAVE["perplexity_cli.runners.config"] = "T012"
for _mod in (
    "threads.cache_manager",
    "threads.date_parser",
    "threads.exporter",
    "threads.models",
    "threads.utils",
):
    _WAVE[f"perplexity_cli.{_mod}"] = "T013"
for _mod in ("threads.scraper", "threads.pagination"):
    _WAVE[f"perplexity_cli.{_mod}"] = "T014"
for _mod in (
    "commands._help_sections",
    "commands._help_refs",
    "commands._examples",
    "commands._ctx",
    "commands._schemas",
    "utils.http_errors.impl",
    "utils.http_errors.contracts",
    "utils.http_headers",
    "utils.rate_limiter",
    "utils.rate_limiter_models",
    "utils.session_factory",
    "attachments.upload_manager",
    "utils.attachment_models",
):
    _WAVE[f"perplexity_cli.{_mod}"] = "T015"
for _mod in ("runners.status", "services.model_service", "services.ports", "error_handler"):
    _WAVE[f"perplexity_cli.{_mod}"] = "T016"
_WAVE["perplexity_cli.runners.auth"] = "T017"
_WAVE["perplexity_cli.runners.export"] = "T018"
_WAVE["perplexity_cli.mcp_server"] = "T019"
for _mod in ("query_runner", "query_streaming", "commands.query_cmd", "query_deps"):
    _WAVE[f"perplexity_cli.{_mod}"] = "T020"
for _mod in (
    "cli",
    "command_runner",
    "completion_commands",
    "help_json",
    "session_log",
    "commands.auth_cmds",
    "commands.config_cmds",
    "commands.doctor_cmds",
    "commands.models_cmds",
    "commands.schema_cmd",
    "commands.skill_cmds",
    "commands.style_cmds",
    "commands.threads_cmds",
    "commands._runner_adapter",
    "runners._utils",
    "runners.skill",
    "ports",
    "commands",
):
    _WAVE[f"perplexity_cli.{_mod}"] = "T021"


def _module(key: str) -> str:
    parts = key.rsplit(".x_", 1)
    _MIN_SPLIT_PARTS = 2
    return parts[0] if len(parts) == _MIN_SPLIT_PARTS else key.rsplit(".", 1)[0]


def build(report_path: Path) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    tasks: dict[str, list[str]] = defaultdict(list)
    cats_by_task: dict[str, Counter[str]] = defaultdict(Counter)
    unassigned: list[str] = []
    for f in payload.get("findings", []):
        mod = _module(f["key"])
        tid = _WAVE.get(mod)
        if tid is None:
            unassigned.append(f["key"])
            tid = "UNASSIGNED"
        tasks[tid].append(f["key"])
        cats_by_task[tid][f["category"]] += 1
    manifests = []
    for tid in sorted(tasks):
        keys = sorted(tasks[tid])
        digest = hashlib.sha256(json.dumps(keys, sort_keys=True).encode()).hexdigest()
        manifests.append(
            {
                "task_id": tid,
                "total": len(keys),
                "categories": dict(cats_by_task[tid]),
                "keys": keys,
                "records_sha256": digest,
            }
        )
    triage_digest = hashlib.sha256(
        json.dumps({m["task_id"]: m["records_sha256"] for m in manifests}, sort_keys=True).encode()
    ).hexdigest()
    return {
        "schema_version": TRIAGE_SCHEMA_VERSION,
        "baseline_total": payload.get("total_mutants", 0),
        "actionable_total": len(payload.get("findings", [])),
        "task_count": len(manifests),
        "unassigned_count": len(unassigned),
        "unassigned_keys": sorted(unassigned),
        "tasks": manifests,
        "triage_sha256": triage_digest,
    }


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    args = parser.parse_args(argv)
    doc = build(args.report_path)
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    logger.info(
        "%d actionable across %d tasks (%d unassigned)",
        doc["actionable_total"],
        doc["task_count"],
        doc["unassigned_count"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
