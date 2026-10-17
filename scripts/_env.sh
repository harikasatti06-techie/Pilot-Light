# Shared by the demo scripts
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="$ROOT/.venv/bin/python"
set -a; [ -f "$ROOT/.env" ] && source "$ROOT/.env"; set +a
export AWS_REGION="${AWS_REGION:-us-east-1}"
export PYTHONUNBUFFERED=1
