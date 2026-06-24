# Be Your Eyes Evaluation

这个评测系统用于回答一个问题：每次改模型或规则后，系统到底是变强了，还是只是看起来变强了。

它不训练模型，只把同一批图片/视频离线回放给当前工具链，并输出 `CSV / JSON / HTML` 报告。2080Ti 足够使用。

## 1. 录制样本

每个样本建议 10-20 秒，任务单一，画面尽量像真实使用场景。

```powershell
cd D:\Be-your-eyes
.\.venv\Scripts\python.exe scripts\eval_toolchain.py record `
  --out data\eval\media\red_can_reach_001.mp4 `
  --seconds 15 `
  --camera 0 `
  --fps 20
```

建议先录这些任务：

- 找红色罐子
- 引导手拿起红色罐子
- 找绿色罐子
- 读书名
- 找手机/钥匙/杯子
- 判断前方是否安全

## 2. 生成标注清单

```powershell
.\.venv\Scripts\python.exe scripts\eval_toolchain.py init `
  --media-dir data\eval\media `
  --out data\eval\manifest.jsonl `
  --question "引导我的手拿起红色罐子" `
  --mode auto_assist `
  --sample-fps 2
```

然后打开 `data\eval\manifest.jsonl`，把 `expect` 改成真实标签。一个样例如下：

```json
{
  "id": "red_can_reach_001",
  "media": "media/red_can_reach_001.mp4",
  "question": "引导我的手拿起红色罐子",
  "mode": "auto_assist",
  "sample_fps": 2,
  "expect": {
    "target": {"present": true, "label": "can", "color": "red", "position": "center"},
    "hand": {"present": true},
    "safety": {"blocking": false},
    "final_phases": ["close_fingers", "hold", "lift"],
    "speech_contains": [],
    "speech_avoids": []
  }
}
```

`position` 可以写 `left / center / right / top / bottom`，也可以写中文如 `左侧`、`右下方`、`正前方`。

## 3. 跑完整系统

```powershell
.\.venv\Scripts\python.exe scripts\eval_toolchain.py run `
  --manifest data\eval\manifest.jsonl `
  --out data\eval\runs\full `
  --variant full `
  --max-frames 30 `
  --save-annotated
```

输出文件：

- `frames.jsonl`：每帧的证据、回答、阶段、延迟
- `samples.csv`：每个样本的指标
- `summary.json`：总体分数
- `report.html`：可视化报告
- `annotated/`：可选，保存标注帧

## 4. 跑消融对比

关掉智能体，只看工具链一帧回答能力：

```powershell
.\.venv\Scripts\python.exe scripts\eval_toolchain.py run `
  --manifest data\eval\manifest.jsonl `
  --out data\eval\runs\no_agent `
  --variant no_agent `
  --max-frames 30
```

只跑检测和安全：

```powershell
.\.venv\Scripts\python.exe scripts\eval_toolchain.py run `
  --manifest data\eval\manifest.jsonl `
  --out data\eval\runs\detect_only `
  --variant detect_only `
  --max-frames 30
```

对论文最有用的是比较：

- `full` vs `no_agent`
- `full` vs `detect_only`
- `full` vs 线上 VLM 抽帧 baseline

## 5. 小自检

生成一个合成图片和 demo manifest：

```powershell
.\.venv\Scripts\python.exe scripts\eval_toolchain.py demo --out data\eval\demo
```

直接跑 demo：

```powershell
.\.venv\Scripts\python.exe scripts\eval_toolchain.py demo --out data\eval\demo --run --variant full
```

合成图只是检查评测管线能否工作，不代表真实精度。
