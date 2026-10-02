"""Unified launcher: python run.py web | gui."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["web", "gui"])
    args = p.parse_args()
    target = ROOT / ("WEB_UI/web.py" if args.mode == "web" else "GUI.py")
    raise SystemExit(subprocess.call([sys.executable, str(target)], cwd=str(ROOT)))


if __name__ == "__main__":
    main()
