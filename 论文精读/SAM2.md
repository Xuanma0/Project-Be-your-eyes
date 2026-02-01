## SAM2 落地简报
### 核心能力
**PVS视频分割（围绕给定物体在整个视频中追踪）**，同时拥有图像分割等基础能力。但缺乏SAM3概念分割的能力
### 性能测试
在9400F CPU上，仅Tiny版本推理640x640花费20895.3ms，与SAM3 827ms性能差异较大，估计ultralytics对SAM3存在特殊优化
整体而言推理精度较高

### 示例代码
图像分割

```python
from ultralytics import SAM

def main():
    # 加载 SAM2 模型 (会自动下载，如果本地不存在)
    # 可选模型: sam2_t.pt (tiny), sam2_s.pt (small), sam2_b.pt (base), sam2_l.pt (large)
    model = SAM("sam2_t.pt")

    # 显示模型信息
    model.info()

    # 对 bus.jpg 进行分割并保存结果，固定推理分辨率为640x640
    # bboxes, points, labels 可选参数用于交互式分割
    results = model.predict(source="bus.jpg", save=True, device="cpu", labels=["person", "bus", "glasses"], imgsz=640) # 默认使用 CPU，如果有 GPU 可改为 "cuda"

    print("分割完成，结果已保存到 runs/segment/predict 目录下。")

if __name__ == "__main__":
    main()
```

视频推理

```python
from ultralytics.models.sam import SAM2VideoPredictor

def main():
    # 1. 定义配置参数
    overrides = dict(conf=0.25, task="segment", mode="predict", imgsz=640, model="sam2_t.pt")

    # 2. 初始化视频预测器 (PVS 模式)
    predictor = SAM2VideoPredictor(overrides=overrides)

    # 3. 执行推理并指定起始帧的追踪点
    # source: 视频路径 (例如 "video.mp4")
    # points: [x, y] 格式的点，表示要追踪的物体位置
    # labels: 1 表示前景（追踪该点所属物体），0 表示背景
    results = predictor(source="video.mp4", points=[[320, 240]], labels=[1], save=True, device="cpu")

    print("视频追踪完成，结果已保存。")

if __name__ == "__main__":
    main()
```

### 使用建议
改用更为先进的SAM3
