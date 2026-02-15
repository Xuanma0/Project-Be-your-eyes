using UnityEngine;
using Unity.InferenceEngine;
using System.Collections.Generic;
using System.Linq;
using UnityEngine.UI;

namespace Demo.UnitySentis
{
    /// <summary>
    /// YOLO26n ONNX模型推理演示脚本
    /// 使用Unity Inference Engine运行YOLO26n目标检测模型
    /// </summary>
    public class InferDemo : MonoBehaviour
    {
        [Header("模型设置")]
        [Tooltip("YOLO26n ONNX模型文件")]
        public ModelAsset modelAsset;
        
        [Header("输入设置")]
        [Tooltip("用于推理的输入图像")]
        public Texture2D inputTexture;
        [Tooltip("输入图像尺寸（YOLO26n标准输入为640x640）")]
        public Vector2Int inputSize = new Vector2Int(640, 640);
        
        [Header("显示设置")]
        [Tooltip("用于显示输入图像的RawImage组件")]
        public RawImage inputDisplay;
        [Tooltip("用于显示检测结果的RawImage组件")]
        public RawImage resultDisplay;
        
        [Header("检测设置")]
        [Tooltip("置信度阈值（低于此值的检测将被忽略）")]
        [Range(0f, 1f)]
        public float confidenceThreshold = 0.25f;
        [Tooltip("IoU阈值（用于非极大值抑制）")]
        [Range(0f, 1f)]
        public float iouThreshold = 0.45f;
        
        // Sentis组件
        private Model m_Model;
        private Worker m_Worker;
        
        // COCO数据集类别名称（80个类别）
        private static readonly string[] COCO_CLASS_NAMES = {
            "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
            "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
            "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
            "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
            "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
            "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
            "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
            "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
            "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
            "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush"
        };
        
        // 检测结果结构体
        private struct DetectionResult
        {
            public Rect rect;
            public float confidence;
            public int classId;
            public string className;
        }
        
        private void Start()
        {
            // 检查必需组件
            if (modelAsset == null)
            {
                Debug.LogError("请指定YOLO26n ONNX模型文件");
                return;
            }
            
            if (inputTexture == null)
            {
                Debug.LogError("请指定输入图像");
                return;
            }
            
            // 初始化Sentis推理引擎
            InitializeSentis();
            
            // 显示输入图像
            if (inputDisplay != null)
            {
                inputDisplay.texture = inputTexture;
            }
            RunInference();
        }
        
        /// <summary>
        /// 初始化Sentis推理引擎
        /// </summary>
        private void InitializeSentis()
        {
            // 从ModelAsset加载模型
            m_Model = ModelLoader.Load(modelAsset);

            // 创建推理工作器，优先使用GPU加速
            try
            {
                // 尝试使用GPUCompute后端
                m_Worker = new Worker(m_Model, BackendType.GPUCompute);
                Debug.Log("使用GPU加速进行推理");
            }
            catch (System.Exception)
            {
                // 如果GPU不可用，回退到CPU
                m_Worker = new Worker(m_Model, BackendType.CPU);
                Debug.Log("GPU加速不可用，使用CPU进行推理");
            }

            Debug.Log($"Sentis推理引擎初始化完成。模型输入形状: {GetModelInputShape()}");
        }
        
        /// <summary>
        /// 获取模型输入形状
        /// </summary>
        private string GetModelInputShape()
        {
            if (m_Model == null || m_Model.inputs.Count == 0)
                return "未知";
            
            var input = m_Model.inputs[0];
            return string.Join("x", input.shape);
        }
        
        /// <summary>
        /// 运行推理（可由UI按钮调用）
        /// </summary>
        public void RunInference()
        {
            if (m_Worker == null)
            {
                Debug.LogError("推理引擎未初始化");
                return;
            }

            // 1. 预处理输入图像
            Tensor<float> inputTensor = PreprocessImage(inputTexture);

            // 2. 执行推理
            Debug.Log("开始推理...");
            //启用计时
            System.Diagnostics.Stopwatch stopwatch = new System.Diagnostics.Stopwatch();
            stopwatch.Start();
            using (inputTensor)
            {
                // 设置输入并执行推理
                m_Worker.SetInput(0, inputTensor);
                m_Worker.Schedule();

                // 3. 获取输出
                Tensor outputTensor = m_Worker.PeekOutput();
                
                // 确保输出张量数据就绪
                outputTensor.CompleteAllPendingOperations();
                
                Tensor<float> floatOutputTensor = outputTensor as Tensor<float>;

                if (floatOutputTensor == null)
                {
                    Debug.LogError($"输出张量类型错误: {outputTensor?.GetType().Name}");
                    return;
                }

                // 4. 后处理输出（解析YOLO输出）
                List<DetectionResult> detections = PostprocessOutput(floatOutputTensor);

                // 5. 可视化结果
                VisualizeDetections(detections);

                Debug.Log($"检测到 {detections.Count} 个对象，耗时: {stopwatch.ElapsedMilliseconds} 毫秒");
            }
        }
        
        /// <summary>
        /// 预处理图像：调整大小、归一化、转换为张量
        /// </summary>
        private Tensor<float> PreprocessImage(Texture2D texture)
        {
            // 调整图像大小到模型输入尺寸
            RenderTexture resizedRT = RenderTexture.GetTemporary(inputSize.x, inputSize.y, 0);
            Graphics.Blit(texture, resizedRT);

            // 创建输入张量形状: [batch=1, channels=3, height=640, width=640]
            TensorShape inputShape = new TensorShape(1, 3, inputSize.y, inputSize.x);
            Tensor<float> tensor = new Tensor<float>(inputShape);

            // 将纹理转换为张量
            TextureConverter.ToTensor(resizedRT, tensor);

            // 释放临时RenderTexture
            RenderTexture.ReleaseTemporary(resizedRT);

            // YOLO模型通常需要归一化到0-1范围
            // TextureConverter.ToTensor 已经处理了归一化
            // 注意：某些YOLO模型可能需要不同的归一化方式
            // 例如：(image / 255.0f).ToTensor() 或使用均值和标准差

            return tensor;
        }
        
        /// <summary>
        /// 后处理YOLO输出
        /// </summary>
        private List<DetectionResult> PostprocessOutput(Tensor<float> outputTensor)
        {
            List<DetectionResult> detections = new List<DetectionResult>();

            // 获取输出数据
            TensorShape shape = outputTensor.shape;
            float[] data = outputTensor.DownloadToArray();

            Debug.Log($"输出形状: {shape}, 数据长度: {data.Length}");
            
            // YOLO26n端到端输出格式解析
            // YOLO26n是端到端模型，不需要NMS，输出格式为:
            // [batch_size, num_detections, 85]
            // 其中85 = [x, y, w, h, confidence, class_scores...]
            
            // 解析检测结果
            int numDetections = shape[1];
            int featuresPerDetection = shape[2];
            
            for (int i = 0; i < numDetections; i++)
            {
                int baseIndex = i * featuresPerDetection;
                
                // 获取边界框信息
                float centerX = data[baseIndex + 0];
                float centerY = data[baseIndex + 1];
                float width = data[baseIndex + 2];
                float height = data[baseIndex + 3];
                float confidence = data[baseIndex + 4];
                
                // 如果置信度低于阈值，跳过
                if (confidence < confidenceThreshold)
                    continue;
                
                // 找到类别分数最高的类别
                int classId = -1;
                float maxClassScore = 0f;
                
                // 从第5个元素开始是类别分数
                for (int c = 0; c < 80; c++) // COCO有80个类别
                {
                    float classScore = data[baseIndex + 5 + c];
                    if (classScore > maxClassScore)
                    {
                        maxClassScore = classScore;
                        classId = c;
                    }
                }
                
                // 最终置信度 = 框置信度 * 类别置信度
                float finalConfidence = confidence * maxClassScore;
                
                // 转换为Unity坐标（0-1范围）
                float x = centerX - width / 2f;
                float y = 1.0f - (centerY + height / 2f); // 反转Y轴
                Rect rect = new Rect(x, y, width, height);
                
                // 添加到结果列表
                detections.Add(new DetectionResult
                {
                    rect = rect,
                    confidence = finalConfidence,
                    classId = classId,
                    className = classId < COCO_CLASS_NAMES.Length ? COCO_CLASS_NAMES[classId] : $"Class_{classId}"
                });
            }
            
            // 按置信度排序
            detections = detections.OrderByDescending(d => d.confidence).ToList();
            
            return detections;
        }
        
        /// <summary>
        /// 可视化检测结果
        /// </summary>
        private void VisualizeDetections(List<DetectionResult> detections)
        {
            if (resultDisplay == null || inputTexture == null)
                return;
            
            // 创建结果纹理副本
            Texture2D resultTexture = new Texture2D(inputTexture.width, inputTexture.height);
            Graphics.CopyTexture(inputTexture, resultTexture);
            
            // 绘制边界框和标签
            foreach (var detection in detections)
            {
                // 将归一化坐标转换为像素坐标
                int x = Mathf.RoundToInt(detection.rect.x * inputTexture.width);
                int y = Mathf.RoundToInt(detection.rect.y * inputTexture.height);
                int width = Mathf.RoundToInt(detection.rect.width * inputTexture.width);
                int height = Mathf.RoundToInt(detection.rect.height * inputTexture.height);
                
                // 绘制边界框
                DrawBox(resultTexture, x, y, width, height, Color.green, 3);
                
                // 绘制标签
                string label = $"{detection.className}: {detection.confidence:F2}";
                // 注意：在实际应用中，你可能需要使用GUI或UI.Text组件来绘制文本
                // 这里只是简化示例
            }
            
            resultTexture.Apply();
            resultDisplay.texture = resultTexture;
        }
        
        /// <summary>
        /// 在纹理上绘制边界框
        /// </summary>
        private void DrawBox(Texture2D texture, int x, int y, int width, int height, Color color, int thickness)
        {
            // 绘制上边框
            for (int i = 0; i < thickness; i++)
            {
                for (int j = 0; j < width; j++)
                {
                    texture.SetPixel(x + j, y + i, color);
                }
            }
            
            // 绘制下边框
            for (int i = 0; i < thickness; i++)
            {
                for (int j = 0; j < width; j++)
                {
                    texture.SetPixel(x + j, y + height - i - 1, color);
                }
            }
            
            // 绘制左边框
            for (int i = 0; i < thickness; i++)
            {
                for (int j = 0; j < height; j++)
                {
                    texture.SetPixel(x + i, y + j, color);
                }
            }
            
            // 绘制右边框
            for (int i = 0; i < thickness; i++)
            {
                for (int j = 0; j < height; j++)
                {
                    texture.SetPixel(x + width - i - 1, y + j, color);
                }
            }
        }
        
        /// <summary>
        /// 加载新图像并运行推理
        /// </summary>
        public void LoadAndInference(Texture2D newTexture)
        {
            if (newTexture == null)
                return;
            
            inputTexture = newTexture;
            
            if (inputDisplay != null)
            {
                inputDisplay.texture = inputTexture;
            }
            
            RunInference();
        }
        
        /// <summary>
        /// 清理资源
        /// </summary>
        private void OnDestroy()
        {
            m_Worker?.Dispose();
            Debug.Log("Sentis推理引擎已清理");
        }
        
        /// <summary>
        /// 获取模型信息（可用于调试）
        /// </summary>
        public string GetModelInfo()
        {
            if (m_Model == null)
                return "模型未加载";

            string info = "模型信息:\n";
            info += $"输入数量: {m_Model.inputs.Count}\n";
            info += $"输出数量: {m_Model.outputs.Count}\n";

            foreach (var input in m_Model.inputs)
            {
                info += $"输入: {input.name}, 形状: {string.Join("x", input.shape)}\n";
            }

            foreach (var output in m_Model.outputs)
            {
                info += $"输出: {output.name}, 索引: {output.index}\n";
            }

            return info;
        }
    }
}