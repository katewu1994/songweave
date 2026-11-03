"""Load versioned system prompts from prompts/*.md (text between the PROMPT markers)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from ..config import Config

FILES = {"pair_explanation": "PAIR_EXPLANATION.md", "lyric_understanding": "LYRIC_UNDERSTANDING.md"}
LANG_NAMES = {"zh-Hans": "简体中文", "en": "English", "ja": "日本語"}


class MissingPromptError(ValueError):
    """Generation resources are intentionally absent from a source-only checkout."""


def has_prompt(cfg: Config, kind: str) -> bool:
    return (cfg.root / "prompts" / FILES[kind]).is_file()


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str
    sha256: str


def load_prompt(cfg: Config, kind: str, output_language: str) -> Prompt:
    path = cfg.root / "prompts" / FILES[kind]
    try:
        doc = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MissingPromptError(
            f"Generation unavailable: local prompt {path.name} is not included in this checkout"
        ) from exc
    m = re.search(r"<!-- PROMPT START -->\n(.*?)<!-- PROMPT END -->", doc, flags=re.S)
    v = re.search(r"Prompt version:\s*`([^`]+)`", doc)
    if not m or not v:
        raise ValueError(f"{path} lacks PROMPT markers or a version line")
    text = m.group(1).strip().replace("{output_language}", LANG_NAMES.get(output_language, output_language))
    return Prompt(name=FILES[kind], version=v.group(1), text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
