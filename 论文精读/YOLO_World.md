## YOLO_World落地简报
### 两篇差异

文本一和文本二重叠内容仅措辞有调整，其余无变化，除此之外，文本二包含更多实验相关具体内容

### 端侧部署

直接用ultralytics官方量化代码即可导出为execttorch，运行于高通NPU上
https://docs.ultralytics.com/zh/integrations/executorch/

性能预估可以做到30ms以内

### 效果与性能
1. 实测预训练模型效果极差，无法实现论文中所说的任意物品检测，依赖训练数据。在圣诞树的图片中，无论是s还是x模型，均检测不出任何内容
2. 性能较好，与普通YOLO模型相当，但不提供nano版本，最低small。未优化9400F CPU实测120ms左右

### 代码

```python
from ultralytics import YOLOWorld

# Initialize a YOLO-World model
model = YOLOWorld("yolov8x-worldv2.pt")  # or select yolov8m/l-world.pt for different sizes

# Define custom classes (text prompts)
model.set_classes(["cat", "dog", "car"])

# Execute inference with the YOLOv8s-world model on the specified image
results = model.predict("bus.jpg")

#Show results
results[0].show()
```

### 风险
可能达不到预期效果

### FallBack
回退到传统YOLO模型，预训练词表