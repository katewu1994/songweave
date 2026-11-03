"""Split user-provided original lyrics into blocks (stanzas, capped at N lines). Text is never rewritten."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LyricBlock:
    index: int
    text: str
    line_start: int  # 1-based line numbers in the source file
    line_end: int

    def evidence_id(self, track_id: str) -> str:
        return f"lyr:{track_id}:{self.index}"


def read_lyrics(path: Path) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")


def split_blocks(text: str, max_lines: int = 4) -> list[LyricBlock]:
    blocks: list[LyricBlock] = []
    current: list[tuple[int, str]] = []

    def flush() -> None:
        for i in range(0, len(current), max_lines):
            chunk = current[i : i + max_lines]
            blocks.append(
                LyricBlock(index=len(blocks), text="\n".join(t for _, t in chunk), line_start=chunk[0][0], line_end=chunk[-1][0])
            )
        current.clear()

    for n, line in enumerate(text.split("\n"), start=1):
        s = line.strip()
        if not s:
            flush()
            continue
        current.append((n, s))
    flush()
    return blocks


def _is_cjk(c: str) -> bool:
    o = ord(c)
    return 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x9FFF or 0xFF66 <= o <= 0xFF9F or 0xF900 <= o <= 0xFAFF


def block_lang(text: str, default: str) -> str:
    """SONAR source language per block: a block written only in Latin letters is tagged English;
    anything containing kana/kanji keeps the track's language. Text itself is never changed."""
    letters = [c for c in text if c.isalpha()]
    if letters and not any(_is_cjk(c) for c in letters) and all(c.isascii() or "\uFF21" <= c <= "\uFF5A" for c in letters):
        return "eng_Latn"
    return default


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
