## SAM3落地简报

**功能**
1. **基于名词短语的概念分割**（Promptable Concept Segmentation, PCS）
2. **开放词汇检测与分割**
3. **图像范例提示**（正/负样本框）
4. **几何视觉提示**（点、框、涂鸦）
5. **全实例分割**（同一概念的所有对象）
6. **视频对象检测与跟踪**
8. **交互式掩码细化**（正/负点击修正）
9. **语义分割输出**
10. **实例分割输出**
11. **目标计数**
12. **小样本适应**
13. **与MLLM结合的复杂查询处理**
14. **流式视频推理**
15. **预加载视频推理**

**优势：**
1. 允许人工多次反复校准（但本项目难以涉及）
2. 基于自然语言的识别，泛化性强
3. 支持在视频流中实时追踪物体（PCS Task），可能有用
4. SAM3 Agent设计，允许将SAM3作为tool供MLLM调用

**劣势：**
1. 8.5亿参数，无端侧部署可能
2. 有一定延时，如与LLM配合使用产生更长调用时间
3. 无直接量化方法

**结论：**

**无端测部署可能，可在云端做SAM3 Agent提升慢环大模型检测精度**

---
**FallBack：** YOLO-World 或 MobileSAM

**接口形式**
1. Meta官方：sam3库/transformer库
2. ultralytics：更友好，ultralytics库集成

**输入输出示例**

文本-图像推理
```python
from ultralytics.models.sam import SAM3SemanticPredictor

# Initialize predictor with configuration
overrides = dict(
    conf=0.25,
    task="segment",
    mode="predict",
    model="SAM\\sam3.pt",
    half=False,  # Use FP16 for faster inference
    save=True,
)
predictor = SAM3SemanticPredictor(overrides=overrides)

# Set image once for multiple queries
predictor.set_image("path/to/image.jpg")

# Query with multiple text prompts
results = predictor(text=["person", "bus", "glasses"])

# Works with descriptive phrases
results = predictor(text=["person with red cloth", "person with blue cloth"])

# Query with a single concept
results = predictor(text=["a person"])
```

每个 `Results` 对象包含以下属性：

| 属性名 | 类型 | 描述 |
|--------|------|------|
| `orig_img` | `numpy.ndarray` | 原始输入图像（BGR格式） |
| `masks` | `torch.Tensor` 或 `None` | **二进制掩码**，形状为 `(1, H, W)` |
| `boxes` | `torch.Tensor` 或 `None` | 检测框，格式 `[x1, y1, x2, y2]` |
| `keypoints` | `torch.Tensor` 或 `None` | 关键点（如适用） |
| `names` | `dict` | 类别名称映射 |
| `speed` | `dict` | 预处理、推理、后处理时间 |

在9400F CPU单提示推理耗时827ms，这意味着端侧性能不可接受，
但如果利用GPU，推理耗时能降至50ms以内，有在云侧部署的可能

示例样本-图像分割
```python
from ultralytics.models.sam import SAM3SemanticPredictor

# Initialize predictor
overrides = dict(conf=0.25, task="segment", mode="predict", model="sam3.pt", half=True, save=True)
predictor = SAM3SemanticPredictor(overrides=overrides)

# Set image
predictor.set_image("path/to/image.jpg")

# Provide bounding box examples to segment similar objects
results = predictor(bboxes=[[480.0, 290.0, 590.0, 650.0]])

# Multiple bounding boxes for different concepts
results = predictor(bboxes=[[539, 599, 589, 639], [343, 267, 499, 662]])
```
文本+视频-物体实时追踪
```python
from ultralytics.models.sam import SAM3VideoSemanticPredictor

# Initialize semantic video predictor
overrides = dict(conf=0.25, task="segment", mode="predict", imgsz=640, model="SAM\\sam3.pt", half=True, save=True)
predictor = SAM3VideoSemanticPredictor(overrides=overrides)

# Track concepts using text prompts
results = predictor(source="Target.mp4", text=["person", "bicycle"], stream=True)

# Process results
for r in results:
    r.show()  # Display frame with tracked objects


