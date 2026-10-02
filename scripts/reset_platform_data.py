"""Reset local runtime database and generated governance artifacts."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import GlobalConfig


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--yes", action="store_true", help="Actually delete runtime data")
    args = p.parse_args()
    target = GlobalConfig.PLATFORM_DIR
    if not args.yes:
        raise SystemExit("Would delete: {}\nRe-run with --yes to confirm.".format(target))
    if target.exists():
        shutil.rmtree(target)
    GlobalConfig.ensure_directories()
    print("Reset:", target)


if __name__ == "__main__":
    main()
