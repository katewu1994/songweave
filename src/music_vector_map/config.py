"""Configuration loading. The repository root is the directory holding config/songweave.toml."""

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def find_root(start: Path | None = None) -> Path:
    env = os.environ.get("SONGWEAVE_ROOT")
    if env:
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config" / "songweave.toml").is_file():
            return candidate
    raise FileNotFoundError("config/songweave.toml not found; run from the SongWeave repository or set SONGWEAVE_ROOT")


@dataclass
class Config:
    root: Path
    data: dict[str, Any]

    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    @property
    def manifest_path(self) -> Path:
        return self.path(self.data["project"]["manifest"])

    @property
    def artifacts_dir(self) -> Path:
        return self.path(self.data["project"]["artifacts_dir"])

    @property
    def export_dir(self) -> Path:
        return self.path(self.data["project"]["export_dir"])

    @property
    def analysis_dir(self) -> Path:
        return self.artifacts_dir / "analysis"

    @property
    def interpretations_dir(self) -> Path:
        return self.artifacts_dir / "interpretations"

    def section(self, *keys: str) -> dict[str, Any]:
        node: Any = self.data
        for k in keys:
            node = node[k]
        return node


def load_config(path: Path | None = None) -> Config:
    if path is None:
        root = find_root()
        path = root / "config" / "songweave.toml"
    else:
        path = path.resolve()
        root = path.parent.parent
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Config(root=root, data=data)


def stable_hash(obj: Any, n: int = 12) -> str:
    """Hash of a JSON-serialisable object, used to key caches on preprocessing settings."""
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:n]


def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()
