# 项目计划书 → 源码实现映射

| 计划书能力 | 源码位置 | 状态 |
|---|---|---|
| 图片检测 | `detector.py` + `GUI.py` + `WEB_UI/web.py` | 已实现 |
| 文件夹批量检测 | `GUI.py` / `/api/detect/batch` | 已实现 |
| 视频文件分析 | `GUI.py` / `/api/stream/video` | 已实现 |
| 摄像头 / RTSP / HTTP | `VideoGovernanceThread` / `StreamManager` | 已实现 |
| YOLO26 目标检测 | `detector.py` | 已实现接口；需要用户提供 `.pt` |
| 统一 `label + confidence + box` | `detector.py` / `normalize_detections` | 已实现 |
| Track ID / 轨迹 | `CentroidTracker` | 已实现轻量版 |
| 禁行区域闯入 | `RuleEngine` | 已实现 |
| 逆行预警 | `RuleEngine` | 已实现 |
| 异常滞留 | `RuleEngine` | 已实现 |
| 告警冷却 | `GovernanceRules` / `RuleEngine` | 已实现 |
| 自动截图留证 | GUI/Web 事件处理 | 已实现 |
| SQLite 事件库 | `PlatformDatabase` | 已实现 |
| CSV 导出 | `PlatformDatabase.export_events_csv` | 已实现 |
| 设备管理 | SQLite + Web/GUI | 已实现 |
| 治理总览 | Web/GUI Dashboard | 已实现 |
| 近 7 日趋势 | `PlatformDatabase.weekly_stats` + Web Canvas | 已实现 |
| Web 管理后台 | `WEB_UI/` | 已实现 |
| PyQt5 桌面端 | `GUI.py` | 已实现 |
| 三类非机动车模型 | `datasets/` + `train.py` | 训练管线已提供；需要真实数据/训练 |
| 校园真实指标 | 真实试点 | **不能由源码生成，需要实测** |
| 多路 RTSP 并发 | 后续产品化 | 未纳入当前单路原型 |
| ByteTrack / BoT-SORT | 后续模型升级 | 未纳入当前轻量原型 |
| 登录/权限/移动告警 | 后续产品化 | 未纳入当前原型 |

## 不在源码包中伪造的内容

1. `models/best.pt`：需要你的训练权重；
2. 真实校园视频数据：需要合法采集或授权；
3. Precision / Recall / mAP / FPS 等比赛指标：需要在指定硬件和测试集上实测；
4. 客户合同、试点证明、专利/软著证明：需要真实材料。
