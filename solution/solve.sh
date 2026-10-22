#!/bin/sh
set -e
mkdir -p /app/output
python3 /solution/solve.py /app/data /app/output/preflights.json
