import os
import sys
from pathlib import Path

# 添加当前目录到路径，以便导入ultralytics
current_dir = Path(__file__).parent
project_root = current_dir.parent.parent.parent  # 假设脚本在Assets/Demo/UnitySentis
sys.path.insert(0, str(project_root))

from ultralytics import YOLO

def main():
    # 路径配置
    model_dir = current_dir / "model"
    model_dir.mkdir(exist_ok=True)

    # 输入模型路径（项目根目录下的yolo26n.pt）
    input_model = project_root / "yolo26n.pt"
    if not input_model.exists():
        print(f"错误：找不到输入模型 {input_model}")
        sys.exit(1)

    # 输出模型路径（不含扩展名，export方法会自动添加.onnx）
    output_model = model_dir / "yolo26n"

    print(f"加载模型: {input_model}")
    model = YOLO(str(input_model))

    print("导出模型为ONNX格式...")
    # 导出参数：格式为onnx，输入尺寸640，opset版本12（兼容性）
    # 使用name参数直接指定输出路径（不含扩展名）
    model.export(
        format='onnx',
        imgsz=640,
        opset=12,
        simplify=True,
        dynamic=False,  # 固定尺寸，提高性能
        half=False,     # FP32精度
        device='cpu',   # 在CPU上导出
        name=str(output_model)  # 直接指定输出路径
    )

    # 检查导出结果
    expected_file = output_model.with_suffix('.onnx')
    if expected_file.exists():
        print(f"模型已导出到: {expected_file}")
    else:
        print("错误：导出失败，未找到生成的ONNX文件")
        sys.exit(1)

if __name__ == "__main__":
    main()