"""Validate a trained non-motorized-vehicle YOLO model."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="models/best.pt")
    p.add_argument("--data", default="datasets/non_motor_vehicle/data.yaml")
    p.add_argument("--split", default="test", choices=["train", "val", "test"])
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--device", default="")
    args = p.parse_args()

    from ultralytics import YOLO
    model = YOLO(str(Path(args.weights)))
    kwargs = dict(data=args.data, split=args.split, imgsz=args.imgsz, plots=True)
    if args.device:
        kwargs["device"] = args.device
    metrics = model.val(**kwargs)
    print(metrics)


if __name__ == "__main__":
    main()
