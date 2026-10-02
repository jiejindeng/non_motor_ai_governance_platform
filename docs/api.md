# Web API 概览

默认地址：`http://127.0.0.1:5001`

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/dashboard` | 今日指标、最近事件、7 日趋势 |
| GET | `/api/system` | 模型、输出目录、数据库等系统信息 |
| POST | `/api/model` | 上传并切换 `.pt` 模型 |
| POST | `/api/detect/image` | 单图片检测 |
| POST | `/api/detect/batch` | 多图片/文件夹批量检测 |
| POST | `/api/stream/start` | 启动摄像头/RTSP/HTTP 实时任务 |
| POST | `/api/stream/video` | 上传并分析视频 |
| POST | `/api/stream/stop` | 停止实时任务 |
| GET | `/api/stream/status` | 实时 FPS/目标/轨迹/事件/帧数 |
| GET | `/stream/original.mjpg` | 原始 MJPEG 画面 |
| GET | `/stream/result.mjpg` | AI 结果 MJPEG 画面 |
| POST | `/api/save-current` | 保存当前结果画面 |
| GET | `/api/events` | 查询事件列表 |
| GET | `/api/events/<id>/snapshot` | 获取事件截图 |
| GET | `/api/events/export` | 导出事件 CSV |
| GET/POST | `/api/devices` | 查询/新增设备 |
| PUT/DELETE | `/api/devices/<id>` | 修改/删除设备 |
| GET/POST | `/api/rules` | 获取/应用治理规则 |

## 实时任务限制

当前比赛/试点版本的 Web 后台按“单路主分析任务”设计。切换新视频源时会停止上一条任务。真实多路并发属于后续产品化升级范围。
