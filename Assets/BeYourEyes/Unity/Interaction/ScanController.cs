using System;
using System.Collections;
using BeYourEyes.Adapters;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Core.Events;
using BeYourEyes.Core.Scheduling;
using BeYourEyes.Unity.Capture;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.InputSystem;

namespace BeYourEyes.Unity.Interaction
{
    public sealed class ScanController : MonoBehaviour
    {
        public readonly struct UploadMetrics
        {
            public UploadMetrics(double uploadMs, double e2eMs, bool ok, string error)
            {
                UploadMs = uploadMs;
                E2eMs = e2eMs;
                Ok = ok;
                Error = string.IsNullOrWhiteSpace(error) ? string.Empty : error.Trim();
            }

            public double UploadMs { get; }
            public double E2eMs { get; }
            public bool Ok { get; }
            public string Error { get; }
        }

        private const float NoGatewayPromptThrottleSec = 5f;

        public KeyCode scanKey = KeyCode.S;
        public KeyCode liveToggleKey = KeyCode.L;
        public float minIntervalSec = 1.0f;
        [Header("Live Loop")]
        [SerializeField] private bool liveEnabledDefault = false;
        [SerializeField] private float liveFps = 2.0f;
        [SerializeField] private int liveMaxInflight = 1;
        [SerializeField] private float liveMinIntervalOverrideSec = 0f;
        [SerializeField] private bool liveDropIfBusy = true;
        [Header("XR Input (optional)")]
        [SerializeField] private bool enableXrButtons = true;
        [SerializeField] private InputActionReference rightLiveToggleAction;
        [SerializeField] private InputActionReference rightPrimaryButtonAction;
        [SerializeField] private InputActionReference rightTriggerButtonAction;

        private ScreenFrameGrabber frameGrabber;
        private GatewayFrameUploader uploader;
        private GatewayWsClient wsClient;
        private GatewayClient gatewayClient;
        private InputAction fallbackPrimaryButtonAction;
        private InputAction fallbackTriggerButtonAction;
        private float lastNoGatewayPromptAt = -1000f;
        private double lastManualScanAtSec = -1000d;
        private double lastLiveTickAtSec = -1000d;
        private long lastAckOrEventTsMs = -1;
        private bool captureInProgress;
        private bool liveEnabled;
        private string lastScanState = "idle";
        private string lastScanError = string.Empty;
        private string lastEventType = "-";
        private int inflight;
        private long pendingE2eStartTsMs = -1;
        private long lastSendTsMs = -1;
        private double lastUploadCostMs = -1d;
        private double lastE2eMs = -1d;
        private int framesSentCount;
        private int uploadsOkCount;
        private int uploadsFailedCount;
        private int dropBusyCount;
        private int eventsReceivedCount;
        private string[] pendingForcedTargets;

        public bool LiveEnabled => liveEnabled;
        public bool IsLiveEnabled => liveEnabled;
        public float LiveFps => Mathf.Max(0f, liveFps);
        public int InflightCount => Mathf.Max(0, inflight);
        public int LiveMaxInflight => Mathf.Max(1, liveMaxInflight);
        public double LastUploadCostMs => lastUploadCostMs;
        public double LastE2eMs => lastE2eMs;
        public long LastSendTsMs => lastSendTsMs;
        public long LastAckOrEventTsMs => lastAckOrEventTsMs;
        public int FramesSentCount => Mathf.Max(0, framesSentCount);
        public int UploadsOkCount => Mathf.Max(0, uploadsOkCount);
        public int UploadsFailedCount => Mathf.Max(0, uploadsFailedCount);
        public int DropBusyCount => Mathf.Max(0, dropBusyCount);
        public int EventsReceivedCount => Mathf.Max(0, eventsReceivedCount);
        public string LastScanState => string.IsNullOrWhiteSpace(lastScanState) ? "idle" : lastScanState;
        public string LastScanError => string.IsNullOrWhiteSpace(lastScanError) ? string.Empty : lastScanError;
        public string LastEventType => string.IsNullOrWhiteSpace(lastEventType) ? "-" : lastEventType;
        public bool CaptureSupportsAsyncReadback => frameGrabber != null && frameGrabber.SupportsAsyncGpuReadback;
        public bool CaptureAsyncReadbackEnabled => frameGrabber != null && frameGrabber.AsyncGpuReadbackEnabled;
        public int CaptureTargetHz => frameGrabber != null ? frameGrabber.CaptureTargetHz : Mathf.Max(1, Mathf.RoundToInt(liveFps));
        public int CaptureActiveReadbacks => frameGrabber != null ? frameGrabber.ActiveReadbackRequests : 0;
        public event Action<UploadMetrics> OnUploadFinished;

        private void Awake()
        {
            AppServices.Init();
            frameGrabber = GetComponent<ScreenFrameGrabber>();
            if (frameGrabber == null)
            {
                frameGrabber = gameObject.AddComponent<ScreenFrameGrabber>();
            }

            if (frameGrabber != null)
            {
                liveFps = Mathf.Max(0.1f, frameGrabber.CaptureTargetHz);
                liveMaxInflight = Mathf.Max(1, frameGrabber.CaptureMaxInflight);
            }

            uploader = GetComponent<GatewayFrameUploader>();
            if (uploader == null)
            {
                uploader = gameObject.AddComponent<GatewayFrameUploader>();
            }

            gatewayClient = FindFirstObjectByType<GatewayClient>();
            liveEnabled = liveEnabledDefault;
        }

        private void OnEnable()
        {
            EnsureXrFallbackActions();
            rightLiveToggleAction?.action?.Enable();
            rightPrimaryButtonAction?.action?.Enable();
            rightTriggerButtonAction?.action?.Enable();
            fallbackPrimaryButtonAction?.Enable();
            fallbackTriggerButtonAction?.Enable();
            BindGatewayEventStream();
        }

        private void OnDisable()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            }

            rightLiveToggleAction?.action?.Disable();
            rightPrimaryButtonAction?.action?.Disable();
            rightTriggerButtonAction?.action?.Disable();
            fallbackPrimaryButtonAction?.Disable();
            fallbackTriggerButtonAction?.Disable();
        }

        private void EnsureXrFallbackActions()
        {
#if ENABLE_INPUT_SYSTEM
            if (!enableXrButtons)
            {
                return;
            }

            if (fallbackPrimaryButtonAction == null)
            {
                fallbackPrimaryButtonAction = new InputAction(
                    name: "BYES_RightPrimaryButton",
                    type: InputActionType.Button,
                    binding: "<XRController>{RightHand}/primaryButton");
            }

            if (fallbackTriggerButtonAction == null)
            {
                fallbackTriggerButtonAction = new InputAction(
                    name: "BYES_RightTriggerButton",
                    type: InputActionType.Button,
                    binding: "<XRController>{RightHand}/triggerPressed");
            }
#endif
        }

        private void Update()
        {
            if (WasLiveTogglePressedThisFrame())
            {
                ToggleLive();
            }

            if (WasManualScanPressedThisFrame())
            {
                TrySendFrame(isLiveTick: false);
            }

            if (liveEnabled)
            {
                TrySendFrame(isLiveTick: true);
            }
        }

        private void BindGatewayEventStream()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }

            if (gatewayClient != null)
            {
                gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
                gatewayClient.OnGatewayEvent += HandleGatewayEvent;
            }
        }

        private void HandleGatewayEvent(JObject evt)
        {
            if (evt == null)
            {
                return;
            }

            var type = (evt.Value<string>("type") ?? string.Empty).Trim().ToLowerInvariant();
            if (string.IsNullOrWhiteSpace(type))
            {
                var name = (evt.Value<string>("name") ?? string.Empty).Trim().ToLowerInvariant();
                if (!string.IsNullOrWhiteSpace(name))
                {
                    type = name;
                }
                else
                {
                    var category = (evt.Value<string>("category") ?? string.Empty).Trim().ToLowerInvariant();
                    type = string.IsNullOrWhiteSpace(category) ? "event" : category;
                }
            }

            if (!string.IsNullOrWhiteSpace(type))
            {
                lastEventType = type;
            }

            if (!IsScanRelevantEvent(type))
            {
                return;
            }

            eventsReceivedCount++;
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            lastAckOrEventTsMs = nowMs;
            if (pendingE2eStartTsMs <= 0)
            {
                return;
            }

            lastE2eMs = Math.Max(0d, nowMs - pendingE2eStartTsMs);
            pendingE2eStartTsMs = -1;
            EmitUploadMetrics(ok: true, error: string.Empty);
        }

        private bool IsGatewayConnected()
        {
            var wsConnected = wsClient != null && string.Equals(wsClient.ConnectionState, "Connected", StringComparison.Ordinal);
            if (wsConnected)
            {
                return true;
            }

            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }

            return gatewayClient != null && gatewayClient.IsConnected;
        }

        private void TrySendFrame(bool isLiveTick)
        {
            if (captureInProgress)
            {
                return;
            }

            if (wsClient == null)
            {
                wsClient = FindFirstObjectByType<GatewayWsClient>();
            }

            if (!IsGatewayConnected())
            {
                NotifyGatewayUnavailable();
                return;
            }

            var nowSec = Time.unscaledTimeAsDouble;
            if (!isLiveTick && nowSec - lastManualScanAtSec < minIntervalSec)
            {
                return;
            }

            if (isLiveTick && nowSec - lastLiveTickAtSec < ResolveLiveIntervalSec())
            {
                return;
            }

            var maxInflight = Mathf.Max(1, liveMaxInflight);
            if (inflight >= maxInflight)
            {
                if (liveDropIfBusy || isLiveTick)
                {
                    dropBusyCount++;
                    return;
                }
            }

            if (!isLiveTick)
            {
                lastManualScanAtSec = nowSec;
            }
            else
            {
                lastLiveTickAtSec = nowSec;
            }

            StartCoroutine(ScanOnce());
        }

        private double ResolveLiveIntervalSec()
        {
            if (!liveEnabled)
            {
                return double.MaxValue;
            }

            if (liveMinIntervalOverrideSec > 0f)
            {
                return Math.Max(0.05d, liveMinIntervalOverrideSec);
            }

            if (liveFps <= 0f)
            {
                return double.MaxValue;
            }

            return Math.Max(0.05d, 1d / liveFps);
        }

        private IEnumerator ScanOnce()
        {
            var forcedTargets = pendingForcedTargets;
            pendingForcedTargets = null;
            captureInProgress = true;
            inflight++;
            framesSentCount++;
            lastScanState = "sending";
            lastScanError = string.Empty;
            var sendTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            lastSendTsMs = sendTsMs;
            byte[] jpg = null;
            var uploadOk = false;
            var uploadCostMs = 0L;
            var uploadError = string.Empty;

            try
            {
                yield return frameGrabber.CaptureJpg(bytes => jpg = bytes);

                captureInProgress = false;
                if (jpg == null || jpg.Length == 0)
                {
                    Debug.LogWarning("[Scan] frame capture failed");
                    lastScanState = "failed";
                    lastScanError = "capture failed";
                    uploadsFailedCount++;
                    EmitUploadMetrics(ok: false, error: lastScanError);
                    yield break;
                }

                if (gatewayClient == null)
                {
                    gatewayClient = FindFirstObjectByType<GatewayClient>();
                }

                if (gatewayClient != null)
                {
                    uploader.baseUrl = gatewayClient.BaseUrl;
                    uploader.SetApiKey(gatewayClient.ApiKey);
                }
                var metaJson = BuildUploadMetaJson(sendTsMs, forcedTargets);

                yield return uploader.UploadFrame(
                    jpg,
                    metaJson,
                    onCompleted: (ok, elapsedMs) =>
                    {
                        uploadOk = ok;
                        uploadCostMs = elapsedMs;
                    });
                lastUploadCostMs = uploadCostMs;

                if (uploadOk)
                {
                    uploadsOkCount++;
                    pendingE2eStartTsMs = sendTsMs;
                    lastScanState = "uploaded";
                    lastScanError = string.Empty;
                    EmitUploadMetrics(ok: true, error: string.Empty);
                }
                else
                {
                    uploadsFailedCount++;
                    pendingE2eStartTsMs = -1;
                    uploadError = "upload failed";
                    lastScanState = "failed";
                    lastScanError = uploadError;
                    EmitUploadMetrics(ok: false, error: uploadError);
                }
            }
            finally
            {
                captureInProgress = false;
                inflight = Mathf.Max(0, inflight - 1);
            }
        }

        private void NotifyGatewayUnavailable()
        {
            if (Time.unscaledTime - lastNoGatewayPromptAt < NoGatewayPromptThrottleSec)
            {
                return;
            }

            lastNoGatewayPromptAt = Time.unscaledTime;
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var envelope = new EventEnvelope(nowMs, CoordFrame.World, 1f, 2000, "scan_controller");
            AppServices.Bus.Publish(new PromptEvent(
                envelope,
                "未连接网关，无法扫描",
                80,
                false,
                "tts",
                "system"));
        }

        private void ToggleLive()
        {
            liveEnabled = !liveEnabled;
            pendingE2eStartTsMs = -1;
            var status = liveEnabled ? "ON" : "OFF";
            Debug.Log($"[Scan] live loop {status} (fps={liveFps:0.##}, maxInflight={Mathf.Max(1, liveMaxInflight)})");
            lastScanState = liveEnabled ? "live" : "idle";
        }

        public void SetLiveEnabled(bool enabled)
        {
            if (liveEnabled == enabled)
            {
                return;
            }

            liveEnabled = enabled;
            pendingE2eStartTsMs = -1;
            var status = liveEnabled ? "ON" : "OFF";
            Debug.Log($"[Scan] live loop {status} (fps={liveFps:0.##}, maxInflight={Mathf.Max(1, liveMaxInflight)})");
            lastScanState = liveEnabled ? "live" : "idle";
        }

        public void ToggleLiveFromUi()
        {
            SetLiveEnabled(!liveEnabled);
        }

        public void ScanOnceFromUi()
        {
            TrySendFrame(isLiveTick: false);
        }

        public void ReadTextOnceFromUi()
        {
            pendingForcedTargets = new[] {"ocr"};
            TrySendFrame(isLiveTick: false);
        }

        public void DetectObjectsOnceFromUi()
        {
            pendingForcedTargets = new[] {"det"};
            TrySendFrame(isLiveTick: false);
        }

        public void DepthRiskOnceFromUi()
        {
            pendingForcedTargets = new[] {"depth", "risk"};
            TrySendFrame(isLiveTick: false);
        }

        public void ScanOnceWithTargetsFromUi(string[] targets)
        {
            if (targets == null || targets.Length == 0)
            {
                pendingForcedTargets = null;
            }
            else
            {
                pendingForcedTargets = targets;
            }
            TrySendFrame(isLiveTick: false);
        }

        private bool WasLiveTogglePressedThisFrame()
        {
            if (!enableXrButtons)
            {
                return WasKeyboardKeyPressedThisFrame(liveToggleKey);
            }

            var xrPressed =
                (rightLiveToggleAction != null && rightLiveToggleAction.action != null && rightLiveToggleAction.action.WasPressedThisFrame())
                || (rightPrimaryButtonAction != null && rightPrimaryButtonAction.action != null && rightPrimaryButtonAction.action.WasPressedThisFrame())
                || (fallbackPrimaryButtonAction != null && fallbackPrimaryButtonAction.WasPressedThisFrame());
            if (xrPressed)
            {
                return true;
            }

            return WasKeyboardKeyPressedThisFrame(liveToggleKey);
        }

        private bool WasManualScanPressedThisFrame()
        {
            if (enableXrButtons)
            {
                var triggerPressed =
                    (rightTriggerButtonAction != null && rightTriggerButtonAction.action != null && rightTriggerButtonAction.action.WasPressedThisFrame())
                    || (fallbackTriggerButtonAction != null && fallbackTriggerButtonAction.WasPressedThisFrame());
                if (triggerPressed)
                {
                    return true;
                }
            }

            return WasKeyboardKeyPressedThisFrame(scanKey);
        }

        private bool WasKeyboardKeyPressedThisFrame(KeyCode keyCode)
        {
#if ENABLE_INPUT_SYSTEM
            var keyboard = Keyboard.current;
            if (keyboard != null)
            {
                if (keyCode == KeyCode.S)
                {
                    return keyboard.sKey.wasPressedThisFrame;
                }

                if (keyCode == KeyCode.L)
                {
                    return keyboard.lKey.wasPressedThisFrame;
                }

                if (keyCode == KeyCode.BackQuote)
                {
                    return keyboard.backquoteKey.wasPressedThisFrame;
                }
            }
#endif
#if ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetKeyDown(keyCode);
#else
            return false;
#endif
        }

        private static bool IsScanRelevantEvent(string eventType)
        {
            switch (eventType)
            {
                case "risk":
                case "ocr":
                case "seg":
                case "depth":
                case "slam_pose":
                case "action_plan":
                case "prompt":
                case "frame.input":
                case "frame.ack":
                case "debug":
                case "event":
                    return true;
                default:
                    return false;
            }
        }

        private void EmitUploadMetrics(bool ok, string error)
        {
            OnUploadFinished?.Invoke(new UploadMetrics(
                uploadMs: lastUploadCostMs,
                e2eMs: lastE2eMs,
                ok: ok,
                error: error
            ));
        }

        private string BuildUploadMetaJson(long captureTsMs, string[] forcedTargets)
        {
            var mode = GatewayRuntimeContext.ResolveApiMode();
            var runId = gatewayClient != null ? (gatewayClient.SessionId ?? string.Empty).Trim() : string.Empty;
            if (string.IsNullOrWhiteSpace(runId))
            {
                runId = "quest3-smoke";
            }

            var payload = new JObject
            {
                ["runId"] = runId,
                ["deviceId"] = GatewayRuntimeContext.DeviceId,
                ["deviceTimeBase"] = GatewayRuntimeContext.DeviceTimeBase,
                ["captureTsMs"] = captureTsMs,
                ["mode"] = string.IsNullOrWhiteSpace(mode) ? "walk" : mode.Trim(),
            };

            if (forcedTargets != null && forcedTargets.Length > 0)
            {
                var arr = new JArray();
                for (var i = 0; i < forcedTargets.Length; i += 1)
                {
                    var token = string.IsNullOrWhiteSpace(forcedTargets[i]) ? string.Empty : forcedTargets[i].Trim().ToLowerInvariant();
                    if (token == "ocr" || token == "risk" || token == "det" || token == "seg" || token == "depth" || token == "slam")
                    {
                        arr.Add(token);
                    }
                }

                if (arr.Count > 0)
                {
                    payload["targets"] = arr;
                }
            }

            return payload.ToString(Newtonsoft.Json.Formatting.None);
        }
    }
}
