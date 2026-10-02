"""Insert explicitly marked DEMO events/statistics for UI rehearsal.

This script never runs automatically. Use it only for layout rehearsal before real
campus test data is available. Competition metrics must be replaced with real tests.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from config import GlobalConfig
from platform_core import PlatformDatabase


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--confirm-demo-data", action="store_true")
    args = p.parse_args()
    if not args.confirm_demo_data:
        raise SystemExit("Refusing to insert synthetic data. Re-run with --confirm-demo-data.")
    GlobalConfig.ensure_directories()
    db = PlatformDatabase(GlobalConfig.PLATFORM_DIR / "platform.db")
    devices = db.list_devices()
    names = [d["name"] for d in devices] or ["本机摄像头"]
    types = ["禁行区域闯入", "逆行预警", "异常滞留"]
    labels = ["bicycle", "electric_bicycle", "tricycle"]
    for i in range(9):
        t = datetime.now() - timedelta(minutes=13 * i)
        db.add_event({
            "timestamp": t.strftime("%Y-%m-%d %H:%M:%S"),
            "device": names[i % len(names)],
            "event_type": types[i % len(types)],
            "target_label": labels[i % len(labels)],
            "track_id": 1000 + i,
            "confidence": 0.80 + 0.01 * (i % 10),
            "snapshot_path": "",
            "note": "DEMO DATA - 仅用于界面排练，不得作为真实试点指标",
        })
    db.increment_stats(flow_delta=126, frame_delta=3200)
    db.close()
    print("Inserted DEMO data into", GlobalConfig.PLATFORM_DIR / "platform.db")


if __name__ == "__main__":
    main()
