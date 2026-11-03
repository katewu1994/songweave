#!/usr/bin/env bash
# Reproduce the three Python environments and the local Node toolchain from the lock files.
# Run from the repository root. Downloads packages only (PyPI, python-build-standalone, nodejs.org);
# model weights download separately on first `mvm analyze` / `mvm probe` (Hugging Face, Meta CDN).
set -euo pipefail
cd "$(dirname "$0")/.."

UV="${UV:-}"
if [[ -z "$UV" ]]; then
  if command -v uv >/dev/null; then
    UV=uv
  else
    python3 -m venv .tools/bootstrap
    .tools/bootstrap/bin/pip install -q uv
    UV=.tools/bootstrap/bin/uv
  fi
fi

"$UV" python install 3.12

# Main environment: CLI, export, PE-AV (transformers 5).
"$UV" venv --allow-existing --python 3.12 .venv
VIRTUAL_ENV=.venv "$UV" pip install -r requirements/main.lock.txt
VIRTUAL_ENV=.venv "$UV" pip install --no-deps -e .

# MERIT worker: MERT remote code needs transformers 4.x.
"$UV" venv --allow-existing --python 3.12 .venvs/merit
VIRTUAL_ENV=.venvs/merit "$UV" pip install -r requirements/merit.lock.txt

# SONAR worker: fairseq2n 0.8.1 is built against torch 2.9.1.
"$UV" venv --allow-existing --python 3.12 .venvs/sonar
VIRTUAL_ENV=.venvs/sonar "$UV" pip install -r requirements/sonar.lock.txt
# fairseq2n's macOS wheel expects Homebrew libsndfile; use the copy bundled with the soundfile wheel.
cp .venvs/sonar/lib/python3.12/site-packages/_soundfile_data/libsndfile_arm64.dylib .venvs/sonar/lib/libsndfile.1.dylib

# Node (frontend build only).
if ! command -v node >/dev/null && [[ ! -x .tools/node/bin/node ]]; then
  V=v24.22.2
  mkdir -p .tools/dl
  curl -fsSL -o ".tools/dl/node.tgz" "https://nodejs.org/dist/$V/node-$V-darwin-arm64.tar.gz"
  (cd .tools/dl && curl -fsSL "https://nodejs.org/dist/$V/SHASUMS256.txt" | grep "node-$V-darwin-arm64.tar.gz" | sed "s/node-$V-darwin-arm64.tar.gz/node.tgz/" | shasum -a 256 -c)
  tar xzf .tools/dl/node.tgz -C .tools && mv ".tools/node-$V-darwin-arm64" .tools/node && rm -rf .tools/dl
fi
NODE_BIN="$(command -v node >/dev/null && dirname "$(command -v node)" || echo "$PWD/.tools/node/bin")"
(cd web && PATH="$NODE_BIN:$PATH" npm ci --no-fund --no-audit)

echo "Environments ready. Next: .venv/bin/mvm init-manifest data/songs --lyrics-dir data/lyrics"
