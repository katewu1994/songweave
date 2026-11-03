"""Output JSON schemas for Meta interpretations plus a small strict validator (no extra dependency)."""

from __future__ import annotations

from typing import Any

DIMENSIONS = ["overall_peav", "melody_merit", "rhythm_merit", "timbre_merit", "lyrics_sonar", "cross_view"]


def _claims(enum_field: str, values: list[str]) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                enum_field: {"type": "string", "enum": values},
                "statement": {"type": "string"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
            "required": [enum_field, "statement", "evidence_ids"],
            "additionalProperties": False,
        },
    }


PAIR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "similarities": _claims("dimension", DIMENSIONS),
        "differences": _claims("dimension", DIMENSIONS),
        "listening_guide": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"evidence_id": {"type": "string"}, "suggestion": {"type": "string"}},
                "required": ["evidence_id", "suggestion"],
                "additionalProperties": False,
            },
        },
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "similarities", "differences", "listening_guide", "uncertainties"],
    "additionalProperties": False,
}

LYRICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "observations": _claims("aspect", ["theme", "emotion", "stance", "narration", "imagery", "ambiguity"]),
        "uncertainties": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overview", "observations", "uncertainties"],
    "additionalProperties": False,
}


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errs: list[str] = []
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object"]
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                errs.append(f"{path}.{k}: missing")
        if schema.get("additionalProperties") is False:
            errs += [f"{path}.{k}: unexpected" for k in value if k not in props]
        for k, sub in props.items():
            if k in value:
                errs += validate(value[k], sub, f"{path}.{k}")
    elif t == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array"]
        if len(value) < schema.get("minItems", 0):
            errs.append(f"{path}: needs at least {schema['minItems']} item(s)")
        for i, v in enumerate(value):
            errs += validate(v, schema.get("items", {}), f"{path}[{i}]")
    elif t == "string":
        if not isinstance(value, str):
            return [f"{path}: expected string"]
        if "enum" in schema and value not in schema["enum"]:
            errs.append(f"{path}: {value!r} not in enum")
    return errs


def cited_ids(kind: str, output: dict[str, Any]) -> list[tuple[str, str]]:
    """(json path, evidence id) for every citation in an output."""
    out: list[tuple[str, str]] = []
    if kind == "pair_explanation":
        for sec in ("similarities", "differences"):
            for i, c in enumerate(output.get(sec, [])):
                out += [(f"{sec}[{i}]", e) for e in c.get("evidence_ids", [])]
        for i, g in enumerate(output.get("listening_guide", [])):
            out.append((f"listening_guide[{i}]", g.get("evidence_id", "")))
    else:
        for i, c in enumerate(output.get("observations", [])):
            out += [(f"observations[{i}]", e) for e in c.get("evidence_ids", [])]
    return out
