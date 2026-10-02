# 数据集工具

推荐流程：

```text
公开数据 + 校园自采
        ↓
merge_yolo_datasets.py
        ↓
datasets/staging
        ↓
split_by_group.py
        ↓
datasets/non_motor_vehicle
        ↓
dataset_stats.py
        ↓
train.py
```

## 为什么按 group 划分

视频抽帧中相邻帧高度相似。如果逐图片随机切分，训练集和测试集会出现近重复帧，导致指标虚高。`split_by_group.py` 会把同一 manifest group 放在同一 split。

如果你的自采帧没有按视频文件夹组织，请在合并前尽量整理为：

```text
raw_campus/
├── cam01_20260910/
├── cam01_20260911/
├── cam02_20260910/
└── ...
```

然后把每组图片与标签放在对应的 images/labels 结构中。
