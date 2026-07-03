from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mpl.api import process_text


ABI_VERSION = "0.1"


def run_contract(payload: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_source(payload)
    render = bool(payload.get("render", payload.get("svg", True)))
    strict = bool(payload.get("strict", False))
    result = process_text(source, render=render, strict=strict)
    result["abi"] = {"name": "mpl-json", "version": ABI_VERSION}
    return result


def run_contract_json(raw_json: str) -> str:
    payload = json.loads(raw_json)
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
