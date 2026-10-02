"""Merge multiple YOLO detection datasets into a normalized staging dataset.

The script is intentionally source-agnostic. It reads each source dataset's YAML
class names, remaps selected labels to the project's three canonical classes and
writes a flat staging set plus a manifest. No Internet access is performed.

Example:
    python dataset_tools/merge_yolo_datasets.py \
        --spec dataset_tools/merge_spec.example.json \
        --output datasets/staging
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import yaml

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def read_names(yaml_path: Path) -> Dict[int, str]:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    names = data.get("names", {})
    if isinstance(names, list):
        return {i: str(v) for i, v in enumerate(names)}
    return {int(k): str(v) for k, v in dict(names).items()}


def find_image_for_label(label_path: Path) -> Path | None:
    parts = list(label_path.parts)
    candidates: List[Path] = []
    if "labels" in parts:
        idx = len(parts) - 1 - parts[::-1].index("labels")
        image_parts = parts.copy()
        image_parts[idx] = "images"
        base = Path(*image_parts).with_suffix("")
        candidates.extend(base.with_suffix(ext) for ext in IMAGE_EXTS)
    base = label_path.with_suffix("")
    candidates.extend(base.with_suffix(ext) for ext in IMAGE_EXTS)
    for p in candidates:
        if p.exists():
            return p
    return None


def label_files(root: Path) -> Iterable[Path]:
    for p in root.rglob("*.txt"):
        if "labels" in p.parts:
            yield p


def infer_group(image_path: Path, source_root: Path, source_name: str) -> str:
    try:
        rel = image_path.relative_to(source_root)
    except ValueError:
        rel = image_path
    parent = rel.parent.as_posix()
    # Sequence/video datasets are commonly stored one sequence per folder. Preserve that
    # parent as a grouping hint so later train/val/test splitting can avoid frame leakage.
    return "{}:{}".format(source_name, parent or image_path.stem)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-negative", action="store_true", help="Keep images whose selected-class label becomes empty")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    target_classes = [str(x) for x in spec["target_classes"]]
    target_id = {name: i for i, name in enumerate(target_classes)}
    out = args.output
    images_out = out / "images" / "all"
    labels_out = out / "labels" / "all"
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)

    manifest_rows = []
    stats = {name: 0 for name in target_classes}
    copied = 0
    skipped = 0

    for source in spec.get("sources", []):
        source_name = str(source["name"])
        root = Path(source["root"]).expanduser().resolve()
        yaml_path = root / source.get("yaml", "data.yaml")
        if not yaml_path.exists():
            raise FileNotFoundError("{}: YAML not found: {}".format(source_name, yaml_path))
        source_names = read_names(yaml_path)
        mapping = {str(k): str(v) for k, v in source.get("class_map", {}).items()}

        for label_path in label_files(root):
            image_path = find_image_for_label(label_path)
            if image_path is None:
                skipped += 1
                continue
            remapped: List[str] = []
            for raw in label_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                fields = raw.strip().split()
                if len(fields) < 5:
                    continue
                try:
                    src_id = int(float(fields[0]))
                except ValueError:
                    continue
                src_name = source_names.get(src_id, str(src_id))
                dst_name = mapping.get(src_name)
                if not dst_name or dst_name not in target_id:
                    continue
                fields[0] = str(target_id[dst_name])
                remapped.append(" ".join(fields[:5]))
                stats[dst_name] += 1

            if not remapped and not args.include_negative:
                continue

            fingerprint = hashlib.sha1(str(image_path).encode("utf-8")).hexdigest()[:10]
            safe_stem = "{}__{}__{}".format(source_name, fingerprint, image_path.stem.replace(" ", "_"))
            dst_image = images_out / (safe_stem + image_path.suffix.lower())
            dst_label = labels_out / (safe_stem + ".txt")
            shutil.copy2(image_path, dst_image)
            dst_label.write_text("\n".join(remapped) + ("\n" if remapped else ""), encoding="utf-8")
            manifest_rows.append({
                "stem": safe_stem,
                "image": dst_image.name,
                "label": dst_label.name,
                "source": source_name,
                "group": infer_group(image_path, root, source_name),
                "original": str(image_path),
                "instances": len(remapped),
            })
            copied += 1

    with (out / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.DictWriter(fp, fieldnames=["stem", "image", "label", "source", "group", "original", "instances"])
        writer.writeheader()
        writer.writerows(manifest_rows)
    (out / "classes.json").write_text(json.dumps(target_classes, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Merged images:", copied)
    print("Unmatched label/image pairs skipped:", skipped)
    print("Instance counts:", json.dumps(stats, ensure_ascii=False))
    print("Staging dataset:", out.resolve())


if __name__ == "__main__":
    main()
