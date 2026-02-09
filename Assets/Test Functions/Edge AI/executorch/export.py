from ultralytics import YOLO # type: ignore

def export_model():
    # 加载模型
    model = YOLO("yolo26n.pt")
    # 导出模型为 ONNX 格式
    model.export(format="executorch", name="Assets\\Test Functions\\Edge AI\\executorch\\yolo26n.pte")
    print("Model exported successfully as yolo26n.pte")

def refer_run():
    # 加载模型
    model = YOLO("yolo26n.pt")
    # 执行推理
    source = "Assets\\Test Functions\\Edge AI\\executorch\\bus.jpg"
    results = model.predict(source)
    # 处理结果
    print("refer_run successfully executed.")


if __name__ == "__main__":
    refer_run()
    export_model()