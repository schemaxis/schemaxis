#!/usr/bin/env bash
# Copyright (C) 2026 David L F Gaden
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."
exec python3 examples/demos/demo.py "$@"
