"""Command-line image/video/stream inference."""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from detector import BicycleDetector


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("source", help="Image/video path, camera index, RTSP or HTTP stream")
    p.add_argument("--weights", default="models/best.pt")
    p.add_argument("--output", default="output/predict")
    args = p.parse_args()

    detector = BicycleDetector(args.weights)
    source = int(args.source) if args.source.isdigit() else args.source
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    image = cv2.imread(str(source)) if isinstance(source, str) else None
    if image is not None:
        result, detections = detector.predict(image)
        target = out_dir / "detected.jpg"
        cv2.imwrite(str(target), result)
        print("targets=", len(detector.detection_rows(detections)), "saved=", target)
        return

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise SystemExit("Unable to open source: {}".format(args.source))
    writer = None
    target = out_dir / "detected.mp4"
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            result, _ = detector.predict(frame)
            if writer is None:
                h, w = result.shape[:2]
                writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
            writer.write(result)
    finally:
        cap.release()
        if writer:
            writer.release()
    print("saved=", target)


if __name__ == "__main__":
    main()
