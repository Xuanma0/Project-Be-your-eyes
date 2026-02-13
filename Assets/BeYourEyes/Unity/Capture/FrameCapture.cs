using System;
using System.Collections;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Object = UnityEngine.Object;
using BeYourEyes.Unity.Interaction;

namespace BeYourEyes.Unity.Capture
{
    public sealed class FrameCapture : MonoBehaviour
    {
        public readonly struct ForceWindowResult
        {
            public ForceWindowResult(bool completed, string reason, long startedAtMs, long endedAtMs, int targetFrames, int sentFrames)
            {
                Completed = completed;
                Reason = string.IsNullOrWhiteSpace(reason) ? "unknown" : reason;
                StartedAtMs = startedAtMs;
                EndedAtMs = endedAtMs;
                TargetFrames = targetFrames;
                SentFrames = sentFrames;
            }

            public bool Completed { get; }
            public string Reason { get; }
            public long StartedAtMs { get; }
            public long EndedAtMs { get; }
            public int TargetFrames { get; }
            public int SentFrames { get; }
        }

        public readonly struct FrameAcceptedInfo
        {
            public FrameAcceptedInfo(long seq, long timestampMs, byte[] jpgBytes, int width, int height, bool roiApplied, string keyframeReason, string metaJson)
            {
                Seq = seq;
                TimestampMs = timestampMs;
                JpgBytes = jpgBytes;
                Width = width;
                Height = height;
                RoiApplied = roiApplied;
                KeyframeReason = keyframeReason;
                MetaJson = metaJson;
            }

            public long Seq { get; }
            public long TimestampMs { get; }
            public byte[] JpgBytes { get; }
            public int Width { get; }
            public int Height { get; }
            public bool RoiApplied { get; }
            public string KeyframeReason { get; }
            public string MetaJson { get; }
        }

        [SerializeField] private Camera captureCamera;
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;
        [SerializeField] private int captureWidth = 640;
        [SerializeField] private int captureHeight = 360;

        [Header("Adaptive Policy")]
        [SerializeField] private int normalFps = 5;
        [SerializeField] private int degradedFps = 3;
        [SerializeField] private int throttledFps = 1;
        [SerializeField] private int safeModeFps = 1;
        [SerializeField, Range(1, 100)] private int normalJpegQuality = 70;
        [SerializeField, Range(1, 100)] private int degradedJpegQuality = 60;
        [SerializeField, Range(1, 100)] private int throttledJpegQuality = 50;
        [SerializeField, Range(1, 100)] private int safeModeJpegQuality = 40;
        [SerializeField] private int ttlMs = 3000;

        [Header("Keyframe")]
        [SerializeField] private KeyframeSelector keyframeSelector = new KeyframeSelector();

        [Header("Backpressure")]
        [SerializeField] private int busyDropThreshold = 8;
        [SerializeField, Range(0.2f, 1f)] private float busyDropFpsScale = 0.5f;
        [SerializeField] private bool includePose = true;
        [SerializeField] private bool autoStart = true;

        [Header("Scan Text ROI")]
        [SerializeField] private bool enableScanTextRoi = true;
        [SerializeField, Range(0.2f, 0.9f)] private float scanTextRoiWidthRatio = 0.5f;
        [SerializeField, Range(0.2f, 0.9f)] private float scanTextRoiHeightRatio = 0.5f;
        [SerializeField, Range(1, 100)] private int scanTextRoiMinQuality = 75;
        [SerializeField, Range(1, 100)] private int safeModeScanTextRoiQuality = 60;
        [SerializeField] private int scanTextStreamMinIntervalMs = 200;
        [SerializeField] private int limitedModeMinIntervalMs = 1500;
        [SerializeField] private int limitedModeQualityDrop = 10;

        private readonly WaitForEndOfFrame waitForEndOfFrame = new WaitForEndOfFrame();
        private Coroutine captureRoutine;
        private int frameSeq;
        private int consecutiveBusyDrops;

        private RenderTexture captureRt;
        private Texture2D fullTexture;
        private Texture2D roiTexture;
        private int rtWidth;
        private int rtHeight;

        private long framesCaptured;
        private long framesSent;
        private long framesDroppedBusy;
        private long framesDroppedNoConn;
        private long totalBytesSent;
        private double bytesEma = -1;
        private const double BytesEmaAlpha = 0.2;
        private string lastKeyframeReason = "-";
        private long lastFallbackAttemptAtMs = -1;
        private long lastScanTextSentAtMs = -1;
        private long lastLimitedSentAtMs = -1;
        private bool forceWindowActive;
        private long forceWindowStartedAtMs = -1;
        private long forceWindowEndAtMs = -1;
        private long forceWindowLastSendAttemptMs = -1;
        private int forceWindowTargetFrames;
        private int forceWindowMinIntervalMs = 120;
        private long forceWindowSentAtStart;

        public long FramesCaptured => framesCaptured;
        public long FramesSent => framesSent;
        public long FramesDroppedBusy => framesDroppedBusy;
        public long FramesDroppedNoConn => framesDroppedNoConn;
        public long TotalBytesSent => totalBytesSent;
        public double BytesEma => bytesEma;
        public string LastKeyframeReason => lastKeyframeReason;
        public bool IsForceWindowActive => forceWindowActive;
        public long ForceWindowStartedAtMs => forceWindowStartedAtMs;
        public long ForceWindowEndAtMs => forceWindowEndAtMs;
        public int ForceWindowTargetFrames => forceWindowTargetFrames;
        public int ForceWindowSentFrames => forceWindowStartedAtMs > 0 ? Math.Max(0, (int)(framesSent - forceWindowSentAtStart)) : 0;
        public event Action<FrameAcceptedInfo> OnFrameAccepted;
        public event Action<ForceWindowResult> OnForceWindowCompleted;

        private void OnEnable()
        {
            if (autoStart)
            {
                StartCapture();
            }
        }

        private void OnDisable()
        {
            if (forceWindowActive)
            {
                CompleteForceWindow(false, "disabled", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            }
            StopCapture();
            ReleaseCaptureResources();
            keyframeSelector?.ResetRuntime();
        }

        public void StartCapture()
        {
            if (captureRoutine != null)
            {
                return;
            }

            captureRoutine = StartCoroutine(CaptureLoop());
            Debug.Log("[FrameCapture] started");
        }

        public void StopCapture()
        {
            if (captureRoutine == null)
            {
                return;
            }

            StopCoroutine(captureRoutine);
            captureRoutine = null;
            Debug.Log("[FrameCapture] stopped");
        }

        public bool ForceCaptureWindow(float durationSec, int maxFrames, int minIntervalMs, out string reason)
        {
            if (durationSec <= 0f && maxFrames <= 0)
            {
                reason = "invalid_window";
                return false;
            }

            if (captureRoutine == null)
            {
                StartCapture();
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            forceWindowActive = true;
            forceWindowStartedAtMs = nowMs;
            forceWindowEndAtMs = nowMs + (long)(Mathf.Max(0.1f, durationSec) * 1000f);
            forceWindowTargetFrames = Math.Max(0, maxFrames);
            forceWindowMinIntervalMs = Math.Max(50, minIntervalMs);
            forceWindowLastSendAttemptMs = -1;
            forceWindowSentAtStart = framesSent;
            lastKeyframeReason = "force_window_start";
            reason = "ok";
            return true;
        }

        public void CancelForceCaptureWindow(string reason = "manual_cancel")
        {
            if (!forceWindowActive)
            {
                return;
            }

            CompleteForceWindow(false, reason, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        }

        private IEnumerator CaptureLoop()
        {
            while (true)
            {
                yield return waitForEndOfFrame;
                CaptureAndSendOnce();

                var policy = ResolvePolicy();
                var fps = Mathf.Max(0.5f, policy.fps * ResolveBusyScale());
                yield return new WaitForSeconds(1f / fps);
            }
        }

        private void CaptureAndSendOnce()
        {
            framesCaptured++;
            var cameraToUse = captureCamera != null ? captureCamera : Camera.main;
            if (cameraToUse == null)
            {
                Debug.LogWarning("[FrameCapture] no camera available");
                return;
            }

            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<BeYourEyes.Adapters.Networking.GatewayClient>();
                if (gatewayClient == null)
                {
                    Debug.LogWarning("[FrameCapture] no GatewayClient found");
                    return;
                }
            }

            if (gatewayClient.IsReplayMode)
            {
                lastKeyframeReason = "replay_mode_pause";
                return;
            }

            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (!AllowByFallback(nowMs))
            {
                return;
            }

            if (forceWindowActive && nowMs >= forceWindowEndAtMs)
            {
                CompleteForceWindow(false, "timeout", nowMs);
                return;
            }

            var policy = ResolvePolicy();
            var healthStatus = ResolveHealthStatus();
            var pose = cameraToUse.transform;
            var useScanTextRoi = ShouldUseScanTextRoi();
            KeyframeDecision decision;
            if (forceWindowActive)
            {
                if (forceWindowLastSendAttemptMs > 0 && nowMs - forceWindowLastSendAttemptMs < forceWindowMinIntervalMs)
                {
                    lastKeyframeReason = "force_min_interval";
                    return;
                }
                forceWindowLastSendAttemptMs = nowMs;
                decision = new KeyframeDecision(true, "force_window");
            }
            else if (useScanTextRoi)
            {
                var minInterval = Math.Max(50, scanTextStreamMinIntervalMs);
                if (lastScanTextSentAtMs > 0 && nowMs - lastScanTextSentAtMs < minInterval)
                {
                    lastKeyframeReason = "scan_text_min_interval";
                    return;
                }
                decision = new KeyframeDecision(true, "scan_text_stream");
            }
            else
            {
                decision = keyframeSelector.Evaluate(nowMs, pose.position, pose.rotation, healthStatus, consecutiveBusyDrops);
                if (!decision.ShouldSend)
                {
                    lastKeyframeReason = decision.Reason;
                    return;
                }
            }
            lastKeyframeReason = decision.Reason;

            var capabilityState = gatewayClient.CurrentCapabilityState;
            if (!forceWindowActive && capabilityState == BeYourEyes.Adapters.Networking.CapabilityState.LIMITED_NOT_READY)
            {
                var limitedMin = Math.Max(200, limitedModeMinIntervalMs);
                if (lastLimitedSentAtMs > 0 && nowMs - lastLimitedSentAtMs < limitedMin)
                {
                    lastKeyframeReason = "limited_low_rate_guard";
                    return;
                }
            }

            var effectiveQuality = policy.jpegQuality;
            if (capabilityState == BeYourEyes.Adapters.Networking.CapabilityState.LIMITED_NOT_READY)
            {
                effectiveQuality = Mathf.Clamp(effectiveQuality - Math.Max(0, limitedModeQualityDrop), 1, 100);
            }
            if (useScanTextRoi)
            {
                var minRoiQuality = string.Equals(healthStatus, "SAFE_MODE", StringComparison.OrdinalIgnoreCase)
                    ? safeModeScanTextRoiQuality
                    : scanTextRoiMinQuality;
                effectiveQuality = Mathf.Max(effectiveQuality, Mathf.Clamp(minRoiQuality, 1, 100));
            }

            var capture = CaptureCameraJpg(cameraToUse, captureWidth, captureHeight, effectiveQuality, useScanTextRoi);
            if (capture.bytes == null || capture.bytes.Length == 0)
            {
                Debug.LogWarning("[FrameCapture] failed to capture jpg");
                return;
            }

            frameSeq++;
            var meta = BuildMeta(cameraToUse, nowMs, policy.ttlMs, capture, decision.Reason);
            var metaJson = meta.ToString(Formatting.None);
            if (capabilityState == BeYourEyes.Adapters.Networking.CapabilityState.OFFLINE)
            {
                framesDroppedNoConn++;
                lastKeyframeReason = "offline_pause_upload";
                consecutiveBusyDrops = 0;
                return;
            }

            var result = gatewayClient.TrySendFrameDetailed(capture.bytes, metaJson, frameSeq, nowMs);
            switch (result)
            {
                case BeYourEyes.Adapters.Networking.FrameSendResult.Accepted:
                    framesSent++;
                    totalBytesSent += capture.bytes.Length;
                    UpdateBytesEma(capture.bytes.Length);
                    consecutiveBusyDrops = 0;
                    keyframeSelector.NotifySendSucceeded(nowMs, pose.position, pose.rotation);
                    if (useScanTextRoi)
                    {
                        lastScanTextSentAtMs = nowMs;
                    }
                    if (capabilityState == BeYourEyes.Adapters.Networking.CapabilityState.LIMITED_NOT_READY)
                    {
                        lastLimitedSentAtMs = nowMs;
                    }
                    OnFrameAccepted?.Invoke(new FrameAcceptedInfo(
                        frameSeq,
                        nowMs,
                        capture.bytes,
                        capture.outputWidth,
                        capture.outputHeight,
                        capture.usedRoi,
                        decision.Reason,
                        metaJson
                    ));
                    if (forceWindowActive && forceWindowTargetFrames > 0 && ForceWindowSentFrames >= forceWindowTargetFrames)
                    {
                        CompleteForceWindow(true, "max_frames", nowMs);
                    }
                    break;
                case BeYourEyes.Adapters.Networking.FrameSendResult.DroppedBusy:
                    framesDroppedBusy++;
                    consecutiveBusyDrops++;
                    break;
                case BeYourEyes.Adapters.Networking.FrameSendResult.DroppedNoConnection:
                    framesDroppedNoConn++;
                    consecutiveBusyDrops = 0;
                    break;
                default:
                    consecutiveBusyDrops = 0;
                    break;
            }
        }

        private bool AllowByFallback(long nowMs)
        {
            if (localSafetyFallback == null || localSafetyFallback.IsOk)
            {
                return true;
            }

            if (localSafetyFallback.CaptureMode == FallbackCaptureMode.Pause)
            {
                lastKeyframeReason = "fallback_pause";
                return false;
            }

            var minIntervalMs = Math.Max(200, localSafetyFallback.FallbackMinIntervalMs);
            if (lastFallbackAttemptAtMs > 0 && nowMs - lastFallbackAttemptAtMs < minIntervalMs)
            {
                lastKeyframeReason = "fallback_lowrate_wait";
                return false;
            }

            lastFallbackAttemptAtMs = nowMs;
            return true;
        }

        private JObject BuildMeta(Camera cameraToUse, long nowMs, int effectiveTtlMs, CaptureResult capture, string keyReason)
        {
            var intrinsics = EstimateIntrinsics(cameraToUse, capture.sourceWidth, capture.sourceHeight, capture.cropRect);
            var meta = new JObject
            {
                ["sessionId"] = gatewayClient != null ? gatewayClient.SessionId : "default",
                ["seq"] = frameSeq,
                ["timestampMs"] = nowMs,
                ["tsCaptureMs"] = nowMs,
                ["ttlMs"] = Mathf.Max(200, effectiveTtlMs),
                ["width"] = capture.outputWidth,
                ["height"] = capture.outputHeight,
                ["coordFrame"] = "World",
                ["source"] = "unity_skeleton",
                ["intrinsics"] = intrinsics,
                ["keyframeReason"] = string.IsNullOrWhiteSpace(keyReason) ? "unknown" : keyReason,
                ["roiApplied"] = capture.usedRoi,
            };

            if (includePose)
            {
                var t = cameraToUse.transform;
                meta["pose"] = new JObject
                {
                    ["position"] = new JObject
                    {
                        ["x"] = t.position.x,
                        ["y"] = t.position.y,
                        ["z"] = t.position.z,
                    },
                    ["rotation"] = new JObject
                    {
                        ["x"] = t.rotation.x,
                        ["y"] = t.rotation.y,
                        ["z"] = t.rotation.z,
                        ["w"] = t.rotation.w,
                    },
                };
            }

            return meta;
        }

        private float ResolveBusyScale()
        {
            if (consecutiveBusyDrops >= Mathf.Max(1, busyDropThreshold))
            {
                return Mathf.Clamp(busyDropFpsScale, 0.2f, 1f);
            }

            return 1f;
        }

        private CapturePolicy ResolvePolicy()
        {
            var status = ResolveHealthStatus();
            switch (status)
            {
                case "SAFE_MODE":
                    return new CapturePolicy(Mathf.Max(1, safeModeFps), Mathf.Clamp(safeModeJpegQuality, 1, 100), ttlMs);
                case "THROTTLED":
                    return new CapturePolicy(Mathf.Max(1, throttledFps), Mathf.Clamp(throttledJpegQuality, 1, 100), ttlMs);
                case "DEGRADED":
                    return new CapturePolicy(Mathf.Max(1, degradedFps), Mathf.Clamp(degradedJpegQuality, 1, 100), ttlMs);
                default:
                    return new CapturePolicy(Mathf.Max(1, normalFps), Mathf.Clamp(normalJpegQuality, 1, 100), ttlMs);
            }
        }

        private string ResolveHealthStatus()
        {
            return gatewayClient != null
                ? (gatewayClient.LastHealthStatus ?? string.Empty).Trim().ToUpperInvariant()
                : string.Empty;
        }

        public JObject BuildParameterSnapshot()
        {
            return new JObject
            {
                ["captureWidth"] = captureWidth,
                ["captureHeight"] = captureHeight,
                ["normalFps"] = normalFps,
                ["degradedFps"] = degradedFps,
                ["throttledFps"] = throttledFps,
                ["safeModeFps"] = safeModeFps,
                ["normalJpegQuality"] = normalJpegQuality,
                ["degradedJpegQuality"] = degradedJpegQuality,
                ["throttledJpegQuality"] = throttledJpegQuality,
                ["safeModeJpegQuality"] = safeModeJpegQuality,
                ["ttlMs"] = ttlMs,
                ["busyDropThreshold"] = busyDropThreshold,
                ["busyDropFpsScale"] = busyDropFpsScale,
                ["enableScanTextRoi"] = enableScanTextRoi,
                ["scanTextRoiWidthRatio"] = scanTextRoiWidthRatio,
                ["scanTextRoiHeightRatio"] = scanTextRoiHeightRatio,
                ["scanTextRoiMinQuality"] = scanTextRoiMinQuality,
                ["safeModeScanTextRoiQuality"] = safeModeScanTextRoiQuality,
                ["scanTextStreamMinIntervalMs"] = scanTextStreamMinIntervalMs,
                ["limitedModeMinIntervalMs"] = limitedModeMinIntervalMs,
                ["limitedModeQualityDrop"] = limitedModeQualityDrop,
                ["forceWindowMinIntervalMs"] = forceWindowMinIntervalMs,
                ["keyframe"] = new JObject
                {
                    ["normalMinIntervalMs"] = keyframeSelector != null ? keyframeSelector.NormalMinIntervalMs : 0,
                    ["normalMaxIntervalMs"] = keyframeSelector != null ? keyframeSelector.NormalMaxIntervalMs : 0,
                    ["throttledMinIntervalMs"] = keyframeSelector != null ? keyframeSelector.ThrottledMinIntervalMs : 0,
                    ["throttledMaxIntervalMs"] = keyframeSelector != null ? keyframeSelector.ThrottledMaxIntervalMs : 0,
                    ["degradedMinIntervalMs"] = keyframeSelector != null ? keyframeSelector.DegradedMinIntervalMs : 0,
                    ["degradedMaxIntervalMs"] = keyframeSelector != null ? keyframeSelector.DegradedMaxIntervalMs : 0,
                    ["safeModeMinIntervalMs"] = keyframeSelector != null ? keyframeSelector.SafeModeMinIntervalMs : 0,
                    ["safeModeMaxIntervalMs"] = keyframeSelector != null ? keyframeSelector.SafeModeMaxIntervalMs : 0,
                    ["angleThresholdDeg"] = keyframeSelector != null ? keyframeSelector.AngleThresholdDeg : 0f,
                    ["positionThresholdM"] = keyframeSelector != null ? keyframeSelector.PositionThresholdM : 0f,
                    ["busyDropStreakThreshold"] = keyframeSelector != null ? keyframeSelector.BusyDropStreakThreshold : 0,
                },
            };
        }

        private bool ShouldUseScanTextRoi()
        {
            if (!enableScanTextRoi || gatewayClient == null)
            {
                return false;
            }

            return string.Equals(gatewayClient.CurrentIntentKind, "scan_text", StringComparison.OrdinalIgnoreCase);
        }

        private void EnsureCaptureTargets(int width, int height)
        {
            var safeWidth = Mathf.Max(32, width);
            var safeHeight = Mathf.Max(32, height);
            if (captureRt == null || rtWidth != safeWidth || rtHeight != safeHeight)
            {
                ReleaseCaptureResources();
                captureRt = new RenderTexture(safeWidth, safeHeight, 24, RenderTextureFormat.ARGB32);
                captureRt.Create();
                rtWidth = safeWidth;
                rtHeight = safeHeight;
            }

            if (fullTexture == null || fullTexture.width != safeWidth || fullTexture.height != safeHeight)
            {
                if (fullTexture != null)
                {
                    Object.Destroy(fullTexture);
                }
                fullTexture = new Texture2D(safeWidth, safeHeight, TextureFormat.RGB24, false);
            }
        }

        private CaptureResult CaptureCameraJpg(Camera cameraToUse, int width, int height, int quality, bool useRoi)
        {
            var safeWidth = Mathf.Max(32, width);
            var safeHeight = Mathf.Max(32, height);
            var safeQuality = Mathf.Clamp(quality, 1, 100);

            var previousTarget = cameraToUse.targetTexture;
            var previousActive = RenderTexture.active;
            try
            {
                EnsureCaptureTargets(safeWidth, safeHeight);
                cameraToUse.targetTexture = captureRt;
                cameraToUse.Render();
                RenderTexture.active = captureRt;

                if (!useRoi)
                {
                    fullTexture.ReadPixels(new Rect(0f, 0f, safeWidth, safeHeight), 0, 0);
                    fullTexture.Apply(false, false);
                    var fullBytes = fullTexture.EncodeToJPG(safeQuality);
                    return new CaptureResult(fullBytes, safeWidth, safeHeight, safeWidth, safeHeight, new RectInt(0, 0, safeWidth, safeHeight), false);
                }

                var roiRect = ComputeCenterRoiRect(safeWidth, safeHeight);
                if (roiTexture == null || roiTexture.width != roiRect.width || roiTexture.height != roiRect.height)
                {
                    if (roiTexture != null)
                    {
                        Object.Destroy(roiTexture);
                    }
                    roiTexture = new Texture2D(roiRect.width, roiRect.height, TextureFormat.RGB24, false);
                }

                roiTexture.ReadPixels(new Rect(roiRect.x, roiRect.y, roiRect.width, roiRect.height), 0, 0);
                roiTexture.Apply(false, false);
                var roiBytes = roiTexture.EncodeToJPG(safeQuality);
                return new CaptureResult(roiBytes, roiRect.width, roiRect.height, safeWidth, safeHeight, roiRect, true);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[FrameCapture] capture exception: {ex.Message}");
                return default;
            }
            finally
            {
                cameraToUse.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
            }
        }

        private RectInt ComputeCenterRoiRect(int fullWidth, int fullHeight)
        {
            var roiWidth = Mathf.Clamp(Mathf.RoundToInt(fullWidth * Mathf.Clamp(scanTextRoiWidthRatio, 0.2f, 0.9f)), 32, fullWidth);
            var roiHeight = Mathf.Clamp(Mathf.RoundToInt(fullHeight * Mathf.Clamp(scanTextRoiHeightRatio, 0.2f, 0.9f)), 32, fullHeight);
            var x = Mathf.Max(0, (fullWidth - roiWidth) / 2);
            var y = Mathf.Max(0, (fullHeight - roiHeight) / 2);
            return new RectInt(x, y, roiWidth, roiHeight);
        }

        private static JObject EstimateIntrinsics(Camera cameraToUse, int sourceWidth, int sourceHeight, RectInt cropRect)
        {
            var fovYRad = cameraToUse.fieldOfView * Mathf.Deg2Rad;
            var fy = 0.5f * sourceHeight / Mathf.Tan(0.5f * Mathf.Max(0.01f, fovYRad));
            var fx = fy * (sourceWidth / Mathf.Max(1f, sourceHeight));
            var cx = sourceWidth * 0.5f;
            var cy = sourceHeight * 0.5f;

            var adjustedCx = cx - cropRect.x;
            var adjustedCy = cy - cropRect.y;
            return new JObject
            {
                ["fx"] = fx,
                ["fy"] = fy,
                ["cx"] = adjustedCx,
                ["cy"] = adjustedCy,
                ["width"] = cropRect.width,
                ["height"] = cropRect.height,
            };
        }

        private void UpdateBytesEma(int bytes)
        {
            if (bytes <= 0)
            {
                return;
            }

            if (bytesEma < 0)
            {
                bytesEma = bytes;
                return;
            }

            bytesEma = (BytesEmaAlpha * bytes) + ((1d - BytesEmaAlpha) * bytesEma);
        }

        private void CompleteForceWindow(bool completed, string reason, long endedAtMs)
        {
            if (!forceWindowActive)
            {
                return;
            }

            var startedAt = forceWindowStartedAtMs;
            var sentFrames = ForceWindowSentFrames;
            var targetFrames = forceWindowTargetFrames;

            forceWindowActive = false;
            forceWindowStartedAtMs = -1;
            forceWindowEndAtMs = -1;
            forceWindowLastSendAttemptMs = -1;
            forceWindowTargetFrames = 0;
            forceWindowSentAtStart = framesSent;

            lastKeyframeReason = $"force_window_end:{reason}";
            OnForceWindowCompleted?.Invoke(new ForceWindowResult(completed, reason, startedAt, endedAtMs, targetFrames, sentFrames));
        }

        private void ReleaseCaptureResources()
        {
            if (captureRt != null)
            {
                captureRt.Release();
                Object.Destroy(captureRt);
                captureRt = null;
            }

            if (fullTexture != null)
            {
                Object.Destroy(fullTexture);
                fullTexture = null;
            }

            if (roiTexture != null)
            {
                Object.Destroy(roiTexture);
                roiTexture = null;
            }

            rtWidth = 0;
            rtHeight = 0;
        }

        private readonly struct CaptureResult
        {
            public CaptureResult(byte[] bytes, int outputWidth, int outputHeight, int sourceWidth, int sourceHeight, RectInt cropRect, bool usedRoi)
            {
                this.bytes = bytes;
                this.outputWidth = outputWidth;
                this.outputHeight = outputHeight;
                this.sourceWidth = sourceWidth;
                this.sourceHeight = sourceHeight;
                this.cropRect = cropRect;
                this.usedRoi = usedRoi;
            }

            public readonly byte[] bytes;
            public readonly int outputWidth;
            public readonly int outputHeight;
            public readonly int sourceWidth;
            public readonly int sourceHeight;
            public readonly RectInt cropRect;
            public readonly bool usedRoi;
        }

        private readonly struct CapturePolicy
        {
            public CapturePolicy(int fps, int jpegQuality, int ttlMs)
            {
                this.fps = fps;
                this.jpegQuality = jpegQuality;
                this.ttlMs = ttlMs;
            }

            public readonly int fps;
            public readonly int jpegQuality;
            public readonly int ttlMs;
        }
    }
}
