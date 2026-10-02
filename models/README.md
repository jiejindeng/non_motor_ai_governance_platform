# 模型目录

把训练完成的部署权重放在：

```text
models/best.pt
```

平台默认读取该文件。也可以：

- 桌面端：点击“选择模型”；
- Web 端：实时监控或系统设置中上传并切换 `.pt`；
- 环境变量：设置 `GOVERNANCE_MODEL=/path/to/best.pt`。

## 类别建议

项目当前推荐统一为：

```text
0 bicycle
1 electric_bicycle
2 tricycle
```

平台层按 `label + confidence + box` 处理，因此可继续扩展 `scooter` 等类别。

> 本源码包不包含训练权重。模型文件通常较大，而且必须来自你自己的训练/授权来源。
