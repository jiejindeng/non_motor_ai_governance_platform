# 系统架构

项目按照计划书中的六层结构实现：

```text
图片 / 视频 / 摄像头 / RTSP / HTTP
                │
                ▼
        1. 视频接入层 (OpenCV)
                │
                ▼
        2. AI 识别层 (YOLO26)
         label + conf + bbox
                │
                ▼
        3. 轨迹分析层
         CentroidTracker / Track ID
                │
                ▼
        4. 规则引擎层
     禁行区域 / 逆行 / 异常滞留
                │
                ▼
        5. 数据留证层
     SQLite / JPEG / MP4 / CSV
                │
                ▼
        6. 业务展示层
       Flask Web + PyQt5 GUI
```

## 关键解耦

`detector.py` 只负责模型推理并输出统一检测结构；`platform_core.py` 不依赖具体 YOLO 版本。
因此后续将单类 `bicycle` 权重替换成 `bicycle / electric_bicycle / tricycle` 多类权重时，Web、桌面端、事件数据库和规则引擎无需重写。

## 当前跟踪边界

V1/V2 原型使用轻量中心点关联，适合比赛演示与单/少量目标场景。遮挡密集、多目标交叉场景建议后续替换 ByteTrack 或 BoT-SORT。
