using System;
using System.Collections;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using Object = UnityEngine.Object;

namespace BeYourEyes.Unity.Capture
{
    public sealed class FrameCapture : MonoBehaviour
    {
        [SerializeField] private Camera captureCamera;
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;
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

        [Header("Backpressure")]
        [SerializeField] private int busyDropThreshold = 8;
        [SerializeField, Range(0.2f, 1f)] private float busyDropFpsScale = 0.5f;
        [SerializeField] private bool includePose = true;
        [SerializeField] private bool autoStart = true;

        private readonly WaitForEndOfFrame waitForEndOfFrame = new WaitForEndOfFrame();
        private Coroutine captureRoutine;
        private int frameSeq;
        private int consecutiveBusyDrops;

        private long framesCaptured;
        private long framesSent;
        private long framesDroppedBusy;
        private long framesDroppedNoConn;

        public long FramesCaptured => framesCaptured;
        public long FramesSent => framesSent;
        public long FramesDroppedBusy => framesDroppedBusy;
        public long FramesDroppedNoConn => framesDroppedNoConn;

        private void OnEnable()
        {
            if (autoStart)
            {
                StartCapture();
            }
        }

        private void OnDisable()
        {
            StopCapture();
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

        private IEnumerator CaptureLoop()
        {
            while (true)
            {
                yield return waitForEndOfFrame;
                CaptureAndSendOnce();

                var policy = ResolvePolicy();
                var fps = Mathf.Max(0.5f, policy.fps * ResolveBusyScale());
                var interval = 1f / fps;
                yield return new WaitForSeconds(interval);
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

            var policy = ResolvePolicy();
            var jpg = CaptureCameraJpg(cameraToUse, captureWidth, captureHeight, policy.jpegQuality);
            if (jpg == null || jpg.Length == 0)
            {
                Debug.LogWarning("[FrameCapture] failed to capture jpg");
                return;
            }

            frameSeq++;
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var meta = BuildMeta(cameraToUse, nowMs, policy.ttlMs);
            var result = gatewayClient.TrySendFrameDetailed(jpg, meta.ToString(Formatting.None), frameSeq, nowMs);
            switch (result)
            {
                case BeYourEyes.Adapters.Networking.FrameSendResult.Accepted:
                    framesSent++;
                    consecutiveBusyDrops = 0;
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

        private JObject BuildMeta(Camera cameraToUse, long nowMs, int effectiveTtlMs)
        {
            var width = Mathf.Max(32, captureWidth);
            var height = Mathf.Max(32, captureHeight);
            var intrinsics = EstimateIntrinsics(cameraToUse, width, height);

            var meta = new JObject
            {
                ["sessionId"] = gatewayClient != null ? gatewayClient.SessionId : "default",
                ["seq"] = frameSeq,
                ["timestampMs"] = nowMs,
                ["tsCaptureMs"] = nowMs,
                ["ttlMs"] = Mathf.Max(200, effectiveTtlMs),
                ["width"] = width,
                ["height"] = height,
                ["coordFrame"] = "World",
                ["source"] = "unity_skeleton",
                ["intrinsics"] = intrinsics,
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
            var status = gatewayClient != null ? (gatewayClient.LastHealthStatus ?? string.Empty).Trim().ToUpperInvariant() : string.Empty;
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

        private static JObject EstimateIntrinsics(Camera cameraToUse, int width, int height)
        {
            var fovYRad = cameraToUse.fieldOfView * Mathf.Deg2Rad;
            var fy = 0.5f * height / Mathf.Tan(0.5f * Mathf.Max(0.01f, fovYRad));
            var fx = fy * (width / Mathf.Max(1f, height));
            var cx = width * 0.5f;
            var cy = height * 0.5f;

            return new JObject
            {
                ["fx"] = fx,
                ["fy"] = fy,
                ["cx"] = cx,
                ["cy"] = cy,
                ["width"] = width,
                ["height"] = height,
            };
        }

        private static byte[] CaptureCameraJpg(Camera cameraToUse, int width, int height, int quality)
        {
            var safeWidth = Mathf.Max(32, width);
            var safeHeight = Mathf.Max(32, height);
            var safeQuality = Mathf.Clamp(quality, 1, 100);

            RenderTexture rt = null;
            Texture2D tex = null;
            var previousTarget = cameraToUse.targetTexture;
            var previousActive = RenderTexture.active;

            try
            {
                rt = RenderTexture.GetTemporary(safeWidth, safeHeight, 24, RenderTextureFormat.ARGB32);
                tex = new Texture2D(safeWidth, safeHeight, TextureFormat.RGB24, false);

                cameraToUse.targetTexture = rt;
                cameraToUse.Render();
                RenderTexture.active = rt;

                tex.ReadPixels(new Rect(0, 0, safeWidth, safeHeight), 0, 0);
                tex.Apply(false, false);
                return tex.EncodeToJPG(safeQuality);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[FrameCapture] capture exception: {ex.Message}");
                return null;
            }
            finally
            {
                cameraToUse.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                if (rt != null)
                {
                    RenderTexture.ReleaseTemporary(rt);
                }

                if (tex != null)
                {
                    Object.Destroy(tex);
                }
            }
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
