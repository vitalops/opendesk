#!/usr/bin/env bash
# Install a durable local runtime; model downloads reuse the Hugging Face cache.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RUNTIME="$HOME/Library/Application Support/OpenDesk/local-venv"
command -v uv >/dev/null || { echo 'Install uv first, then rerun this script.' >&2; exit 1; }
if [[ ! -x "$RUNTIME/bin/python" ]]; then
  uv venv --python 3.11 "$RUNTIME"
fi
uv pip install --python "$RUNTIME/bin/python" -e "$HERE/../python[local,local-vision,memory]"
"$RUNTIME/bin/python" - <<'PY'
from huggingface_hub import snapshot_download
for model in [
    'LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit',
    'mlx-community/LFM2.5-VL-1.6B-4bit',
]:
    print(f'Caching {model}', flush=True)
    snapshot_download(model)
PY
printf 'Local runtime ready: %s\n' "$RUNTIME/bin/python"
