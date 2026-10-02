"""非机动车 AI 智慧治理平台 - Flask Web 管理后台。

放置方式：
    项目根目录/
    ├── config.py
    ├── detector.py
    ├── platform_core.py
    ├── models/best.pt
    └── WEB_UI_governance/
        ├── web.py
        ├── templates/index.html
        └── static/{style.css, app.js}

运行：python WEB_UI_governance/web.py
"""
from __future__ import annotations

import atexit
import json
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np
from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import GlobalConfig
from detector import BicycleDetector
from platform_core import CentroidTracker, GovernanceRules, PlatformDatabase, RuleEngine, normalize_detections


APP_NAME = "非机动车 AI 智慧治理平台"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv"}
MODEL_EXTS = {".pt"}

GlobalConfig.ensure_directories()
OUTPUT_DIR = Path(GlobalConfig.OUTPUT_DIR)
PLATFORM_DIR = OUTPUT_DIR / "governance_platform"
SNAPSHOT_DIR = PLATFORM_DIR / "events"
WEB_UPLOAD_DIR = PLATFORM_DIR / "web_uploads"
EXPORT_DIR = PLATFORM_DIR / "web_exports"
MODEL_UPLOAD_DIR = ROOT / "models" / "web_uploads"
RULES_FILE = PLATFORM_DIR / "web_rules.json"
for directory in (PLATFORM_DIR, SNAPSHOT_DIR, WEB_UPLOAD_DIR, EXPORT_DIR, MODEL_UPLOAD_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024  # 1 GiB，视频上传上限
app.config["JSON_AS_ASCII"] = False

db = PlatformDatabase(PLATFORM_DIR / "platform.db")
db_lock = threading.RLock()
detector = BicycleDetector()
detector_lock = threading.RLock()


def load_rules() -> GovernanceRules:
    rules = GovernanceRules()
    if RULES_FILE.exists():
        try:
            data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
            for key, value in data.items():
                if hasattr(rules, key):
                    setattr(rules, key, value)
        except Exception:
            pass
    return rules


rules = load_rules()
rule_engine = RuleEngine(rules)
state: Dict[str, Any] = {
    "model_path": str(getattr(GlobalConfig, "MODEL_PATH", ROOT / "models" / "best.pt")),
}


def save_rules() -> None:
    RULES_FILE.write_text(json.dumps(rules.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def write_cv_image(path: Path, frame) -> None:
    """支持中文路径的 OpenCV 图片写入。"""
    suffix = path.suffix.lower() or ".jpg"
    ok, buf = cv2.imencode(suffix if suffix in IMAGE_EXTS else ".jpg", frame)
    if not ok:
        raise RuntimeError("无法编码图片")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.tobytes())


def decode_image(data: bytes):
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("文件不是有效图片。")
    return frame


class StreamManager:
    """管理单路演示/比赛用实时分析任务，并向浏览器提供 MJPEG。"""

    def __init__(self):
        self.lock = threading.RLock()
        self.log_lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.original_jpeg: Optional[bytes] = None
        self.result_jpeg: Optional[bytes] = None
        self.active = False
        self.device_id: Optional[int] = None
        self.device_name = "默认设备"
        self.source_display = ""
        self.saved_video = ""
        self.stats = {"fps": 0.0, "targets": 0, "tracks": 0, "events": 0, "frames": 0}
        self.logs = []
        self.log_seq = 0
        self.last_error = ""

    def log(self, message: str, level: str = "info") -> None:
        with self.log_lock:
            self.log_seq += 1
            self.logs.append({
                "id": self.log_seq,
                "time": datetime.now().strftime("%H:%M:%S"),
                "message": str(message),
                "level": level,
            })
            if len(self.logs) > 1000:
                self.logs = self.logs[-1000:]

    def get_logs(self, after: int = 0):
        with self.log_lock:
            return [item for item in self.logs if item["id"] > after][-200:]

    @staticmethod
    def _jpeg(frame) -> bytes:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        if not ok:
            raise RuntimeError("无法编码预览画面")
        return buf.tobytes()

    def set_static_frames(self, original, result, targets: int = 0) -> None:
        with self.lock:
            self.original_jpeg = self._jpeg(original)
            self.result_jpeg = self._jpeg(result)
            self.stats.update({"fps": 0.0, "targets": int(targets), "tracks": 0, "events": 0})

    def current_result_bytes(self) -> Optional[bytes]:
        with self.lock:
            return self.result_jpeg

    def start(self, source, device_name: str = "默认设备", device_id: Optional[int] = None) -> None:
        self.stop(wait=True)
        rule_engine.reset()
        self.stop_event.clear()
        self.active = True
        self.last_error = ""
        self.device_name = device_name or "默认设备"
        self.device_id = device_id
        self.source_display = str(source)
        self.saved_video = str(OUTPUT_DIR / "web_stream_{}.mp4".format(datetime.now().strftime("%Y%m%d_%H%M%S")))
        self.stats = {"fps": 0.0, "targets": 0, "tracks": 0, "events": 0, "frames": 0}
        if device_id is not None:
            with db_lock:
                db.set_device_status(device_id, "在线")
        self.thread = threading.Thread(
            target=self._run,
            args=(source,),
            name="governance-web-stream",
            daemon=True,
        )
        self.thread.start()
        self.log("启动实时治理分析：{}".format(source))

    def stop(self, wait: bool = False) -> None:
        self.stop_event.set()
        thread = self.thread
        if wait and thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=4.0)
        if not thread or not thread.is_alive():
            self.active = False

    def _save_event(self, event: Dict[str, Any], snapshot) -> None:
        filename = "{}_{}_ID{}.jpg".format(
            datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
            event.get("event_type", "event"),
            event.get("track_id", 0),
        ).replace("/", "_")
        path = SNAPSHOT_DIR / filename
        try:
            write_cv_image(path, snapshot)
            event["snapshot_path"] = str(path)
        except Exception as exc:
            self.log("事件截图保存失败：{}".format(exc), "warning")
        with db_lock:
            db.add_event(event)
        self.log("治理告警：{} / {} / 轨迹 ID {}".format(
            event.get("event_type"), event.get("target_label"), event.get("track_id")
        ), "warning")

    def _run(self, source) -> None:
        cap = cv2.VideoCapture(source)
        writer = None
        tracker = CentroidTracker()
        pending_flow = 0
        pending_frames = 0
        last_flush = time.monotonic()
        started = time.perf_counter()
        frame_count = 0
        try:
            if not cap.isOpened():
                raise RuntimeError("无法打开视频源，请检查摄像头编号、视频文件或 RTSP/HTTP 地址。")
            source_fps = cap.get(cv2.CAP_PROP_FPS) or float(getattr(GlobalConfig, "VIDEO_FPS", 25) or 25)
            frame_delay = int(getattr(GlobalConfig, "FRAME_DELAY_MS", 10) or 0)
            video_path = Path(self.saved_video)

            while not self.stop_event.is_set():
                ok, frame = cap.read()
                if not ok:
                    break
                with detector_lock:
                    annotated, detections = detector.predict(frame)
                    rows = normalize_detections(detector, detections)
                tracks, new_tracks = tracker.update(rows)
                events = rule_engine.process(tracks, frame.shape, self.device_name)
                result = rule_engine.draw_overlays(annotated.copy(), tracks)

                if writer is None:
                    h, w = result.shape[:2]
                    codec = getattr(GlobalConfig, "VIDEO_CODEC", "mp4v")
                    video_path.parent.mkdir(parents=True, exist_ok=True)
                    writer = cv2.VideoWriter(
                        str(video_path), cv2.VideoWriter_fourcc(*codec), source_fps, (w, h)
                    )
                if writer is not None:
                    writer.write(result)

                frame_count += 1
                elapsed = max(time.perf_counter() - started, 0.001)
                fps = frame_count / elapsed
                with self.lock:
                    self.original_jpeg = self._jpeg(frame)
                    self.result_jpeg = self._jpeg(result)
                    self.stats = {
                        "fps": round(fps, 1),
                        "targets": len(rows),
                        "tracks": len(tracks),
                        "events": len(events),
                        "frames": frame_count,
                    }

                pending_flow += int(new_tracks)
                pending_frames += 1
                if time.monotonic() - last_flush >= 2.0:
                    with db_lock:
                        db.increment_stats(pending_flow, pending_frames)
                    pending_flow = pending_frames = 0
                    last_flush = time.monotonic()

                for event in events:
                    self._save_event(event, result.copy())

                if frame_delay > 0:
                    time.sleep(frame_delay / 1000.0)
        except Exception as exc:
            self.last_error = str(exc)
            self.log("实时任务异常：{}".format(exc), "error")
        finally:
            if pending_flow or pending_frames:
                try:
                    with db_lock:
                        db.increment_stats(pending_flow, pending_frames)
                except Exception:
                    pass
            cap.release()
            if writer is not None:
                writer.release()
            if self.device_id is not None:
                try:
                    with db_lock:
                        db.set_device_status(self.device_id, "已配置")
                except Exception:
                    pass
            self.active = False
            self.stop_event.set()
            self.log("实时治理分析已停止" + ("，结果：{}".format(self.saved_video) if self.saved_video else ""))

    def status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "active": self.active,
                "device_name": self.device_name,
                "source": self.source_display,
                "saved_video": self.saved_video,
                "last_error": self.last_error,
                **self.stats,
            }

    def mjpeg(self, which: str):
        while True:
            with self.lock:
                data = self.original_jpeg if which == "original" else self.result_jpeg
            if data:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + data + b"\r\n"
            time.sleep(0.06)


stream = StreamManager()
stream.log("Web 治理平台已启动，AI 引擎就绪")


def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": str(message)}), status




def ensure_model_loaded():
    if hasattr(detector, "loaded") and not detector.loaded:
        detail = getattr(detector, "last_error", "")
        message = "尚未加载检测模型，请先上传/选择 models/best.pt。"
        if detail:
            message += " 当前加载错误：{}".format(detail)
        return json_error(message, 409)
    return None

def get_device(device_id: int):
    with db_lock:
        for item in db.list_devices():
            if int(item["id"]) == int(device_id):
                return item
    return None


def weekly_stats():
    with db_lock:
        return db.weekly_stats(7)


@app.get("/")
def index():
    return render_template("index.html", app_name=APP_NAME)


@app.get("/api/dashboard")
def api_dashboard():
    with db_lock:
        metrics = db.dashboard_metrics()
        recent = db.list_events(8)
    status = stream.status()
    metrics["fps"] = status["fps"]
    metrics["active_targets"] = status["targets"]
    return jsonify({"ok": True, "metrics": metrics, "recent_events": recent, "weekly": weekly_stats()})


@app.get("/api/system")
def api_system():
    model_info = detector.model_info() if hasattr(detector, "model_info") else {"loaded": True, "path": state["model_path"]}
    return jsonify({
        "ok": True,
        "app_name": APP_NAME,
        "model_path": state["model_path"],
        "model_loaded": bool(model_info.get("loaded")),
        "model_error": model_info.get("last_error", ""),
        "model_classes": model_info.get("classes", {}),
        "output_dir": str(OUTPUT_DIR),
        "database": str(PLATFORM_DIR / "platform.db"),
        "snapshot_dir": str(SNAPSHOT_DIR),
        "rules_file": str(RULES_FILE),
        "model_note": "当前模型若为 bicycle 单类别，只能真实识别其训练过的类别；平台层已兼容 bicycle / electric_bicycle / tricycle 等多类别检测结果。",
    })


@app.post("/api/model")
def api_model_upload():
    uploaded = request.files.get("model")
    if not uploaded or not uploaded.filename:
        return json_error("请选择 .pt 模型文件。")
    suffix = Path(uploaded.filename).suffix.lower()
    if suffix not in MODEL_EXTS:
        return json_error("当前仅支持 .pt 模型。")
    safe = secure_filename(uploaded.filename) or "model.pt"
    path = MODEL_UPLOAD_DIR / "{}_{}".format(datetime.now().strftime("%Y%m%d_%H%M%S"), safe)
    uploaded.save(path)
    try:
        with detector_lock:
            detector.set_model(path)
        state["model_path"] = str(path)
        stream.log("模型已切换：{}".format(path))
        return jsonify({"ok": True, "model_path": str(path)})
    except Exception as exc:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return json_error("模型加载失败：{}".format(exc))


@app.post("/api/detect/image")
def api_detect_image():
    missing = ensure_model_loaded()
    if missing:
        return missing
    uploaded = request.files.get("image")
    if not uploaded or not uploaded.filename:
        return json_error("请选择图片。")
    if Path(uploaded.filename).suffix.lower() not in IMAGE_EXTS:
        return json_error("仅支持 JPG、JPEG、PNG、BMP 图片。")
    try:
        frame = decode_image(uploaded.read())
        with detector_lock:
            result, detections = detector.predict(frame)
            rows = normalize_detections(detector, detections)
        stream.set_static_frames(frame, result, len(rows))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        save_path = WEB_UPLOAD_DIR / "image_results" / "{}_detected.jpg".format(stamp)
        write_cv_image(save_path, result)
        stream.log("{}：检测到 {} 个目标".format(uploaded.filename, len(rows)))
        return jsonify({
            "ok": True,
            "count": len(rows),
            "detections": rows,
            "saved_path": str(save_path),
            "preview_version": time.time_ns(),
        })
    except Exception as exc:
        return json_error("图片检测失败：{}".format(exc))


@app.post("/api/detect/batch")
def api_detect_batch():
    missing = ensure_model_loaded()
    if missing:
        return missing
    uploads = request.files.getlist("images")
    uploads = [f for f in uploads if f and f.filename and Path(f.filename).suffix.lower() in IMAGE_EXTS]
    if not uploads:
        return json_error("请选择包含图片的文件夹或多张图片。")
    if len(uploads) > 500:
        return json_error("单次批量检测最多 500 张图片。")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = WEB_UPLOAD_DIR / "batch_{}".format(stamp)
    batch_dir.mkdir(parents=True, exist_ok=True)
    total_targets = 0
    processed = 0
    last_original = last_result = None
    manifest = []
    try:
        for idx, uploaded in enumerate(uploads, 1):
            try:
                frame = decode_image(uploaded.read())
                with detector_lock:
                    result, detections = detector.predict(frame)
                    rows = normalize_detections(detector, detections)
                total_targets += len(rows)
                processed += 1
                last_original, last_result = frame, result
                original_name = Path(uploaded.filename).name
                safe = secure_filename(original_name)
                if not safe:
                    safe = "image_{:04d}.jpg".format(idx)
                stem = Path(safe).stem
                suffix = Path(safe).suffix.lower()
                if suffix not in IMAGE_EXTS:
                    suffix = ".jpg"
                output_name = "{:04d}_{}_detected{}".format(idx, stem, suffix)
                write_cv_image(batch_dir / output_name, result)
                manifest.append({"file": original_name, "targets": len(rows), "output": output_name})
            except Exception as exc:
                manifest.append({"file": uploaded.filename, "targets": 0, "error": str(exc)})
        (batch_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        zip_name = "batch_{}.zip".format(stamp)
        zip_path = EXPORT_DIR / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in batch_dir.iterdir():
                if path.is_file():
                    zf.write(path, arcname=path.name)
        if last_original is not None and last_result is not None:
            stream.set_static_frames(last_original, last_result, manifest[-1].get("targets", 0))
        stream.log("批量检测完成：{} 张图片 / {} 个目标".format(processed, total_targets))
        return jsonify({
            "ok": True,
            "processed": processed,
            "total_targets": total_targets,
            "download_url": "/downloads/{}".format(zip_name),
            "preview_version": time.time_ns(),
        })
    except Exception as exc:
        return json_error("批量检测失败：{}".format(exc))


@app.post("/api/stream/start")
def api_stream_start():
    missing = ensure_model_loaded()
    if missing:
        return missing
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id")
    source = data.get("source", "0")
    device_name = data.get("device_name", "默认设备")
    if device_id not in (None, ""):
        device = get_device(int(device_id))
        if not device:
            return json_error("设备不存在。", 404)
        source = device["source"]
        device_name = device["name"]
        device_id = int(device["id"])
    else:
        device_id = None
    source_text = str(source).strip() or "0"
    parsed = int(source_text) if source_text.isdigit() else source_text
    stream.start(parsed, device_name, device_id)
    return jsonify({"ok": True, "message": "实时治理分析已启动"})


@app.post("/api/stream/video")
def api_stream_video():
    missing = ensure_model_loaded()
    if missing:
        return missing
    uploaded = request.files.get("video")
    if not uploaded or not uploaded.filename:
        return json_error("请选择视频文件。")
    suffix = Path(uploaded.filename).suffix.lower()
    if suffix not in VIDEO_EXTS:
        return json_error("仅支持 MP4、AVI、MOV、MKV 视频。")
    safe = secure_filename(uploaded.filename) or "video{}".format(suffix)
    path = WEB_UPLOAD_DIR / "videos" / "{}_{}".format(datetime.now().strftime("%Y%m%d_%H%M%S"), safe)
    path.parent.mkdir(parents=True, exist_ok=True)
    uploaded.save(path)
    stream.start(str(path), "视频文件", None)
    return jsonify({"ok": True, "message": "视频分析已启动", "file": str(path)})


@app.post("/api/stream/stop")
def api_stream_stop():
    stream.stop(wait=False)
    stream.log("收到停止任务指令")
    return jsonify({"ok": True})


@app.get("/api/stream/status")
def api_stream_status():
    return jsonify({"ok": True, **stream.status()})


@app.get("/api/logs")
def api_logs():
    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0
    return jsonify({"ok": True, "logs": stream.get_logs(after)})


@app.get("/stream/original.mjpg")
def stream_original():
    return Response(stream.mjpeg("original"), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/stream/result.mjpg")
def stream_result():
    return Response(stream.mjpeg("result"), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.post("/api/save-current")
def api_save_current():
    data = stream.current_result_bytes()
    if not data:
        return json_error("当前没有可保存的检测结果。")
    path = OUTPUT_DIR / "web_saved_{}.jpg".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
    path.write_bytes(data)
    stream.log("当前检测结果已保存：{}".format(path))
    return jsonify({"ok": True, "saved_path": str(path)})


@app.get("/api/events")
def api_events():
    limit = min(max(int(request.args.get("limit", 300)), 1), 2000)
    with db_lock:
        events = db.list_events(limit)
    for event in events:
        event["has_snapshot"] = bool(event.get("snapshot_path") and Path(event["snapshot_path"]).exists())
    return jsonify({"ok": True, "events": events})


@app.get("/api/events/<int:event_id>/snapshot")
def api_event_snapshot(event_id: int):
    with db_lock:
        row = db.get_event(event_id)
    if not row or not row.get("snapshot_path"):
        return json_error("没有事件截图。", 404)
    path = Path(row["snapshot_path"])
    if not path.exists() or not path.is_file():
        return json_error("截图文件不存在。", 404)
    return send_file(path)


@app.get("/api/events/export")
def api_events_export():
    name = "governance_events_{}.csv".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
    path = EXPORT_DIR / name
    with db_lock:
        db.export_events_csv(path)
    return send_file(path, as_attachment=True, download_name=name)


@app.get("/downloads/<path:filename>")
def downloads(filename: str):
    return send_from_directory(str(EXPORT_DIR), filename, as_attachment=True)


@app.route("/api/devices", methods=["GET", "POST"])
def api_devices():
    if request.method == "GET":
        with db_lock:
            devices = db.list_devices()
        return jsonify({"ok": True, "devices": devices})
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    source = str(data.get("source", "")).strip()
    location = str(data.get("location", "")).strip()
    if not name or not source:
        return json_error("设备名称和视频源不能为空。")
    with db_lock:
        device_id = db.add_device(name, source, location)
    return jsonify({"ok": True, "id": device_id})


@app.route("/api/devices/<int:device_id>", methods=["PUT", "DELETE"])
def api_device_item(device_id: int):
    if not get_device(device_id):
        return json_error("设备不存在。", 404)
    if request.method == "DELETE":
        if stream.device_id == device_id and stream.active:
            stream.stop(wait=False)
        with db_lock:
            db.delete_device(device_id)
        return jsonify({"ok": True})
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    source = str(data.get("source", "")).strip()
    location = str(data.get("location", "")).strip()
    if not name or not source:
        return json_error("设备名称和视频源不能为空。")
    with db_lock:
        db.update_device(device_id, name, source, location)
    return jsonify({"ok": True})


@app.route("/api/rules", methods=["GET", "POST"])
def api_rules():
    if request.method == "GET":
        return jsonify({"ok": True, "rules": rules.to_dict()})
    data = request.get_json(silent=True) or {}
    try:
        rules.forbidden_enabled = bool(data.get("forbidden_enabled", False))
        rules.wrong_way_enabled = bool(data.get("wrong_way_enabled", False))
        rules.dwell_enabled = bool(data.get("dwell_enabled", False))
        rules.forbidden_x = max(0.0, min(1.0, float(data.get("forbidden_x", 0.65))))
        rules.forbidden_y = max(0.0, min(1.0, float(data.get("forbidden_y", 0.10))))
        rules.forbidden_w = max(0.01, min(1.0, float(data.get("forbidden_w", 0.30))))
        rules.forbidden_h = max(0.01, min(1.0, float(data.get("forbidden_h", 0.75))))
        rules.expected_direction = str(data.get("expected_direction", "ltr"))
        if rules.expected_direction not in {"ltr", "rtl", "ttb", "btt"}:
            rules.expected_direction = "ltr"
        rules.dwell_seconds = max(2.0, min(120.0, float(data.get("dwell_seconds", 10))))
        rules.min_motion_px = max(10.0, min(300.0, float(data.get("min_motion_px", 35))))
        rules.event_cooldown = max(1.0, min(120.0, float(data.get("event_cooldown", 8))))
        rule_engine.reset()
        save_rules()
        stream.log("治理规则已更新：禁区={}，逆行={}，滞留={}".format(
            rules.forbidden_enabled, rules.wrong_way_enabled, rules.dwell_enabled
        ))
        return jsonify({"ok": True, "rules": rules.to_dict()})
    except Exception as exc:
        return json_error("规则参数无效：{}".format(exc))


@atexit.register
def cleanup():
    try:
        stream.stop(wait=True)
    except Exception:
        pass
    try:
        with db_lock:
            db.close()
    except Exception:
        pass


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
