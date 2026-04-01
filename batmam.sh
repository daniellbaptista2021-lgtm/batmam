#!/bin/bash
# Atalho para executar o Batmam
DIR="$(cd "$(dirname "$0")" && pwd)"
source "$DIR/.venv/bin/activate"
python -m batmam "$@"
