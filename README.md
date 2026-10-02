# 非机动车 AI 智慧治理平台开发

> 项目愿景：让传统监控从“看得见”升级为“看得懂、能预警、可治理”。

本源码工程按照项目计划书中的产品原型 V1 完整组织，包含 **YOLO 模型适配、图片/批量图片/视频/摄像头/RTSP/HTTP 接入、目标轨迹 ID、禁行区域闯入、逆行、异常滞留、事件截图留证、SQLite 事件库、CSV 导出、设备管理、规则配置、治理总览、Flask Web 后台和 PyQt5 桌面端**。

## 1. 项目结构

```text
non_motor_ai_governance_platform/
├── config.py                     全局配置
├── detector.py                   YOLO26 / Ultralytics 模型适配层
├── platform_core.py              跟踪、规则引擎、SQLite、统计
├── GUI.py                        PyQt5 桌面端
├── run.py                        统一启动入口
├── train.py                      多类别 YOLO 训练
├── val.py                        模型验证
├── predict.py                    命令行推理
├── requirements.txt
├── requirements-web.txt
├── requirements-gui.txt
│
├── WEB_UI/
│   ├── web.py                    Flask 后端 + MJPEG 实时流 + REST API
│   ├── templates/index.html      Web 管理后台
│   └── static/
│       ├── style.css
│       └── app.js
│
├── models/
│   └── README.md                 将 best.pt 放在这里
│
├── datasets/non_motor_vehicle/
│   ├── data.yaml                 bicycle / electric_bicycle / tricycle
│   ├── images/{train,val,test}/
│   └── labels/{train,val,test}/
│
├── dataset_tools/
│   ├── merge_spec.example.json
│   ├── merge_yolo_datasets.py
│   ├── split_by_group.py
│   └── dataset_stats.py
│
├── scripts/
│   ├── check_environment.py
│   ├── seed_demo_data.py
│   └── reset_platform_data.py
│
├── docs/
│   ├── architecture.md
│   ├── dataset_design.md
│   └── deployment.md
│
├── tests/
│   ├── test_platform_core.py
│   └── test_detector_adapter.py
└── output/                       运行时自动生成结果
```

## 2. 安装

推荐先创建独立 Python 环境：

```bash
conda create -n governance python=3.10 -y
conda activate governance
pip install -r requirements.txt
```

如果只运行 Web：

```bash
pip install -r requirements-web.txt
```

如果只运行桌面 GUI：

```bash
pip install -r requirements-gui.txt
```

检查环境：

```bash
python scripts/check_environment.py
```

## 3. 模型准备

当前源码包**不包含模型权重**。把你的训练权重放到：

```text
models/best.pt
```

或者在桌面端 / Web 端点击“选择模型”上传 `.pt`。

当前建议多类别：

```text
0 bicycle
1 electric_bicycle
2 tricycle
```

旧的 `bicycle` 单类别 `best.pt` 仍然可以运行，只是只能真实识别训练过的类别。

## 4. 启动 Web 管理后台

```bash
python run.py web
```

或：

```bash
python WEB_UI/web.py
```

浏览器访问：

```text
http://127.0.0.1:5001
```

Web 端包含：

- 治理总览：今日通行目标 / 事件 / 在线设备 / FPS / 7 日趋势；
- 实时监控：图片、文件夹、视频、本机摄像头、RTSP、HTTP；
- 双画面：原始画面 + AI 检测与治理结果；
- 事件中心：截图证据、搜索、CSV 导出；
- 设备管理：摄像头名称、视频源、位置、状态；
- 规则配置：禁区、逆行、滞留、区域百分比、方向、阈值、冷却；
- 系统设置：模型路径、输出目录、数据库和平台能力。

## 5. 启动 PyQt5 桌面端

```bash
python run.py gui
```

或：

```bash
python GUI.py
```

桌面端和 Web 端共用 `platform_core.py` 的业务逻辑，并默认使用同一 `output/governance_platform/platform.db`。

> 不建议同时让两个端对同一摄像头执行高负载推理；比赛演示时选择一个主入口即可。

## 6. 治理规则

### 禁行区域闯入

治理区域使用画面百分比定义。例如：

```text
X=65%, Y=10%, W=30%, H=75%
```

目标从区域外进入区域内时生成“禁行区域闯入”事件。

### 逆行

设置允许方向：

```text
ltr  从左向右
rtl  从右向左
ttb  从上向下
btt  从下向上
```

当稳定轨迹的净位移与允许方向相反并超过阈值时生成“逆行预警”。

### 异常滞留

目标进入治理区域并持续停留超过配置秒数后生成“异常滞留”，离开区域后计时状态复位。

## 7. 数据集与训练

### 7.1 三层数据体系

本项目不是训练三个网络：

```text
检测数据集 -> 训练一个 YOLO26 多类别主模型
跟踪视频集 -> 测试 Track ID 稳定性
治理事件集 -> 测试禁区/逆行/滞留事件
```

### 7.2 合并公开数据 + 自采数据

编辑：

```text
dataset_tools/merge_spec.example.json
```

然后：

```bash
python dataset_tools/merge_yolo_datasets.py \
  --spec dataset_tools/merge_spec.example.json \
  --output datasets/staging
```

按视频/摄像头分组划分，避免相邻帧泄漏：

```bash
python dataset_tools/split_by_group.py \
  --staging datasets/staging \
  --output datasets/non_motor_vehicle \
  --clean
```

检查统计和标签：

```bash
python dataset_tools/dataset_stats.py \
  --data datasets/non_motor_vehicle/data.yaml
```

### 7.3 训练

```bash
python train.py \
  --model yolo26n.pt \
  --data datasets/non_motor_vehicle/data.yaml \
  --epochs 100 \
  --imgsz 640
```

训练结束后将对应 run 下的 `best.pt` 复制到 `models/best.pt`。

### 7.4 测试

```bash
python val.py --weights models/best.pt --split test
```

建议最终形成：Precision、Recall、mAP50、mAP50-95、FPS，以及夜间、遮挡、小目标、密集场景分组指标。

## 8. 输出数据

平台自动创建：

```text
output/
├── governance_platform/
│   ├── platform.db
│   ├── events/              告警截图
│   ├── web_uploads/
│   ├── web_exports/
│   └── web_rules.json
├── web_stream_*.mp4
└── ...
```

事件数据库记录：

```text
时间 / 设备 / 事件类型 / 目标类别 / Track ID / 置信度 / 截图 / 备注
```

## 9. 比赛演示建议

推荐路演顺序：

```text
治理总览
  -> 实时监控上传一段校园视频
  -> 开启禁区/逆行规则
  -> 触发治理事件
  -> 打开事件中心查看截图证据
  -> 展示设备管理与 CSV 导出
```

如暂时没有真实事件数据，可以运行：

```bash
python scripts/seed_demo_data.py --confirm-demo-data
```

它只生成**明确标记为 DEMO 的排练数据**。正式计划书、PPT 和答辩指标必须替换为真实校园测试结果。

清空本地运行数据：

```bash
python scripts/reset_platform_data.py --yes
```

## 10. 测试

平台核心逻辑不依赖 Flask/PyQt5，可直接运行：

```bash
pytest -q
```

## 11. 当前边界与下一阶段

当前完整项目实现的是计划书中的比赛/试点原型。真实规模化部署仍建议继续升级：

1. ByteTrack / BoT-SORT，提升遮挡和密集场景跟踪稳定性；
2. 鼠标绘制多边形治理区域；
3. 多路 RTSP 并发解码 + GPU 推理队列；
4. 登录、角色权限与审计；
5. PostgreSQL/MySQL 与远程对象存储；
6. WebSocket/MQTT/企业微信等实时告警；
7. 电动自行车、三轮车专用多类别模型与真实校园试点数据。

## 12. 重要说明

- 本工程提供完整源码和目录结构，但**不伪造训练权重、真实准确率或真实客户数据**；
- `.pt` 只应加载可信来源文件；
- Flask 当前配置用于本地演示/试点，正式公网部署需要 WSGI、反向代理、HTTPS、认证与访问控制；
- 采集校园/园区视频时，应遵守所在单位的数据、隐私与监控管理要求。
