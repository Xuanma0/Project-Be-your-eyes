using System;
using System.Collections;
using System.Reflection;
using BeYourEyes.Adapters;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Core.Events;
using BeYourEyes.Core.Scheduling;
using BeYourEyes.Unity.Capture;
using UnityEngine;

namespace BeYourEyes.Unity.Interaction
{
    public sealed class ScanController : MonoBehaviour
    {
        private const float NoGatewayPromptThrottleSec = 5f;
        private static readonly Type KeyboardType = Type.GetType("UnityEngine.InputSystem.Keyboard, Unity.InputSystem");
        private static readonly PropertyInfo KeyboardCurrentProperty = KeyboardType?.GetProperty("current", BindingFlags.Public | BindingFlags.Static);
        private static readonly PropertyInfo KeyboardSKeyProperty = KeyboardType?.GetProperty("sKey", BindingFlags.Public | BindingFlags.Instance);
        private static readonly Type ButtonControlType = Type.GetType("UnityEngine.InputSystem.Controls.ButtonControl, Unity.InputSystem");
        private static readonly PropertyInfo ButtonWasPressedThisFrameProperty = ButtonControlType?.GetProperty("wasPressedThisFrame", BindingFlags.Public | BindingFlags.Instance);

        public KeyCode scanKey = KeyCode.S;
        public float minIntervalSec = 1.0f;

        private ScreenFrameGrabber frameGrabber;
        private GatewayFrameUploader uploader;
        private GatewayWsClient wsClient;
        private float lastScanAt = -1000f;
        private float lastNoGatewayPromptAt = -1000f;
        private bool isScanning;

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
        }

        private void Update()
        {
            if (!WasScanPressedThisFrame())
            {
                return;
            }

            if (Time.unscaledTime - lastScanAt < minIntervalSec || isScanning)
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

            lastScanAt = Time.unscaledTime;
            StartCoroutine(ScanOnce());
        }

        private bool IsGatewayConnected()
        {
            return wsClient != null && string.Equals(wsClient.ConnectionState, "Connected", StringComparison.Ordinal);
        }

        private IEnumerator ScanOnce()
        {
            isScanning = true;
            byte[] jpg = null;

            yield return frameGrabber.CaptureJpg(bytes => jpg = bytes);

            if (jpg == null || jpg.Length == 0)
            {
                Debug.LogWarning("[Scan] frame capture failed");
                isScanning = false;
                yield break;
            }

            yield return uploader.UploadFrame(jpg);
            isScanning = false;
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

        private bool WasScanPressedThisFrame()
        {
            if (scanKey != KeyCode.S)
            {
                return false;
            }

            if (KeyboardCurrentProperty == null || KeyboardSKeyProperty == null || ButtonWasPressedThisFrameProperty == null)
            {
                return false;
            }

            var keyboard = KeyboardCurrentProperty.GetValue(null);
            if (keyboard == null)
            {
                return false;
            }

            var sKey = KeyboardSKeyProperty.GetValue(keyboard);
            if (sKey == null)
            {
                return false;
            }

            var pressed = ButtonWasPressedThisFrameProperty.GetValue(sKey);
            return pressed is bool pressedBool && pressedBool;
        }
    }
}
