using System;
using System.Collections;
using System.Reflection;
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
        private const float NoGatewayPromptThrottleSec = 5f;
        private static readonly Type KeyboardType = Type.GetType("UnityEngine.InputSystem.Keyboard, Unity.InputSystem");
        private static readonly PropertyInfo KeyboardCurrentProperty = KeyboardType?.GetProperty("current", BindingFlags.Public | BindingFlags.Static);
        private static readonly PropertyInfo KeyboardSKeyProperty = KeyboardType?.GetProperty("sKey", BindingFlags.Public | BindingFlags.Instance);
        private static readonly PropertyInfo KeyboardLKeyProperty = KeyboardType?.GetProperty("lKey", BindingFlags.Public | BindingFlags.Instance);
        private static readonly Type ButtonControlType = Type.GetType("UnityEngine.InputSystem.Controls.ButtonControl, Unity.InputSystem");
        private static readonly PropertyInfo ButtonWasPressedThisFrameProperty = ButtonControlType?.GetProperty("wasPressedThisFrame", BindingFlags.Public | BindingFlags.Instance);

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
        private int inflight;
        private long pendingE2eStartTsMs = -1;
        private long lastSendTsMs = -1;
        private double lastUploadCostMs = -1d;
        private double lastE2eMs = -1d;

        public bool LiveEnabled => liveEnabled;
        public float LiveFps => Mathf.Max(0f, liveFps);
        public int InflightCount => Mathf.Max(0, inflight);
        public int LiveMaxInflight => Mathf.Max(1, liveMaxInflight);
        public double LastUploadCostMs => lastUploadCostMs;
        public double LastE2eMs => lastE2eMs;
        public long LastSendTsMs => lastSendTsMs;
        public long LastAckOrEventTsMs => lastAckOrEventTsMs;

        private void Awake()
        {
            AppServices.Init();
            frameGrabber = GetComponent<ScreenFrameGrabber>();
            if (frameGrabber == null)
            {
                frameGrabber = gameObject.AddComponent<ScreenFrameGrabber>();
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
            if (evt == null || pendingE2eStartTsMs <= 0)
            {
                return;
            }

            var type = (evt.Value<string>("type") ?? string.Empty).Trim().ToLowerInvariant();
            if (!IsInferenceLikeEvent(type))
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            lastAckOrEventTsMs = nowMs;
            lastE2eMs = Math.Max(0d, nowMs - pendingE2eStartTsMs);
            pendingE2eStartTsMs = -1;
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
            captureInProgress = true;
            inflight++;
            var sendTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            lastSendTsMs = sendTsMs;
            byte[] jpg = null;
            var uploadOk = false;
            var uploadCostMs = 0L;

            try
            {
                yield return frameGrabber.CaptureJpg(bytes => jpg = bytes);

                captureInProgress = false;
                if (jpg == null || jpg.Length == 0)
                {
                    Debug.LogWarning("[Scan] frame capture failed");
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

                yield return uploader.UploadFrame(
                    jpg,
                    onCompleted: (ok, elapsedMs) =>
                    {
                        uploadOk = ok;
                        uploadCostMs = elapsedMs;
                    });
                lastUploadCostMs = uploadCostMs;

                if (uploadOk)
                {
                    pendingE2eStartTsMs = sendTsMs;
                }
                else
                {
                    pendingE2eStartTsMs = -1;
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
            if (keyCode != KeyCode.S && keyCode != KeyCode.L)
            {
                return Input.GetKeyDown(keyCode);
            }

            if (KeyboardCurrentProperty == null || ButtonWasPressedThisFrameProperty == null)
            {
                return Input.GetKeyDown(keyCode);
            }

            var keyboard = KeyboardCurrentProperty.GetValue(null);
            if (keyboard == null)
            {
                return Input.GetKeyDown(keyCode);
            }

            PropertyInfo targetKeyProperty = keyCode == KeyCode.L ? KeyboardLKeyProperty : KeyboardSKeyProperty;
            if (targetKeyProperty == null)
            {
                return Input.GetKeyDown(keyCode);
            }

            var targetKey = targetKeyProperty.GetValue(keyboard);
            if (targetKey == null)
            {
                return Input.GetKeyDown(keyCode);
            }

            var pressed = ButtonWasPressedThisFrameProperty.GetValue(targetKey);
            return pressed is bool pressedBool && pressedBool;
        }

        private static bool IsInferenceLikeEvent(string eventType)
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
                    return true;
                default:
                    return false;
            }
        }
    }
}
