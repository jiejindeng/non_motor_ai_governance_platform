"""非机动车 AI 智慧治理平台 - PyQt5 desktop application.

Builds on the original project without replacing detector.py/config.py.
Existing BicycleDetector is reused for inference; platform_core adds tracking,
rule-based governance events, device management, persistence and analytics.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PyQt5.QtCore import QThread, Qt, QTimer, pyqtSignal, QUrl
from PyQt5.QtGui import QDesktopServices, QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QDoubleSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
    QAbstractItemView
)

from config import GlobalConfig
from detector import BicycleDetector
from platform_core import (
    CentroidTracker, GovernanceRules, PlatformDatabase, RuleEngine,
    normalize_detections,
)

IMAGE_FILTER = "图片 (*.jpg *.jpeg *.png *.bmp)"
VIDEO_FILTER = "视频 (*.mp4 *.avi *.mov *.mkv)"


def read_cv_image(path):
    """OpenCV-safe image read that also supports non-ASCII paths."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def write_cv_image(path, frame):
    """OpenCV-safe image write that also supports non-ASCII paths."""
    path = Path(path)
    suffix = path.suffix.lower() if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"} else ".jpg"
    ok, buf = cv2.imencode(suffix, frame)
    if not ok:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        buf.tofile(str(path))
        return True
    except Exception:
        return False


class PreviewLabel(QLabel):
    """A preview widget that keeps source image and scales smoothly on resize."""
    def __init__(self, message: str):
        super().__init__(message)
        self._source_pixmap = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(360, 300)
        self.setObjectName("previewLabel")

    def set_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy()
        self._source_pixmap = QPixmap.fromImage(image)
        self._refresh()

    def clear_frame(self, message: str):
        self._source_pixmap = None
        self.clear()
        self.setText(message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        if self._source_pixmap and not self._source_pixmap.isNull():
            self.setPixmap(self._source_pixmap.scaled(
                max(1, self.width() - 20), max(1, self.height() - 20),
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            ))


class VideoGovernanceThread(QThread):
    frame_signal = pyqtSignal(object, object)
    info_signal = pyqtSignal(str)
    stats_signal = pyqtSignal(object)
    event_signal = pyqtSignal(object, object)
    finished_signal = pyqtSignal(str)

    def __init__(self, detector, source, save_path, device_name, rule_engine):
        super().__init__()
        self.detector = detector
        self.source = source
        self.save_path = Path(save_path) if save_path else None
        self.device_name = device_name
        self.rule_engine = rule_engine
        self.tracker = CentroidTracker()
        self.is_running = True

    def run(self):
        capture = cv2.VideoCapture(self.source)
        writer = None
        if not capture.isOpened():
            self.info_signal.emit("无法打开视频源，请检查文件、摄像头编号或 RTSP/HTTP 地址。")
            self.finished_signal.emit("")
            return
        try:
            source_fps = capture.get(cv2.CAP_PROP_FPS) or getattr(GlobalConfig, "VIDEO_FPS", 25)
            frame_delay = int(getattr(GlobalConfig, "FRAME_DELAY_MS", 10))
            frame_count = 0
            started = time.perf_counter()
            while self.is_running:
                ok, frame = capture.read()
                if not ok:
                    break
                annotated, detections = self.detector.predict(frame)
                rows = normalize_detections(self.detector, detections)
                tracks, new_tracks = self.tracker.update(rows)
                events = self.rule_engine.process(tracks, frame.shape, self.device_name)
                result = self.rule_engine.draw_overlays(annotated.copy(), tracks)

                if self.save_path:
                    if writer is None:
                        self.save_path.parent.mkdir(parents=True, exist_ok=True)
                        h, w = result.shape[:2]
                        codec = getattr(GlobalConfig, "VIDEO_CODEC", "mp4v")
                        writer = cv2.VideoWriter(
                            str(self.save_path), cv2.VideoWriter_fourcc(*codec),
                            source_fps, (w, h)
                        )
                    writer.write(result)

                frame_count += 1
                elapsed = max(time.perf_counter() - started, 0.001)
                fps = frame_count / elapsed
                self.frame_signal.emit(frame, result)
                self.stats_signal.emit({
                    "fps": fps,
                    "targets": len(rows),
                    "tracks": len(tracks),
                    "new_tracks": new_tracks,
                    "frames": 1,
                    "events": len(events),
                })
                for event in events:
                    self.event_signal.emit(event, result.copy())
                if events:
                    self.info_signal.emit("发现 {} 起治理事件".format(len(events)))
                if frame_delay > 0:
                    self.msleep(frame_delay)
        except Exception as error:
            self.info_signal.emit("视频任务异常：{}".format(error))
        finally:
            capture.release()
            if writer:
                writer.release()
            self.finished_signal.emit(str(self.save_path or ""))

    def stop(self):
        self.is_running = False


class MetricCard(QFrame):
    def __init__(self, title, value="0", subtitle="实时更新"):
        super().__init__()
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("metricSubtitle")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(subtitle_label)

    def set_value(self, value):
        self.value_label.setText(str(value))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        GlobalConfig.ensure_directories()
        self.output_dir = Path(GlobalConfig.OUTPUT_DIR)
        self.platform_dir = self.output_dir / "governance_platform"
        self.snapshot_dir = self.platform_dir / "events"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.db = PlatformDatabase(self.platform_dir / "platform.db")
        self.detector = BicycleDetector()
        self.rules = GovernanceRules()
        self.rule_engine = RuleEngine(self.rules)
        self.thread = None
        self.current_original = None
        self.current_result = None
        self.current_device_id = None
        self.current_device_name = "默认设备"
        self.pending_flow = 0
        self.pending_frames = 0

        self.setWindowTitle("非机动车 AI 智慧治理平台")
        self.resize(max(1440, getattr(GlobalConfig, "WINDOW_WIDTH", 1440)),
                    max(900, getattr(GlobalConfig, "WINDOW_HEIGHT", 900)))
        self.setMinimumSize(1180, 760)
        self._build_ui()
        self._apply_style()
        self._refresh_devices()
        self._refresh_events()
        self._refresh_dashboard()
        if not getattr(self.detector, "loaded", False):
            self.sidebar_status.setText("● 模型未加载")
            self.header_state.setText("请选择模型权重")

        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._flush_stats)
        self.stats_timer.start(2000)

    # ----------------------------- UI construction -----------------------------
    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 18)
        side.setSpacing(8)

        brand = QLabel("AI 交通治理")
        brand.setObjectName("brand")
        product = QLabel("非机动车\n智慧治理平台")
        product.setObjectName("productName")
        side.addWidget(brand)
        side.addWidget(product)
        side.addSpacing(18)

        self.nav_buttons = []
        nav_items = [
            ("治理总览", 0), ("实时监控", 1), ("事件中心", 2),
            ("设备管理", 3), ("规则配置", 4), ("系统设置", 5),
        ]
        for title, index in nav_items:
            btn = QPushButton(title)
            btn.setProperty("nav", True)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, i=index: self._switch_page(i))
            side.addWidget(btn)
            self.nav_buttons.append(btn)
        self.nav_buttons[0].setChecked(True)
        side.addStretch(1)

        status_box = QFrame()
        status_box.setObjectName("sidebarStatus")
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.addWidget(QLabel("系统状态"))
        self.sidebar_status = QLabel("● 就绪")
        self.sidebar_status.setObjectName("onlineText")
        status_layout.addWidget(self.sidebar_status)
        side.addWidget(status_box)

        outer.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(26, 22, 26, 24)
        content_layout.setSpacing(16)

        header = QHBoxLayout()
        head_text = QVBoxLayout()
        self.page_title = QLabel("治理总览")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("面向校园、园区与社区的非机动车视觉智能治理")
        self.page_subtitle.setObjectName("pageSubtitle")
        head_text.addWidget(self.page_title)
        head_text.addWidget(self.page_subtitle)
        header.addLayout(head_text)
        header.addStretch(1)
        self.header_state = QLabel("AI 引擎已加载")
        self.header_state.setObjectName("headerBadge")
        header.addWidget(self.header_state)
        content_layout.addLayout(header)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_dashboard_page())
        self.stack.addWidget(self._build_monitor_page())
        self.stack.addWidget(self._build_events_page())
        self.stack.addWidget(self._build_devices_page())
        self.stack.addWidget(self._build_rules_page())
        self.stack.addWidget(self._build_settings_page())
        content_layout.addWidget(self.stack, 1)
        outer.addWidget(content, 1)
        self.setCentralWidget(root)

    def _build_dashboard_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        metrics = QGridLayout()
        metrics.setSpacing(14)
        self.metric_flow = MetricCard("今日通行目标", "0", "基于轨迹去重统计")
        self.metric_events = MetricCard("今日治理事件", "0", "闯入 / 逆行 / 滞留")
        self.metric_devices = MetricCard("在线设备", "0", "摄像头与视频源")
        self.metric_fps = MetricCard("实时推理 FPS", "0.0", "当前分析任务")
        for i, card in enumerate([self.metric_flow, self.metric_events, self.metric_devices, self.metric_fps]):
            metrics.addWidget(card, 0, i)
        layout.addLayout(metrics)

        body = QHBoxLayout()
        body.setSpacing(16)
        quick = self._card("快速开始")
        ql = quick.layout()
        ql.addWidget(self._muted("从现有监控视频或摄像头直接进入 AI 分析。"))
        q1 = QPushButton("进入实时监控")
        q1.setObjectName("primaryButton")
        q1.clicked.connect(lambda: self._switch_page(1))
        ql.addWidget(q1)
        q2 = QPushButton("查看治理事件")
        q2.setObjectName("secondaryButton")
        q2.clicked.connect(lambda: self._switch_page(2))
        ql.addWidget(q2)
        flow = QLabel("摄像头 → AI识别 → 目标跟踪 → 规则判断 → 告警留证 → 数据统计")
        flow.setWordWrap(True)
        flow.setObjectName("flowText")
        ql.addWidget(flow)
        ql.addStretch(1)
        body.addWidget(quick, 1)

        latest = self._card("最新治理事件")
        ll = latest.layout()
        self.dashboard_event_table = self._new_table(["时间", "设备", "事件", "目标"])
        ll.addWidget(self.dashboard_event_table)
        body.addWidget(latest, 2)
        layout.addLayout(body, 1)
        return page

    def _build_monitor_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        toolbar = self._card("")
        tl = toolbar.layout()
        top = QHBoxLayout()
        self.model_input = QLineEdit(str(GlobalConfig.MODEL_PATH))
        self.model_input.setPlaceholderText("模型权重 .pt")
        self.source_input = QLineEdit("0")
        self.source_input.setPlaceholderText("摄像头编号 / RTSP / HTTP")
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._device_selected)
        top.addWidget(self._field("模型权重", self.model_input), 3)
        top.addWidget(self._field("设备", self.device_combo), 2)
        top.addWidget(self._field("摄像头/流", self.source_input), 2)
        tl.addLayout(top)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        for title, callback, obj in [
            ("选择模型", self.choose_model, "secondaryButton"),
            ("图片检测", self.detect_image, "primaryButton"),
            ("批量检测", self.detect_folder, "secondaryButton"),
            ("视频检测", self.detect_video, "secondaryButton"),
            ("启动摄像头", self.detect_camera, "primaryButton"),
            ("保存结果", self.save_current, "secondaryButton"),
            ("停止任务", self.stop_stream, "dangerButton"),
        ]:
            btn = QPushButton(title)
            btn.setObjectName(obj)
            btn.clicked.connect(callback)
            actions.addWidget(btn)
        actions.addStretch(1)
        tl.addLayout(actions)
        layout.addWidget(toolbar)

        previews = QHBoxLayout()
        previews.setSpacing(12)
        original_card = self._card("原始画面")
        result_card = self._card("AI 检测与治理结果")
        self.original_view = PreviewLabel("等待输入")
        self.result_view = PreviewLabel("等待检测")
        original_card.layout().addWidget(self.original_view, 1)
        result_card.layout().addWidget(self.result_view, 1)
        previews.addWidget(original_card, 1)
        previews.addWidget(result_card, 1)
        layout.addLayout(previews, 1)

        status_row = QHBoxLayout()
        self.monitor_targets = self._mini_stat("当前目标", "0")
        self.monitor_tracks = self._mini_stat("活动轨迹", "0")
        self.monitor_events = self._mini_stat("本帧事件", "0")
        self.monitor_fps = self._mini_stat("FPS", "0.0")
        for widget in [self.monitor_targets, self.monitor_tracks, self.monitor_events, self.monitor_fps]:
            status_row.addWidget(widget)
        layout.addLayout(status_row)

        log_card = self._card("运行日志")
        log_card.setMinimumHeight(190)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(130)
        self.log.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log.document().setMaximumBlockCount(1000)
        log_card.layout().addWidget(self.log)
        layout.addWidget(log_card)
        return page

    def _build_events_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        actions = QHBoxLayout()
        refresh = QPushButton("刷新事件")
        refresh.setObjectName("primaryButton")
        refresh.clicked.connect(self._refresh_events)
        export = QPushButton("导出 CSV")
        export.setObjectName("secondaryButton")
        export.clicked.connect(self.export_events)
        open_dir = QPushButton("打开截图目录")
        open_dir.setObjectName("secondaryButton")
        open_dir.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.snapshot_dir.resolve()))))
        actions.addWidget(refresh)
        actions.addWidget(export)
        actions.addWidget(open_dir)
        actions.addStretch(1)
        layout.addLayout(actions)

        card = self._card("事件留证记录")
        self.event_table = self._new_table(["时间", "设备", "事件类型", "目标", "轨迹ID", "置信度", "截图路径"])
        self.event_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.event_table.doubleClicked.connect(self._open_selected_snapshot)
        card.layout().addWidget(self.event_table)
        layout.addWidget(card, 1)
        return page

    def _build_devices_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        form_card = self._card("新增 / 编辑设备")
        fl = form_card.layout()
        row = QHBoxLayout()
        self.device_name_input = QLineEdit()
        self.device_name_input.setPlaceholderText("例如：学校东门")
        self.device_source_input = QLineEdit()
        self.device_source_input.setPlaceholderText("0 / rtsp://... / http://...")
        self.device_location_input = QLineEdit()
        self.device_location_input.setPlaceholderText("安装位置")
        row.addWidget(self._field("设备名称", self.device_name_input), 2)
        row.addWidget(self._field("视频源", self.device_source_input), 3)
        row.addWidget(self._field("位置", self.device_location_input), 2)
        fl.addLayout(row)
        act = QHBoxLayout()
        add = QPushButton("新增设备")
        add.setObjectName("primaryButton")
        add.clicked.connect(self._add_device)
        update = QPushButton("更新选中")
        update.setObjectName("secondaryButton")
        update.clicked.connect(self._update_device)
        delete = QPushButton("删除选中")
        delete.setObjectName("dangerButton")
        delete.clicked.connect(self._delete_device)
        start = QPushButton("用选中设备监控")
        start.setObjectName("secondaryButton")
        start.clicked.connect(self._monitor_selected_device)
        for b in [add, update, delete, start]:
            act.addWidget(b)
        act.addStretch(1)
        fl.addLayout(act)
        layout.addWidget(form_card)

        table_card = self._card("设备列表")
        self.device_table = self._new_table(["ID", "设备名称", "视频源", "位置", "状态", "创建时间"])
        self.device_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.device_table.itemSelectionChanged.connect(self._fill_device_form)
        table_card.layout().addWidget(self.device_table)
        layout.addWidget(table_card, 1)
        return page

    def _build_rules_page(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        intro = self._card("AI 治理规则")
        intro.layout().addWidget(self._muted("规则作用于视频/摄像头实时轨迹。区域坐标采用画面百分比，可先用演示场景测试。"))
        outer.addWidget(intro)

        card = self._card("规则参数")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        self.rule_forbidden = QCheckBox("启用禁行区域闯入")
        self.rule_wrong_way = QCheckBox("启用逆行预警")
        self.rule_dwell = QCheckBox("启用区域滞留")
        grid.addWidget(self.rule_forbidden, 0, 0, 1, 2)
        grid.addWidget(self.rule_wrong_way, 0, 2, 1, 2)
        grid.addWidget(self.rule_dwell, 0, 4, 1, 2)

        self.zone_x = self._percent_spin(65)
        self.zone_y = self._percent_spin(10)
        self.zone_w = self._percent_spin(30)
        self.zone_h = self._percent_spin(75)
        grid.addWidget(self._field("区域 X (%)", self.zone_x), 1, 0)
        grid.addWidget(self._field("区域 Y (%)", self.zone_y), 1, 1)
        grid.addWidget(self._field("区域宽度 (%)", self.zone_w), 1, 2)
        grid.addWidget(self._field("区域高度 (%)", self.zone_h), 1, 3)

        self.direction_combo = QComboBox()
        self.direction_combo.addItem("从左向右", "ltr")
        self.direction_combo.addItem("从右向左", "rtl")
        self.direction_combo.addItem("从上向下", "ttb")
        self.direction_combo.addItem("从下向上", "btt")
        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setRange(2, 120)
        self.dwell_spin.setValue(10)
        self.dwell_spin.setSuffix(" 秒")
        self.motion_spin = QSpinBox()
        self.motion_spin.setRange(10, 300)
        self.motion_spin.setValue(35)
        self.motion_spin.setSuffix(" px")
        grid.addWidget(self._field("允许通行方向", self.direction_combo), 2, 0, 1, 2)
        grid.addWidget(self._field("滞留阈值", self.dwell_spin), 2, 2)
        grid.addWidget(self._field("逆行位移阈值", self.motion_spin), 2, 3)

        apply_btn = QPushButton("应用治理规则")
        apply_btn.setObjectName("primaryButton")
        apply_btn.clicked.connect(self._apply_rules)
        grid.addWidget(apply_btn, 3, 0, 1, 2)
        card.layout().addLayout(grid)
        outer.addWidget(card)
        outer.addStretch(1)
        return page

    def _build_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        card = self._card("平台信息")
        card.layout().addWidget(QLabel("当前模型：{}".format(GlobalConfig.MODEL_PATH)))
        card.layout().addWidget(QLabel("输出目录：{}".format(self.output_dir)))
        card.layout().addWidget(QLabel("事件数据库：{}".format(self.platform_dir / "platform.db")))
        note = self._muted(
            "当前项目原始权重为 bicycle 单类别时，平台会把它作为非机动车基础目标使用。"
            "如需真正区分自行车、电动自行车等类别，需要更换/训练相应多类别模型权重；平台层已兼容多类别检测结果。"
        )
        note.setWordWrap(True)
        card.layout().addWidget(note)
        layout.addWidget(card)
        layout.addStretch(1)
        return page

    # ----------------------------- helpers -----------------------------
    def _card(self, title):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        if title:
            label = QLabel(title)
            label.setObjectName("cardTitle")
            layout.addWidget(label)
        return frame

    def _field(self, title, widget):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(title)
        label.setObjectName("fieldLabel")
        layout.addWidget(label)
        layout.addWidget(widget)
        return box

    def _mini_stat(self, title, value):
        card = QFrame()
        card.setObjectName("miniStat")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 8, 12, 8)
        label = QLabel(title)
        label.setObjectName("miniTitle")
        val = QLabel(value)
        val.setObjectName("miniValue")
        card.value_label = val
        lay.addWidget(label)
        lay.addStretch(1)
        lay.addWidget(val)
        return card

    @staticmethod
    def _muted(text):
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    @staticmethod
    def _percent_spin(value):
        spin = QDoubleSpinBox()
        spin.setRange(0, 100)
        spin.setDecimals(1)
        spin.setValue(value)
        spin.setSuffix(" %")
        return spin

    @staticmethod
    def _new_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        return table

    def _apply_style(self):
        self.setStyleSheet("""
        * { font-family: "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 13px; }
        #root { background: #f5f7fb; color: #172033; }
        #sidebar { background: #0b1220; border: none; }
        #brand { color: #60a5fa; font-size: 12px; font-weight: 800; letter-spacing: 2px; }
        #productName { color: white; font-size: 23px; font-weight: 800; line-height: 1.3; }
        QPushButton[nav="true"] { text-align: left; color: #aeb9cc; background: transparent; border: none; border-radius: 9px; padding: 11px 14px; font-weight: 600; }
        QPushButton[nav="true"]:hover { background: #142036; color: white; }
        QPushButton[nav="true"]:checked { background: #1d4ed8; color: white; }
        #sidebarStatus { background: #111c30; border: 1px solid #1f2d46; border-radius: 10px; color: #9ba9bf; }
        #onlineText { color: #34d399; font-weight: 700; }
        #pageTitle { font-size: 25px; font-weight: 800; color: #111827; }
        #pageSubtitle { color: #6b7280; }
        #headerBadge { background: #e8f0ff; color: #1d4ed8; border-radius: 12px; padding: 7px 12px; font-weight: 700; }
        #card, #metricCard { background: white; border: 1px solid #e5eaf2; border-radius: 13px; }
        #cardTitle { font-size: 15px; font-weight: 800; color: #1f2937; }
        #metricTitle { color: #6b7280; font-weight: 600; }
        #metricValue { font-size: 28px; font-weight: 900; color: #111827; padding-top: 3px; }
        #metricSubtitle { color: #9ca3af; font-size: 11px; }
        #muted { color: #6b7280; }
        #flowText { color: #1d4ed8; background: #eef4ff; border-radius: 9px; padding: 12px; font-weight: 600; }
        #fieldLabel { color: #475569; font-weight: 700; font-size: 12px; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { min-height: 34px; border: 1px solid #d8dfeb; border-radius: 8px; padding: 0 10px; background: white; color: #111827; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid #3b82f6; }
        QPushButton { min-height: 34px; border-radius: 8px; padding: 0 14px; font-weight: 700; }
        #primaryButton { background: #2563eb; color: white; border: none; }
        #primaryButton:hover { background: #1d4ed8; }
        #secondaryButton { background: #f8fafc; color: #334155; border: 1px solid #d8dfeb; }
        #secondaryButton:hover { background: #eef2f7; }
        #dangerButton { background: #fff1f2; color: #be123c; border: 1px solid #fecdd3; }
        #dangerButton:hover { background: #ffe4e6; }
        #previewLabel { background: #0f172a; color: #94a3b8; border: 1px solid #1e293b; border-radius: 10px; font-size: 15px; }
        #miniStat { background: white; border: 1px solid #e5eaf2; border-radius: 9px; }
        #miniTitle { color: #64748b; font-weight: 600; }
        #miniValue { color: #1d4ed8; font-weight: 900; font-size: 17px; }
        QTextEdit { background: #0f172a; color: #cbd5e1; border: 1px solid #1e293b; border-radius: 8px; padding: 8px; }
        QTableWidget { background: white; alternate-background-color: #f8fafc; border: 1px solid #e5eaf2; border-radius: 8px; gridline-color: #eef2f7; selection-background-color: #e8f0ff; selection-color: #1e3a8a; }
        QHeaderView::section { background: #f8fafc; color: #475569; font-weight: 800; border: none; border-bottom: 1px solid #e5eaf2; padding: 9px; }
        QCheckBox { color: #334155; font-weight: 700; spacing: 8px; }
        QScrollBar:vertical { background: #0f172a; width: 10px; margin: 0; }
        QScrollBar::handle:vertical { background: #475569; min-height: 28px; border-radius: 5px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

    # ----------------------------- navigation -----------------------------
    def _switch_page(self, index):
        titles = ["治理总览", "实时监控", "事件中心", "设备管理", "规则配置", "系统设置"]
        subtitles = [
            "核心指标、治理事件与设备状态一屏掌握",
            "图片、视频、摄像头与网络流的实时 AI 分析",
            "异常事件自动记录、截图留证与结果导出",
            "统一管理摄像头、RTSP/HTTP 视频源与安装位置",
            "配置禁行区域、逆行方向和滞留阈值",
            "平台路径、模型能力与运行信息",
        ]
        self.stack.setCurrentIndex(index)
        self.page_title.setText(titles[index])
        self.page_subtitle.setText(subtitles[index])
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)
        if index == 0:
            self._refresh_dashboard()
        elif index == 2:
            self._refresh_events()
        elif index == 3:
            self._refresh_devices()

    # ----------------------------- model / detection -----------------------------
    def append_log(self, message):
        if hasattr(self, "log"):
            self.log.append("[{}] {}".format(datetime.now().strftime("%H:%M:%S"), message))
            bar = self.log.verticalScrollBar()
            bar.setValue(bar.maximum())

    def choose_model(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择模型", self.model_input.text(), "模型 (*.pt)")
        if path:
            self.stop_stream()
            self.model_input.setText(path)
            try:
                self.detector.set_model(path)
                self.append_log("模型已切换：{}".format(path))
                self.header_state.setText("AI 引擎已加载")
                self.sidebar_status.setText("● 就绪")
            except Exception as error:
                QMessageBox.critical(self, "模型加载失败", str(error))

    def _ensure_model(self):
        path = Path(self.model_input.text()).expanduser().resolve()
        if not path.exists():
            QMessageBox.warning(self, "未找到模型", "请选择有效的 .pt 模型权重。")
            return False
        try:
            current = Path(getattr(self.detector, "model_path", path)).expanduser().resolve()
            if not getattr(self.detector, "loaded", False) or current != path:
                self.detector.set_model(path)
            return True
        except Exception as error:
            QMessageBox.critical(self, "模型加载失败", str(error))
            return False

    def detect_image(self):
        if not self._ensure_model():
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", IMAGE_FILTER)
        if not path:
            return
        frame = read_cv_image(path)
        if frame is None:
            QMessageBox.warning(self, "读取失败", "无法读取图片文件。")
            return
        try:
            result, detections = self.detector.predict(frame)
            rows = normalize_detections(self.detector, detections)
            self.show_frames(frame, result)
            self.monitor_targets.value_label.setText(str(len(rows)))
            self.monitor_tracks.value_label.setText("-")
            self.monitor_events.value_label.setText("0")
            self.append_log("{}：检测到 {} 个目标".format(Path(path).name, len(rows)))
        except Exception as error:
            QMessageBox.critical(self, "检测失败", str(error))

    def detect_folder(self):
        if not self._ensure_model():
            return
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        image_paths = [p for p in Path(folder).iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}]
        if not image_paths:
            QMessageBox.information(self, "没有图片", "该文件夹中没有支持的图片。")
            return
        output = self.output_dir / "folder_{}".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        output.mkdir(parents=True, exist_ok=True)
        total = 0
        for index, path in enumerate(sorted(image_paths), 1):
            frame = read_cv_image(path)
            if frame is None:
                continue
            result, detections = self.detector.predict(frame)
            rows = normalize_detections(self.detector, detections)
            write_cv_image(output / "{}_detected{}".format(path.stem, path.suffix), result)
            self.show_frames(frame, result)
            total += len(rows)
            QApplication.processEvents()
            self.append_log("{}/{} {}：{} 个目标".format(index, len(image_paths), path.name, len(rows)))
        self.append_log("批量检测完成：{} 张图片 / {} 个目标；结果：{}".format(len(image_paths), total, output))

    def detect_video(self):
        if not self._ensure_model():
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择视频", "", VIDEO_FILTER)
        if path:
            self.start_stream(path, "video_{}.mp4".format(datetime.now().strftime("%Y%m%d_%H%M%S")), "视频文件")

    def detect_camera(self):
        if not self._ensure_model():
            return
        source = self.source_input.text().strip() or "0"
        parsed = int(source) if source.isdigit() else source
        self.start_stream(parsed, "camera_{}.mp4".format(datetime.now().strftime("%Y%m%d_%H%M%S")), self.current_device_name)

    def start_stream(self, source, filename, device_name="默认设备"):
        self.stop_stream()
        self.rule_engine.reset()
        path = self.output_dir / filename
        self.current_device_name = device_name or "默认设备"
        if self.current_device_id:
            self.db.set_device_status(self.current_device_id, "在线")
        self.thread = VideoGovernanceThread(self.detector, source, path, self.current_device_name, self.rule_engine)
        self.thread.frame_signal.connect(self.show_frames)
        self.thread.info_signal.connect(self.append_log)
        self.thread.stats_signal.connect(self._on_stream_stats)
        self.thread.event_signal.connect(self._on_governance_event)
        self.thread.finished_signal.connect(self._on_stream_finished)
        self.thread.start()
        self.sidebar_status.setText("● 分析中")
        self.header_state.setText("AI 实时分析中")
        self.append_log("启动实时治理分析：{}".format(source))

    def stop_stream(self):
        if self.thread and self.thread.isRunning():
            self.thread.stop()
            self.thread.wait(3000)
        self.thread = None
        if self.current_device_id:
            self.db.set_device_status(self.current_device_id, "已配置")
        if hasattr(self, "sidebar_status"):
            self.sidebar_status.setText("● 就绪")
            self.header_state.setText("AI 引擎已加载")

    def _on_stream_finished(self, path):
        if path:
            self.append_log("视频任务已停止，结果：{}".format(path))
        else:
            self.append_log("视频任务已停止")
        if self.current_device_id:
            self.db.set_device_status(self.current_device_id, "已配置")
        self.sidebar_status.setText("● 就绪")
        self.header_state.setText("AI 引擎已加载")
        self._refresh_dashboard()

    def _on_stream_stats(self, stats):
        self.monitor_targets.value_label.setText(str(stats.get("targets", 0)))
        self.monitor_tracks.value_label.setText(str(stats.get("tracks", 0)))
        self.monitor_events.value_label.setText(str(stats.get("events", 0)))
        fps = float(stats.get("fps", 0.0))
        self.monitor_fps.value_label.setText("{:.1f}".format(fps))
        self.metric_fps.set_value("{:.1f}".format(fps))
        self.pending_flow += int(stats.get("new_tracks", 0))
        self.pending_frames += int(stats.get("frames", 0))

    def _on_governance_event(self, event, snapshot):
        filename = "{}_{}_ID{}.jpg".format(
            datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
            event.get("event_type", "event"), event.get("track_id", 0)
        ).replace("/", "_")
        path = self.snapshot_dir / filename
        try:
            write_cv_image(path, snapshot)
            event["snapshot_path"] = str(path)
        except Exception:
            pass
        self.db.add_event(event)
        self.append_log("治理告警：{} / {} / 轨迹 ID {}".format(
            event.get("event_type"), event.get("target_label"), event.get("track_id")
        ))
        self._refresh_events()
        self._refresh_dashboard()

    def _flush_stats(self):
        if self.pending_flow or self.pending_frames:
            self.db.increment_stats(self.pending_flow, self.pending_frames)
            self.pending_flow = 0
            self.pending_frames = 0
            if self.stack.currentIndex() == 0:
                self._refresh_dashboard()

    def show_frames(self, original, result):
        self.current_original = original.copy()
        self.current_result = result.copy()
        self.original_view.set_frame(original)
        self.result_view.set_frame(result)

    def save_current(self):
        if self.current_result is None:
            QMessageBox.information(self, "没有结果", "请先完成一次图片或视频检测。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存检测结果", str(self.output_dir / "detected.jpg"), "图片 (*.jpg *.png)"
        )
        if path and write_cv_image(path, self.current_result):
            self.append_log("当前结果已保存：{}".format(path))

    # ----------------------------- governance rules -----------------------------
    def _apply_rules(self):
        self.rules.forbidden_enabled = self.rule_forbidden.isChecked()
        self.rules.wrong_way_enabled = self.rule_wrong_way.isChecked()
        self.rules.dwell_enabled = self.rule_dwell.isChecked()
        self.rules.forbidden_x = self.zone_x.value() / 100.0
        self.rules.forbidden_y = self.zone_y.value() / 100.0
        self.rules.forbidden_w = self.zone_w.value() / 100.0
        self.rules.forbidden_h = self.zone_h.value() / 100.0
        self.rules.expected_direction = self.direction_combo.currentData()
        self.rules.dwell_seconds = self.dwell_spin.value()
        self.rules.min_motion_px = float(self.motion_spin.value())
        self.rule_engine.reset()
        QMessageBox.information(self, "规则已应用", "治理规则已更新，将作用于后续视频/摄像头分析。")
        self.append_log("治理规则已更新：禁区={}，逆行={}，滞留={}".format(
            self.rules.forbidden_enabled, self.rules.wrong_way_enabled, self.rules.dwell_enabled
        ))

    # ----------------------------- devices -----------------------------
    def _refresh_devices(self):
        devices = self.db.list_devices()
        if hasattr(self, "device_table"):
            self.device_table.setRowCount(len(devices))
            for r, d in enumerate(devices):
                values = [d["id"], d["name"], d["source"], d["location"], d["status"], d["created_at"]]
                for c, value in enumerate(values):
                    self.device_table.setItem(r, c, QTableWidgetItem(str(value)))
        if hasattr(self, "device_combo"):
            current_id = self.current_device_id
            self.device_combo.blockSignals(True)
            self.device_combo.clear()
            for d in devices:
                self.device_combo.addItem("{} · {}".format(d["name"], d["location"] or "未设置位置"), d)
            self.device_combo.blockSignals(False)
            if devices:
                idx = 0
                if current_id:
                    for i, d in enumerate(devices):
                        if d["id"] == current_id:
                            idx = i
                            break
                self.device_combo.setCurrentIndex(idx)
                self._device_selected(idx)

    def _device_selected(self, index):
        if index < 0 or not hasattr(self, "device_combo"):
            return
        data = self.device_combo.itemData(index)
        if isinstance(data, dict):
            self.current_device_id = data["id"]
            self.current_device_name = data["name"]
            self.source_input.setText(data["source"])

    def _add_device(self):
        name = self.device_name_input.text().strip()
        source = self.device_source_input.text().strip()
        location = self.device_location_input.text().strip()
        if not name or not source:
            QMessageBox.warning(self, "信息不完整", "设备名称和视频源不能为空。")
            return
        self.db.add_device(name, source, location)
        self._refresh_devices()
        self._clear_device_form()

    def _selected_device_id(self):
        row = self.device_table.currentRow()
        if row < 0:
            return None
        item = self.device_table.item(row, 0)
        return int(item.text()) if item else None

    def _fill_device_form(self):
        row = self.device_table.currentRow()
        if row < 0:
            return
        self.device_name_input.setText(self.device_table.item(row, 1).text())
        self.device_source_input.setText(self.device_table.item(row, 2).text())
        self.device_location_input.setText(self.device_table.item(row, 3).text())

    def _clear_device_form(self):
        self.device_name_input.clear()
        self.device_source_input.clear()
        self.device_location_input.clear()

    def _update_device(self):
        did = self._selected_device_id()
        if did is None:
            QMessageBox.information(self, "未选择设备", "请先在设备列表中选择一行。")
            return
        self.db.update_device(did, self.device_name_input.text(), self.device_source_input.text(), self.device_location_input.text())
        self._refresh_devices()

    def _delete_device(self):
        did = self._selected_device_id()
        if did is None:
            QMessageBox.information(self, "未选择设备", "请先选择要删除的设备。")
            return
        self.db.delete_device(did)
        self._refresh_devices()
        self._clear_device_form()

    def _monitor_selected_device(self):
        row = self.device_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "未选择设备", "请先选择一个设备。")
            return
        did = int(self.device_table.item(row, 0).text())
        name = self.device_table.item(row, 1).text()
        source = self.device_table.item(row, 2).text()
        self.current_device_id = did
        self.current_device_name = name
        self.source_input.setText(source)
        self._switch_page(1)

    # ----------------------------- events / dashboard -----------------------------
    def _refresh_events(self):
        events = self.db.list_events(300)
        if hasattr(self, "event_table"):
            self.event_table.setRowCount(len(events))
            for r, e in enumerate(events):
                vals = [
                    e["timestamp"], e["device"], e["event_type"], e["target_label"],
                    e["track_id"], "{:.1%}".format(float(e["confidence"] or 0)), e["snapshot_path"],
                ]
                for c, v in enumerate(vals):
                    self.event_table.setItem(r, c, QTableWidgetItem(str(v)))
        if hasattr(self, "dashboard_event_table"):
            latest = events[:8]
            self.dashboard_event_table.setRowCount(len(latest))
            for r, e in enumerate(latest):
                vals = [e["timestamp"][11:19], e["device"], e["event_type"], e["target_label"]]
                for c, v in enumerate(vals):
                    self.dashboard_event_table.setItem(r, c, QTableWidgetItem(str(v)))

    def _refresh_dashboard(self):
        metrics = self.db.dashboard_metrics()
        self.metric_flow.set_value(metrics["flow_count"] + self.pending_flow)
        self.metric_events.set_value(metrics["event_count"])
        self.metric_devices.set_value(metrics["online_devices"])
        self._refresh_events()

    def export_events(self):
        default = self.output_dir / "governance_events_{}.csv".format(datetime.now().strftime("%Y%m%d_%H%M%S"))
        path, _ = QFileDialog.getSaveFileName(self, "导出治理事件", str(default), "CSV (*.csv)")
        if path:
            self.db.export_events_csv(Path(path))
            QMessageBox.information(self, "导出完成", "事件数据已导出：\n{}".format(path))

    def _open_selected_snapshot(self):
        row = self.event_table.currentRow()
        if row < 0:
            return
        item = self.event_table.item(row, 6)
        if item and item.text() and Path(item.text()).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(item.text()).resolve())))

    def closeEvent(self, event):
        self._flush_stats()
        self.stop_stream()
        self.db.close()
        event.accept()


if __name__ == "__main__":
    application = QApplication(sys.argv)
    application.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(application.exec_())
