"""Post-generation checks. Passing them proves reference integrity only, not that an interpretation is true."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .schemas import LYRICS_SCHEMA, PAIR_SCHEMA, cited_ids, validate

# Claims the evidence cannot support when no audio was sent (instruments, notation, tempo numbers,
# direct listening). Flagged for human review rather than silently accepted.
_UNSUPPORTED = [
    (r"\d+\s*(bpm|BPM)|每分钟\s*\d+\s*拍", "tempo_number"),
    (r"[A-G][#♯b♭]?\s*(大调|小调|major|minor)|和弦进行|chord progression|\b[IV]{1,3}-[IV]{1,3}\b", "harmony_or_key"),
    (r"吉他|钢琴|鼓组|架子鼓|贝斯|小号|萨克斯|弦乐|管乐|合成器|guitar|piano|drum|bass|trumpet|saxophone|strings|synth", "instrument"),
    (r"我听到|听起来像|我们听到|I hear|sounds like", "direct_listening"),
]


def _view_of(evidence_id: str) -> str | None:
    head = evidence_id.split(":", 2)
    if head[0] in ("rel", "exc", "con") and len(head) > 1:
        return head[1]
    if head[0] in ("lyr", "lpair"):
        return "lyrics_sonar"
    return None


_SMALL_KANA = str.maketrans("ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮゐゑヰヱ", "あいうえおつやゆよわアイウエオツヤユヨワいえイエ")


def _kana_norm(s: str) -> str:
    """Compare quotes despite old/modern kana spelling (つ/っ, ゐ/い) and punctuation."""
    s = unicodedata.normalize("NFKC", s).translate(_SMALL_KANA)
    s = re.sub(r"(.)[ゝヽ]", r"\1\1", s)
    return re.sub(r"[\s、。，,・/「」『』！？!?]", "", s)


def quote_flags(output: dict[str, Any], lyric_texts: dict[str, str]) -> list[dict[str, str]]:
    """Japanese-script text inside 「」 should be a quote of the supplied lyrics."""
    corpus = _kana_norm("".join(lyric_texts.values()))
    texts = [("overview", output.get("overview", "")), ("summary", output.get("summary", ""))]
    for sec in ("observations", "similarities", "differences"):
        texts += [(f"{sec}[{i}]", c["statement"]) for i, c in enumerate(output.get(sec, []))]
    flags = []
    for where, text in texts:
        for q in re.findall(r"「([^」]+)」", text or ""):
            if re.search(r"[ぁ-んァ-ン一-龥]", q) and _kana_norm(q) not in corpus:
                flags.append({"where": where, "flag": "quote_not_in_lyrics", "detail": q})
    return flags


_TIME_RANGE = re.compile(r"\d\d:\d\d\.\d\d-\d\d:\d\d\.\d\d")


def payload_time_index(payload: dict[str, Any]) -> dict[str, set[str]]:
    """Evidence id -> the time-range strings the payload showed for it."""
    out: dict[str, set[str]] = {}
    for d in payload.get("dimensions", []):
        for e in d.get("similar_excerpts", []):
            out[e["evidence_id"]] = {e["A_time"], e["B_time"]}
        for c in d.get("contrast_excerpts", []):
            out[c["evidence_id"]] = {c["time"]}
    return out


def _time_flags(where: str, text: str, ids: list[str], times: dict[str, set[str]]) -> list[dict[str, str]]:
    """A time range quoted in prose must belong to evidence cited by that same item."""
    return [
        {"where": where, "flag": "time_not_in_cited_evidence", "detail": t}
        for t in _TIME_RANGE.findall(text)
        if not any(t in times.get(i, set()) for i in ids)
    ]


def check_output(kind: str, output: Any, allowed: set[str], times: dict[str, set[str]] | None = None) -> dict[str, Any]:
    schema = PAIR_SCHEMA if kind == "pair_explanation" else LYRICS_SCHEMA
    errors = validate(output, schema)
    flags: list[dict[str, str]] = []
    if not errors:
        for where, eid in cited_ids(kind, output):
            if eid not in allowed:
                errors.append(f"{where}: evidence id {eid!r} was not in the payload")
        if kind == "pair_explanation":
            for sec in ("similarities", "differences"):
                for i, c in enumerate(output[sec]):
                    dim = c["dimension"]
                    if dim != "cross_view":
                        wrong = [e for e in c["evidence_ids"] if _view_of(e) not in (None, dim)]
                        if wrong:
                            flags.append({"where": f"{sec}[{i}]", "flag": "dimension_mismatch", "detail": ",".join(wrong)})
                    if times is not None:
                        flags += _time_flags(f"{sec}[{i}]", c["statement"], c["evidence_ids"], times)
            if times is not None:
                for i, g in enumerate(output["listening_guide"]):
                    flags += _time_flags(f"listening_guide[{i}]", g["suggestion"], [g["evidence_id"]], times)
        texts: list[tuple[str, str]] = []
        if kind == "pair_explanation":
            texts.append(("summary", output["summary"]))
            for sec in ("similarities", "differences"):
                texts += [(f"{sec}[{i}]", c["statement"]) for i, c in enumerate(output[sec])]
            texts += [(f"listening_guide[{i}]", g["suggestion"]) for i, g in enumerate(output["listening_guide"])]
        else:
            texts.append(("overview", output["overview"]))
            texts += [(f"observations[{i}]", c["statement"]) for i, c in enumerate(output["observations"])]
        # Lyrics may legitimately mention instruments; for lyric understanding only listening claims are flagged.
        patterns = _UNSUPPORTED if kind == "pair_explanation" else [p for p in _UNSUPPORTED if p[1] == "direct_listening"]
        for where, text in texts:
            for pat, name in patterns:
                m = re.search(pat, text, flags=re.IGNORECASE)
                if m:
                    flags.append({"where": where, "flag": name, "detail": m.group(0)})
    return {"status": "pass" if not errors else "fail", "errors": errors, "lint_flags": flags}
