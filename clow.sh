#!/bin/bash
# Atalho para executar o Clow
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.venv/bin/activate"
python -m clow "$@"
