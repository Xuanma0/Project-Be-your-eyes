## MediaPipe 落地简报
### 特点
1. 良好CPU优化
2. 提供丰富预训练模型

### 缺点：
1. Android开发深度绑定Android Studio，在unity项目中难以直接集成
2. GPU部署有一定困难，而NPU部署几乎不可能
3. 模型使用tensorflow训练，与我们常用框架Pytorch区别大，开发有困难

### 重要坑点
1. 新版本API改动较大，导致AI给的代码完全无法使用，大部分情况下AI也无法顺利自我纠错

### 最终建议
1. 改用ExecuTorch，对各类GPU、NPU支持都比较完善，同时可以在Pytorch体系下快速导出
