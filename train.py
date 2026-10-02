"""Train the project's multi-class YOLO model."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="yolo26n.pt", help="Base YOLO26 weight/name or local .pt path")
    p.add_argument("--data", default="datasets/non_motor_vehicle/data.yaml")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", default="", help="0 / 0,1 / cpu / mps; empty=auto")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--project", default="runs/non_motor_vehicle")
    p.add_argument("--name", default="yolo26_multiclass")
    args = p.parse_args()

    from ultralytics import YOLO
    model = YOLO(args.model)
    kwargs = dict(
        data=str(Path(args.data)), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
        workers=args.workers, project=args.project, name=args.name, pretrained=True,
        patience=30, close_mosaic=10, cache=False,
    )
    if args.device:
        kwargs["device"] = args.device
    model.train(**kwargs)
    print("Training finished. Copy the best weight from the run directory to models/best.pt before deployment.")


if __name__ == "__main__":
    main()
