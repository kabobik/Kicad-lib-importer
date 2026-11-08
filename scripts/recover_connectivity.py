#!/usr/bin/env python3
"""CLI entry point; run with KiCad's system Python (pcbnew must be importable)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.connectivity_recovery.cli import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
