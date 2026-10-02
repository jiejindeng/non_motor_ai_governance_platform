"""Project-wide configuration for the non-motorized vehicle AI governance platform."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Set


class GlobalConfig:
    ROOT = Path(__file__).resolve().parent
    SYS_NAME = "非机动车 AI 智慧治理平台"

    MODEL_PATH = Path(os.getenv("GOVERNANCE_MODEL", ROOT / "models" / "best.pt")).expanduser()
    OUTPUT_DIR = Path(os.getenv("GOVERNANCE_OUTPUT", ROOT / "output")).expanduser()
    PLATFORM_DIR = OUTPUT_DIR / "governance_platform"

    WINDOW_WIDTH = int(os.getenv("GOVERNANCE_WINDOW_WIDTH", "1500"))
    WINDOW_HEIGHT = int(os.getenv("GOVERNANCE_WINDOW_HEIGHT", "920"))
    LEFT_PANEL_WIDTH = int(os.getenv("GOVERNANCE_LEFT_PANEL_WIDTH", "230"))

    VIDEO_FPS = float(os.getenv("GOVERNANCE_VIDEO_FPS", "25"))
    VIDEO_CODEC = os.getenv("GOVERNANCE_VIDEO_CODEC", "mp4v")
    FRAME_DELAY_MS = int(os.getenv("GOVERNANCE_FRAME_DELAY_MS", "8"))

    CONFIDENCE = float(os.getenv("GOVERNANCE_CONF", "0.25"))
    IOU = float(os.getenv("GOVERNANCE_IOU", "0.45"))
    DEVICE = os.getenv("GOVERNANCE_DEVICE", "")  # e.g. 0 / cpu / mps; empty lets Ultralytics choose.

    # Empty means accept all labels produced by the loaded model. Configure when the model
    # contains unrelated classes, e.g. GOVERNANCE_CLASSES=bicycle,electric_bicycle,tricycle.
    _classes = os.getenv("GOVERNANCE_CLASSES", "").strip()
    TARGET_CLASSES: Set[str] = {x.strip().lower() for x in _classes.split(",") if x.strip()}

    @classmethod
    def ensure_directories(cls) -> None:
        for path in (
            cls.OUTPUT_DIR,
            cls.PLATFORM_DIR,
            cls.PLATFORM_DIR / "events",
            cls.ROOT / "models",
            cls.ROOT / "datasets",
        ):
            path.mkdir(parents=True, exist_ok=True)
