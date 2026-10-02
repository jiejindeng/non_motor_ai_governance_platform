"""YOLO detector adapter used by both desktop and Web applications.

The project plan calls the model layer ``YOLO26``. This adapter deliberately only
relies on the public Ultralytics ``YOLO`` interface, so a locally supplied YOLO26
``.pt`` weight can be loaded without coupling the rest of the platform to one
specific model implementation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import cv2
import numpy as np

from config import GlobalConfig


_LABEL_ALIASES = {
    "bike": "bicycle",
    "cycle": "bicycle",
    "e-bike": "electric_bicycle",
    "ebike": "electric_bicycle",
    "electric bike": "electric_bicycle",
    "electric-bike": "electric_bicycle",
    "electricbicycle": "electric_bicycle",
    "three-wheeler": "tricycle",
    "three wheeler": "tricycle",
}


class BicycleDetector:
    """Small compatibility wrapper around an Ultralytics YOLO detector.

    Historical code in this project imports ``BicycleDetector``. The class name is
    kept for compatibility even though the platform can now consume multi-class
    non-motorized-vehicle models.
    """

    def __init__(self, model_path: Optional[str | Path] = None):
        GlobalConfig.ensure_directories()
        self.model_path = Path(model_path or GlobalConfig.MODEL_PATH).expanduser()
        self.model = None
        self.last_error = ""
        if self.model_path.exists():
            try:
                self._load(self.model_path)
            except Exception as exc:  # Keep UI bootable so a user can select another model.
                self.last_error = str(exc)

    def _load(self, path: Path) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise RuntimeError(
                "未安装 ultralytics。请先执行：pip install -r requirements.txt"
            ) from exc
        self.model = YOLO(str(path))
        self.model_path = Path(path)
        self.last_error = ""

    def set_model(self, path: str | Path) -> None:
        path = Path(path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError("模型文件不存在：{}".format(path))
        if path.suffix.lower() != ".pt":
            raise ValueError("当前项目只加载 .pt 权重文件。")
        self._load(path)

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def _ensure_loaded(self) -> None:
        if self.model is None:
            reason = "；上次加载错误：{}".format(self.last_error) if self.last_error else ""
            raise RuntimeError(
                "尚未加载检测模型。请把训练后的 best.pt 放到 models/best.pt，"
                "或在界面中选择模型{}。".format(reason)
            )

    @staticmethod
    def _standard_label(label: str) -> str:
        key = str(label).strip().lower()
        return _LABEL_ALIASES.get(key, key.replace(" ", "_"))

    def _allowed(self, label: str) -> bool:
        configured = GlobalConfig.TARGET_CLASSES
        if not configured:
            return True
        return label.lower() in configured

    def predict(self, frame: np.ndarray):
        """Return ``(annotated_frame, raw_result)`` for one BGR OpenCV frame."""
        self._ensure_loaded()
        if frame is None or not isinstance(frame, np.ndarray) or frame.ndim < 2:
            raise ValueError("输入画面无效。")

        kwargs: Dict[str, Any] = {
            "source": frame,
            "conf": GlobalConfig.CONFIDENCE,
            "iou": GlobalConfig.IOU,
            "verbose": False,
        }
        if GlobalConfig.DEVICE:
            kwargs["device"] = GlobalConfig.DEVICE
        results = self.model.predict(**kwargs)
        if not results:
            return frame.copy(), []
        result = results[0]

        # If no label filter is configured, Ultralytics' own plot is fastest.
        if not GlobalConfig.TARGET_CLASSES:
            try:
                return result.plot(), result
            except Exception:
                return self._draw_rows(frame, self.detection_rows(result)), result

        rows = self.detection_rows(result)
        return self._draw_rows(frame, rows), rows

    @staticmethod
    def _draw_rows(frame: np.ndarray, rows: Iterable[Dict[str, Any]]) -> np.ndarray:
        out = frame.copy()
        palette = [(39, 99, 236), (16, 185, 129), (168, 85, 247), (249, 115, 22)]
        for idx, row in enumerate(rows):
            x1, y1, x2, y2 = [int(row[k]) for k in ("x1", "y1", "x2", "y2")]
            color = palette[idx % len(palette)]
            cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
            text = "{} {:.0%}".format(row.get("label", "target"), float(row.get("confidence", 0)))
            cv2.putText(out, text, (x1, max(20, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, color, 2, cv2.LINE_AA)
        return out

    def detection_rows(self, detections: Any) -> List[Dict[str, Any]]:
        """Normalize raw model output to ``label/confidence/x1/y1/x2/y2`` dicts."""
        if detections is None:
            return []
        if isinstance(detections, list) and (not detections or isinstance(detections[0], dict)):
            return [dict(x) for x in detections]

        result = detections
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return []
        names = getattr(result, "names", None)
        if names is None and self.model is not None:
            names = getattr(self.model, "names", {})
        names = names or {}

        rows: List[Dict[str, Any]] = []
        try:
            count = len(boxes)
        except Exception:
            count = 0
        for i in range(count):
            try:
                xyxy = boxes.xyxy[i].detach().cpu().tolist() if hasattr(boxes.xyxy[i], "detach") else boxes.xyxy[i].tolist()
                conf_obj = boxes.conf[i]
                cls_obj = boxes.cls[i]
                conf = float(conf_obj.detach().cpu().item() if hasattr(conf_obj, "detach") else conf_obj)
                cls_id = int(cls_obj.detach().cpu().item() if hasattr(cls_obj, "detach") else cls_obj)
                if isinstance(names, dict):
                    raw_label = names.get(cls_id, str(cls_id))
                else:
                    raw_label = names[cls_id] if 0 <= cls_id < len(names) else str(cls_id)
                label = self._standard_label(raw_label)
                if not self._allowed(label):
                    continue
                rows.append({
                    "label": label,
                    "confidence": conf,
                    "x1": int(round(xyxy[0])),
                    "y1": int(round(xyxy[1])),
                    "x2": int(round(xyxy[2])),
                    "y2": int(round(xyxy[3])),
                    "class_id": cls_id,
                })
            except Exception:
                continue
        return rows

    def model_info(self) -> Dict[str, Any]:
        names = getattr(self.model, "names", {}) if self.model is not None else {}
        return {
            "loaded": self.loaded,
            "path": str(self.model_path),
            "classes": names,
            "confidence": GlobalConfig.CONFIDENCE,
            "iou": GlobalConfig.IOU,
            "device": GlobalConfig.DEVICE or "auto",
            "last_error": self.last_error,
        }
