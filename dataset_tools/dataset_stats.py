"""Validate and summarize a YOLO-format detection dataset."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import yaml

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def names_from_yaml(path: Path):
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    names = data.get("names", {})
    if isinstance(names, list):
        return {i: str(v) for i, v in enumerate(names)}
    return {int(k): str(v) for k, v in dict(names).items()}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=Path("datasets/non_motor_vehicle/data.yaml"))
    args = p.parse_args()
    yaml_path = args.data.resolve()
    names = names_from_yaml(yaml_path)
    dataset_root = yaml_path.parent

    report = {"classes": names, "splits": {}, "errors": []}
    for split in ("train", "val", "test"):
        images_dir = dataset_root / "images" / split
        labels_dir = dataset_root / "labels" / split
        images = [p for p in images_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS] if images_dir.exists() else []
        counts = Counter()
        empty = 0
        missing_labels = 0
        bad_lines = 0
        for image in images:
            label = labels_dir / (image.stem + ".txt")
            if not label.exists():
                missing_labels += 1
                continue
            lines = [x.strip() for x in label.read_text(encoding="utf-8", errors="ignore").splitlines() if x.strip()]
            if not lines:
                empty += 1
            for line in lines:
                fields = line.split()
                if len(fields) < 5:
                    bad_lines += 1
                    continue
                try:
                    cid = int(float(fields[0]))
                    coords = [float(x) for x in fields[1:5]]
                    if cid not in names or any(x < 0 or x > 1 for x in coords) or coords[2] <= 0 or coords[3] <= 0:
                        bad_lines += 1
                        continue
                    counts[names[cid]] += 1
                except ValueError:
                    bad_lines += 1
        report["splits"][split] = {
            "images": len(images),
            "instances": sum(counts.values()),
            "class_instances": dict(counts),
            "empty_negative_images": empty,
            "missing_labels": missing_labels,
            "bad_label_lines": bad_lines,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
