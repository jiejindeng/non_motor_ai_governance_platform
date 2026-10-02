# 数据集设计与训练路线

## 1. 三层数据体系

不是训练三个模型，而是：

1. **目标检测数据集**：训练一次多类别 YOLO26 主模型；
2. **目标跟踪视频集**：测试 Track ID 稳定性，不用于当前中心点跟踪器训练；
3. **治理事件验证集**：验证禁区、逆行、滞留规则的召回、误报和延迟。

## 2. 目标检测类别

第一阶段建议：

```text
0 bicycle
1 electric_bicycle
2 tricycle
```

数据建议覆盖校园/园区高位监控视角、白天/夜间、遮挡、密集、小目标、逆光与雨天；负样本建议占 10%~20%。

## 3. 数据划分

对视频抽帧数据不要逐帧随机 8:1:1，否则相邻帧会泄漏到不同 split。优先按“摄像头/视频/日期”分组后再 8:1:1。

本项目提供：

```bash
python dataset_tools/merge_yolo_datasets.py --spec dataset_tools/merge_spec.example.json --output datasets/staging
python dataset_tools/split_by_group.py --staging datasets/staging --output datasets/non_motor_vehicle --clean
python dataset_tools/dataset_stats.py --data datasets/non_motor_vehicle/data.yaml
```

## 4. 训练与评估

```bash
python train.py --model yolo26n.pt --data datasets/non_motor_vehicle/data.yaml --epochs 100
python val.py --weights models/best.pt --split test
```

至少报告：Precision、Recall、mAP50、mAP50-95、FPS，并对夜间/遮挡/小目标场景单独统计。治理事件层建议报告事件召回率、误报率和平均告警延迟。
