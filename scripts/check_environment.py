"""Check runtime dependencies and important project paths."""
from __future__ import annotations

import importlib
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import GlobalConfig


# def check_module(name: str):
#     try:
#         m = importlib.import_module(name)
#         return True, getattr(m, "__version__", "installed")
#     except Exception as exc:
#         return False, str(exc)

import importlib
from importlib.metadata import version, PackageNotFoundError
def check_module(name: str):
    try:
        m = importlib.import_module(name)
        ver = version(name)
        return True, ver
    except PackageNotFoundError:
        return True, "installed"
    except Exception as exc:
        return False, str(exc)

def main():
    print("Python:", sys.version.replace("\n", " "))
    print("OS:", platform.platform())
    for name in ["cv2", "numpy", "yaml", "ultralytics", "flask", "PyQt5"]:
        ok, info = check_module(name)
        print("{:12s} {:4s} {}".format(name, "OK" if ok else "MISS", info))
    print("Project root:", ROOT)
    print("Model:", GlobalConfig.MODEL_PATH, "exists=" + str(GlobalConfig.MODEL_PATH.exists()))
    print("Output:", GlobalConfig.OUTPUT_DIR)
    GlobalConfig.ensure_directories()


if __name__ == "__main__":
    main()
