"""Group-aware train/val/test splitter for the merged staging dataset.

The goal is to reduce video-frame leakage. All images that share the same
``group`` value in manifest.csv are assigned to the same split.
"""
from __future__ import annotations

import argparse
import csv
import random
import shutil
from collections import defaultdict
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--staging", type=Path, default=Path("datasets/staging"))
    p.add_argument("--output", type=Path, default=Path("datasets/non_motor_vehicle"))
    p.add_argument("--train", type=float, default=0.8)
    p.add_argument("--val", type=float, default=0.1)
    p.add_argument("--test", type=float, default=0.1)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--clean", action="store_true")
    args = p.parse_args()
    total = args.train + args.val + args.test
    if abs(total - 1.0) > 1e-6:
        raise SystemExit("train + val + test must equal 1.0")

    manifest = args.staging / "manifest.csv"
    rows = list(csv.DictReader(manifest.open(encoding="utf-8-sig")))
    groups = defaultdict(list)
    for row in rows:
        groups[row.get("group") or row["stem"]].append(row)

    group_items = list(groups.items())
    random.Random(args.seed).shuffle(group_items)
    n = len(group_items)
    train_end = round(n * args.train)
    val_end = train_end + round(n * args.val)
    group_split = {}
    for idx, (group, _) in enumerate(group_items):
        group_split[group] = "train" if idx < train_end else ("val" if idx < val_end else "test")

    if args.clean and args.output.exists():
        for kind in ("images", "labels"):
            for split in ("train", "val", "test"):
                target = args.output / kind / split
                if target.exists():
                    shutil.rmtree(target)

    for kind in ("images", "labels"):
        for split in ("train", "val", "test"):
            (args.output / kind / split).mkdir(parents=True, exist_ok=True)

    counts = defaultdict(int)
    output_manifest = []
    for row in rows:
        split = group_split[row.get("group") or row["stem"]]
        src_image = args.staging / "images" / "all" / row["image"]
        src_label = args.staging / "labels" / "all" / row["label"]
        shutil.copy2(src_image, args.output / "images" / split / src_image.name)
        shutil.copy2(src_label, args.output / "labels" / split / src_label.name)
        counts[split] += 1
        row["split"] = split
        output_manifest.append(row)

    fields = list(output_manifest[0].keys()) if output_manifest else ["stem", "split"]
    with (args.output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_manifest)

    print("Groups:", len(groups))
    print("Images:", dict(counts))
    print("Output:", args.output.resolve())


if __name__ == "__main__":
    main()
