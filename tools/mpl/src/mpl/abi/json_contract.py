from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mpl.api import process_text


ABI_VERSION = "0.1"
# Общая для полки версия внешнего контракта (docs/CONTRACT.md). Меняется только
# при несовместимом изменении JSON/CLI-контракта, вместе с записью в CHANGELOG.
CONTRACT_VERSION = 1


def stamp(result: dict[str, Any]) -> dict[str, Any]:
    """Add the contract markers to a JSON result that leaves the tool."""
    result["abi"] = {"name": "mpl-json", "version": ABI_VERSION}
    result["contract_version"] = CONTRACT_VERSION
    return result


def error_result(code: int, kind: str, message: str) -> dict[str, Any]:
    return stamp({"ok": False, "error": {"code": code, "kind": kind, "message": message}})


def run_contract(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("ABI JSON должен быть объектом с полем source/text или input_path")
    source = _resolve_source(payload)
    render = bool(payload.get("render", payload.get("svg", True)))
    strict = bool(payload.get("strict", False))
    return stamp(process_text(source, render=render, strict=strict))


def run_contract_json(raw_json: str) -> str:
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"ABI JSON не разобран: {exc}") from exc
    result = run_contract(payload)
    return json.dumps(result, ensure_ascii=False, indent=2)


def _resolve_source(payload: dict[str, Any]) -> str:
    if "source" in payload:
        return str(payload["source"])
    if "text" in payload:
        return str(payload["text"])
    if "input_path" in payload:
        return Path(str(payload["input_path"])).read_text(encoding="utf-8")
    raise ValueError("ABI JSON должен содержать source/text или input_path")
