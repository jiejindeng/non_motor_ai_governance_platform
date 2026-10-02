"""Core services for the non-motorized vehicle AI governance platform.

This module contains the business layer described in the project plan:
- detector output normalization
- lightweight cross-frame tracking
- configurable governance rules (forbidden-zone, wrong-way, dwell)
- SQLite device/event/statistics persistence
- CSV event export

It deliberately stays independent from Flask and PyQt5 so both application
frontends can reuse the same logic.
"""
from __future__ import annotations

import csv
import math
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import cv2


@dataclass
class GovernanceRules:
    forbidden_enabled: bool = False
    forbidden_x: float = 0.65
    forbidden_y: float = 0.10
    forbidden_w: float = 0.30
    forbidden_h: float = 0.75
    wrong_way_enabled: bool = False
    expected_direction: str = "ltr"  # ltr / rtl / ttb / btt
    dwell_enabled: bool = False
    dwell_seconds: float = 10.0
    event_cooldown: float = 8.0
    min_motion_px: float = 35.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GovernanceRules":
        obj = cls()
        for key, value in (data or {}).items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        return obj


class PlatformDatabase:
    """Thread-safe local SQLite store for devices, events and daily flow statistics."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    location TEXT DEFAULT '',
                    status TEXT DEFAULT '已配置',
                    created_at TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    device TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    target_label TEXT NOT NULL,
                    track_id INTEGER,
                    confidence REAL,
                    snapshot_path TEXT DEFAULT '',
                    note TEXT DEFAULT ''
                )
                """
            )
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_stats (
                    day TEXT PRIMARY KEY,
                    flow_count INTEGER DEFAULT 0,
                    frame_count INTEGER DEFAULT 0
                )
                """
            )
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_device ON events(device)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)")
        if not self.list_devices():
            self.add_device("本机摄像头", "0", "本机/演示")

    # ------------------------------ devices ------------------------------
    def add_device(self, name: str, source: str, location: str = "") -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO devices(name, source, location, status, created_at) VALUES(?,?,?,?,?)",
                (name.strip(), source.strip(), location.strip(), "已配置", now),
            )
        return int(cur.lastrowid)

    def update_device(self, device_id: int, name: str, source: str, location: str) -> None:
        with self._lock, self.conn:
            self.conn.execute(
                "UPDATE devices SET name=?, source=?, location=? WHERE id=?",
                (name.strip(), source.strip(), location.strip(), int(device_id)),
            )

    def delete_device(self, device_id: int) -> None:
        with self._lock, self.conn:
            self.conn.execute("DELETE FROM devices WHERE id=?", (int(device_id),))

    def set_device_status(self, device_id: int, status: str) -> None:
        with self._lock, self.conn:
            self.conn.execute("UPDATE devices SET status=? WHERE id=?", (status, int(device_id)))

    def list_devices(self) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute("SELECT * FROM devices ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    def get_device(self, device_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM devices WHERE id=?", (int(device_id),)).fetchone()
        return dict(row) if row else None

    # ------------------------------- events -------------------------------
    def add_event(self, event: Dict[str, Any]) -> int:
        with self._lock, self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO events(timestamp, device, event_type, target_label, track_id,
                                   confidence, snapshot_path, note)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    event.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    event.get("device", "默认设备"),
                    event.get("event_type", "异常事件"),
                    event.get("target_label", "非机动车"),
                    event.get("track_id"),
                    float(event.get("confidence", 0.0) or 0.0),
                    event.get("snapshot_path", ""),
                    event.get("note", ""),
                ),
            )
        return int(cur.lastrowid)

    def list_events(self, limit: int = 300, query: str = "") -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 100000))
        q = str(query or "").strip()
        with self._lock:
            if q:
                like = "%{}%".format(q)
                rows = self.conn.execute(
                    """SELECT * FROM events
                       WHERE device LIKE ? OR event_type LIKE ? OR target_label LIKE ? OR note LIKE ?
                       ORDER BY id DESC LIMIT ?""",
                    (like, like, like, like, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def get_event(self, event_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM events WHERE id=?", (int(event_id),)).fetchone()
        return dict(row) if row else None

    # ------------------------------- stats -------------------------------
    def increment_stats(self, flow_delta: int = 0, frame_delta: int = 0) -> None:
        day = datetime.now().strftime("%Y-%m-%d")
        with self._lock, self.conn:
            self.conn.execute(
                """
                INSERT INTO daily_stats(day, flow_count, frame_count) VALUES(?,?,?)
                ON CONFLICT(day) DO UPDATE SET
                    flow_count = flow_count + excluded.flow_count,
                    frame_count = frame_count + excluded.frame_count
                """,
                (day, int(flow_delta), int(frame_delta)),
            )

    def dashboard_metrics(self) -> Dict[str, int]:
        day = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            stats = self.conn.execute(
                "SELECT flow_count, frame_count FROM daily_stats WHERE day=?", (day,)
            ).fetchone()
            event_count = self.conn.execute(
                "SELECT COUNT(*) AS c FROM events WHERE substr(timestamp,1,10)=?", (day,)
            ).fetchone()["c"]
            online = self.conn.execute(
                "SELECT COUNT(*) AS c FROM devices WHERE status='在线'"
            ).fetchone()["c"]
        return {
            "flow_count": int(stats["flow_count"]) if stats else 0,
            "frame_count": int(stats["frame_count"]) if stats else 0,
            "event_count": int(event_count),
            "online_devices": int(online),
        }

    def weekly_stats(self, days: int = 7) -> List[Dict[str, int | str]]:
        result: List[Dict[str, int | str]] = []
        for offset in range(days - 1, -1, -1):
            day = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
            with self._lock:
                row = self.conn.execute(
                    "SELECT flow_count, frame_count FROM daily_stats WHERE day=?", (day,)
                ).fetchone()
                ev = self.conn.execute(
                    "SELECT COUNT(*) AS c FROM events WHERE substr(timestamp,1,10)=?", (day,)
                ).fetchone()
            result.append({
                "day": day,
                "label": day[5:],
                "flow": int(row["flow_count"]) if row else 0,
                "frames": int(row["frame_count"]) if row else 0,
                "events": int(ev["c"]) if ev else 0,
            })
        return result

    def export_events_csv(self, path: Path) -> None:
        events = self.list_events(limit=100000)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as fp:
            writer = csv.writer(fp)
            writer.writerow(["时间", "设备", "事件类型", "目标", "轨迹ID", "置信度", "截图", "备注"])
            for e in reversed(events):
                writer.writerow([
                    e["timestamp"], e["device"], e["event_type"], e["target_label"],
                    e["track_id"], e["confidence"], e["snapshot_path"], e["note"],
                ])

    def close(self) -> None:
        try:
            with self._lock:
                self.conn.close()
        except Exception:
            pass


def normalize_detections(detector: Any, detections: Any) -> List[Dict[str, Any]]:
    """Normalize detector results to label/confidence/x1/y1/x2/y2 dictionaries."""
    rows: Any = detections
    try:
        if hasattr(detector, "detection_rows"):
            rows = detector.detection_rows(detections)
    except Exception:
        rows = detections

    normalized: List[Dict[str, Any]] = []
    if rows is None:
        return normalized

    # Ultralytics result compatibility when no detector adapter is available.
    if hasattr(rows, "boxes"):
        try:
            names = getattr(rows, "names", {})
            boxes = rows.boxes
            for i in range(len(boxes)):
                xyxy = boxes.xyxy[i].tolist()
                conf = float(boxes.conf[i])
                cls_id = int(boxes.cls[i])
                normalized.append({
                    "label": names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(cls_id),
                    "confidence": conf,
                    "x1": int(xyxy[0]), "y1": int(xyxy[1]),
                    "x2": int(xyxy[2]), "y2": int(xyxy[3]),
                })
            return normalized
        except Exception:
            pass

    try:
        iterable: Iterable[Any] = rows
    except TypeError:
        return normalized

    for row in iterable:
        if isinstance(row, dict):
            getter = row.get
        else:
            getter = lambda key, default=None, obj=row: getattr(obj, key, default)
        label = getter("label", getter("class_name", getter("name", "非机动车")))
        confidence = getter("confidence", getter("conf", 0.0))
        x1 = getter("x1", None)
        y1 = getter("y1", None)
        x2 = getter("x2", None)
        y2 = getter("y2", None)
        bbox = getter("bbox", None)
        if None in (x1, y1, x2, y2) and bbox is not None and len(bbox) >= 4:
            x1, y1, x2, y2 = bbox[:4]
        try:
            normalized.append({
                "label": str(label),
                "confidence": float(confidence or 0.0),
                "x1": int(float(x1)), "y1": int(float(y1)),
                "x2": int(float(x2)), "y2": int(float(y2)),
            })
        except Exception:
            continue
    return normalized


def _center(row: Dict[str, Any]) -> Tuple[float, float]:
    return ((row["x1"] + row["x2"]) / 2.0, (row["y1"] + row["y2"]) / 2.0)


class CentroidTracker:
    """Dependency-free tracker used by the V1/V2 prototype.

    It is intentionally lightweight for local demonstration. The project roadmap
    can replace it with ByteTrack/BoT-SORT without changing the Web/GUI business
    layer because the RuleEngine only consumes normalized track dictionaries.
    """

    def __init__(self, max_distance: float = 120.0, max_missed: int = 18):
        self.max_distance = float(max_distance)
        self.max_missed = int(max_missed)
        self.next_id = 1
        self.tracks: Dict[int, Dict[str, Any]] = {}

    def reset(self) -> None:
        self.next_id = 1
        self.tracks.clear()

    def update(self, detections: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
        now = time.time()
        for track in self.tracks.values():
            track["missed"] += 1

        unmatched_track_ids = set(self.tracks.keys())
        assigned_detection = set()
        candidates: List[Tuple[float, int, int]] = []
        for tid, track in self.tracks.items():
            tx, ty = track["center"]
            for idx, det in enumerate(detections):
                # Avoid linking visibly different classes once multi-class weights are used.
                if track.get("label") and det.get("label") and track["label"] != det["label"]:
                    continue
                cx, cy = _center(det)
                candidates.append((math.hypot(cx - tx, cy - ty), tid, idx))
        candidates.sort(key=lambda item: item[0])

        for dist, tid, idx in candidates:
            if dist > self.max_distance or tid not in unmatched_track_ids or idx in assigned_detection:
                continue
            det = detections[idx]
            cx, cy = _center(det)
            track = self.tracks[tid]
            old_cx, old_cy = track["center"]
            track["bbox"] = (det["x1"], det["y1"], det["x2"], det["y2"])
            track["center"] = (cx, cy)
            track["history"].append((cx, cy, now))
            track["history"] = track["history"][-45:]
            track["label"] = det["label"]
            track["confidence"] = det["confidence"]
            track["last_seen"] = now
            track["missed"] = 0
            track["age_frames"] += 1
            track["distance_px"] += math.hypot(cx - old_cx, cy - old_cy)
            unmatched_track_ids.remove(tid)
            assigned_detection.add(idx)

        new_count = 0
        for idx, det in enumerate(detections):
            if idx in assigned_detection:
                continue
            cx, cy = _center(det)
            tid = self.next_id
            self.next_id += 1
            self.tracks[tid] = {
                "id": tid,
                "bbox": (det["x1"], det["y1"], det["x2"], det["y2"]),
                "center": (cx, cy),
                "history": [(cx, cy, now)],
                "label": det["label"],
                "confidence": det["confidence"],
                "first_seen": now,
                "last_seen": now,
                "missed": 0,
                "age_frames": 1,
                "distance_px": 0.0,
                "zone_entered": None,
                "meta": {
                    "inside_zone": False,
                    "dwell_fired": False,
                    "wrong_way_fired": False,
                },
            }
            new_count += 1

        for tid in list(self.tracks.keys()):
            if self.tracks[tid]["missed"] > self.max_missed:
                del self.tracks[tid]

        visible = [track for track in self.tracks.values() if track["missed"] == 0]
        return visible, new_count


class RuleEngine:
    def __init__(self, rules: Optional[GovernanceRules] = None):
        self.rules = rules or GovernanceRules()
        self.last_event_at: Dict[Tuple[int, str], float] = {}

    def reset(self) -> None:
        self.last_event_at.clear()

    def _cooldown_ok(self, track_id: int, event_type: str, now: float) -> bool:
        key = (track_id, event_type)
        last = self.last_event_at.get(key, 0.0)
        if now - last < float(self.rules.event_cooldown):
            return False
        self.last_event_at[key] = now
        return True

    def _zone_rect(self, frame_shape) -> Tuple[int, int, int, int]:
        h, w = frame_shape[:2]
        x1 = int(w * max(0.0, min(1.0, self.rules.forbidden_x)))
        y1 = int(h * max(0.0, min(1.0, self.rules.forbidden_y)))
        x2 = int(w * max(0.0, min(1.0, self.rules.forbidden_x + self.rules.forbidden_w)))
        y2 = int(h * max(0.0, min(1.0, self.rules.forbidden_y + self.rules.forbidden_h)))
        return max(0, x1), max(0, y1), min(w - 1, x2), min(h - 1, y2)

    def process(self, tracks: List[Dict[str, Any]], frame_shape, device_name: str) -> List[Dict[str, Any]]:
        now = time.time()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        events: List[Dict[str, Any]] = []
        x1, y1, x2, y2 = self._zone_rect(frame_shape)

        for track in tracks:
            tid = int(track["id"])
            cx, cy = track["center"]
            inside = x1 <= cx <= x2 and y1 <= cy <= y2
            meta = track.setdefault("meta", {})
            was_inside = bool(meta.get("inside_zone", False))

            # Forbidden-area alert fires on an entry edge rather than every N seconds while parked.
            if self.rules.forbidden_enabled and inside and not was_inside:
                if self._cooldown_ok(tid, "禁行区域闯入", now):
                    events.append(self._event(stamp, device_name, "禁行区域闯入", track, "目标进入设定禁行区域"))

            # Dwell timer starts on zone entry and resets on exit.
            if self.rules.dwell_enabled:
                if inside:
                    if track.get("zone_entered") is None:
                        track["zone_entered"] = now
                    elif (
                        not meta.get("dwell_fired", False)
                        and now - float(track["zone_entered"]) >= float(self.rules.dwell_seconds)
                        and self._cooldown_ok(tid, "异常滞留", now)
                    ):
                        events.append(self._event(stamp, device_name, "异常滞留", track, "目标在治理区域内持续停留"))
                        meta["dwell_fired"] = True
                else:
                    track["zone_entered"] = None
                    meta["dwell_fired"] = False

            # Wrong-way alert uses recent net displacement and is emitted once per stable track.
            history = track.get("history", [])
            if self.rules.wrong_way_enabled and not meta.get("wrong_way_fired", False) and len(history) >= 4:
                hx, hy, _ = history[0]
                dx, dy = cx - hx, cy - hy
                if math.hypot(dx, dy) >= float(self.rules.min_motion_px):
                    direction = self.rules.expected_direction
                    wrong = (
                        (direction == "ltr" and dx < -self.rules.min_motion_px)
                        or (direction == "rtl" and dx > self.rules.min_motion_px)
                        or (direction == "ttb" and dy < -self.rules.min_motion_px)
                        or (direction == "btt" and dy > self.rules.min_motion_px)
                    )
                    if wrong and self._cooldown_ok(tid, "逆行预警", now):
                        events.append(self._event(stamp, device_name, "逆行预警", track, "运动方向与设定通行方向相反"))
                        meta["wrong_way_fired"] = True

            meta["inside_zone"] = inside
        return events

    @staticmethod
    def _event(stamp: str, device: str, event_type: str, track: Dict[str, Any], note: str) -> Dict[str, Any]:
        return {
            "timestamp": stamp,
            "device": device,
            "event_type": event_type,
            "target_label": track.get("label", "非机动车"),
            "track_id": int(track.get("id", 0)),
            "confidence": float(track.get("confidence", 0.0)),
            "snapshot_path": "",
            "note": note,
        }

    def draw_overlays(self, frame, tracks: List[Dict[str, Any]]):
        """Overlay governance zone, track IDs and recent motion paths."""
        output = frame
        if self.rules.forbidden_enabled or self.rules.dwell_enabled:
            x1, y1, x2, y2 = self._zone_rect(output.shape)
            cv2.rectangle(output, (x1, y1), (x2, y2), (0, 80, 255), 2)
            cv2.putText(output, "GOVERNANCE ZONE", (x1 + 8, max(24, y1 + 24)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 80, 255), 2, cv2.LINE_AA)
        for track in tracks:
            x1, y1, x2, y2 = track["bbox"]
            cv2.putText(output, "ID {}".format(track["id"]), (int(x1), max(18, int(y1) - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 210, 255), 2, cv2.LINE_AA)
            history = track.get("history", [])
            if len(history) >= 2:
                pts = [(int(x), int(y)) for x, y, _ in history[-15:]]
                for a, b in zip(pts[:-1], pts[1:]):
                    cv2.line(output, a, b, (0, 210, 255), 2)
        return output
