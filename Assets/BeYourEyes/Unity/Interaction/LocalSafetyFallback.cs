using System;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;

namespace BeYourEyes.Unity.Interaction
{
    public enum LocalSafetyState
    {
        OK,
        STALE,
        DISCONNECTED,
        SAFE_MODE_REMOTE,
    }

    public enum FallbackCaptureMode
    {
        Pause,
        LowRate,
    }

    public sealed class LocalSafetyFallback : MonoBehaviour
    {
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;
        [SerializeField] private int staleThresholdMs = 1500;
        [SerializeField] private int recoverGraceMs = 500;

        [Header("Capture Degrade")]
        [SerializeField] private FallbackCaptureMode fallbackMode = FallbackCaptureMode.LowRate;
        [SerializeField] private int fallbackMinIntervalMs = 1000;

        [Header("Alert")]
        [SerializeField] private bool showOverlayText = true;
        [SerializeField] private bool playBeepOnEnter = true;
        [SerializeField] private bool hapticPulseOnEnter = true;
        [SerializeField] private float beepDurationSec = 0.18f;
        [SerializeField] private float beepFrequencyHz = 880f;
        [SerializeField] private float beepVolume = 0.2f;
        [SerializeField] private float hapticAmplitude = 0.5f;
        [SerializeField] private float hapticDurationSec = 0.06f;

        private LocalSafetyState currentState = LocalSafetyState.OK;
        private long stateEnteredAtMs = -1;
        private string lastReason = "ok";
        private long okCandidateSinceMs = -1;

        private Canvas overlayCanvas;
        private Text overlayText;
        private AudioSource beepSource;
        public event Action<LocalSafetyState, LocalSafetyState, string, long> OnStateChanged;

        public LocalSafetyState CurrentState => currentState;
        public bool IsOk => currentState == LocalSafetyState.OK;
        public string LastReason => lastReason;
        public long StateEnteredAtMs => stateEnteredAtMs;
        public FallbackCaptureMode CaptureMode => fallbackMode;
        public int FallbackMinIntervalMs => Mathf.Max(200, fallbackMinIntervalMs);
        public int StaleThresholdMs => Mathf.Max(200, staleThresholdMs);
        public int RecoverGraceMs => Mathf.Max(0, recoverGraceMs);

        private void Awake()
        {
            EnsureOverlay();
        }

        private void Update()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<BeYourEyes.Adapters.Networking.GatewayClient>();
                if (gatewayClient == null)
                {
                    return;
                }
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var nextState = EvaluateState(nowMs, out var reason);
            ApplyStateTransition(nextState, reason, nowMs);
        }

        private LocalSafetyState EvaluateState(long nowMs, out string reason)
        {
            if (!gatewayClient.IsConnected)
            {
                reason = gatewayClient.LastDisconnectReason;
                return LocalSafetyState.DISCONNECTED;
            }

            var healthStatus = (gatewayClient.LastHealthStatus ?? string.Empty).Trim().ToUpperInvariant();
            if (healthStatus == "SAFE_MODE")
            {
                reason = string.IsNullOrWhiteSpace(gatewayClient.LastHealthReason) ? "remote_safe_mode" : gatewayClient.LastHealthReason;
                return LocalSafetyState.SAFE_MODE_REMOTE;
            }

            if (gatewayClient.LastMessageAtMs <= 0 || nowMs - gatewayClient.LastMessageAtMs > StaleThresholdMs)
            {
                reason = "stale_message";
                return LocalSafetyState.STALE;
            }

            reason = "ok";
            return LocalSafetyState.OK;
        }

        private void ApplyStateTransition(LocalSafetyState nextState, string reason, long nowMs)
        {
            var previousState = currentState;
            if (nextState == LocalSafetyState.OK)
            {
                if (currentState == LocalSafetyState.OK)
                {
                    lastReason = "ok";
                    return;
                }

                if (okCandidateSinceMs < 0)
                {
                    okCandidateSinceMs = nowMs;
                }

                if (nowMs - okCandidateSinceMs < RecoverGraceMs)
                {
                    return;
                }

                currentState = LocalSafetyState.OK;
                stateEnteredAtMs = nowMs;
                lastReason = "ok";
                okCandidateSinceMs = -1;
                SetOverlayVisible(false, string.Empty);
                OnStateChanged?.Invoke(previousState, currentState, lastReason, nowMs);
                return;
            }

            okCandidateSinceMs = -1;
            var wasOk = currentState == LocalSafetyState.OK;
            if (currentState != nextState)
            {
                currentState = nextState;
                stateEnteredAtMs = nowMs;
                lastReason = string.IsNullOrWhiteSpace(reason) ? nextState.ToString() : reason;
                OnStateChanged?.Invoke(previousState, currentState, lastReason, nowMs);
            }

            if (wasOk)
            {
                TriggerStopAlertOnce();
            }

            SetOverlayVisible(showOverlayText, BuildOverlayMessage(currentState));
        }

        private void TriggerStopAlertOnce()
        {
            if (playBeepOnEnter)
            {
                PlayBeep();
            }
            if (hapticPulseOnEnter)
            {
                TryPulseHaptics();
            }
        }

        private void EnsureOverlay()
        {
            if (!showOverlayText || overlayCanvas != null)
            {
                return;
            }

            var canvasObj = new GameObject("ByesLocalSafetyCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasObj.transform.SetParent(transform, false);
            overlayCanvas = canvasObj.GetComponent<Canvas>();
            overlayCanvas.renderMode = RenderMode.ScreenSpaceOverlay;
            overlayCanvas.sortingOrder = 950;

            var scaler = canvasObj.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);

            var textObj = new GameObject("LocalSafetyText", typeof(RectTransform), typeof(Text));
            textObj.transform.SetParent(canvasObj.transform, false);
            overlayText = textObj.GetComponent<Text>();
            var rect = overlayText.rectTransform;
            rect.anchorMin = new Vector2(0.15f, 0.40f);
            rect.anchorMax = new Vector2(0.85f, 0.60f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;

            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font != null)
            {
                overlayText.font = font;
            }
            overlayText.fontSize = 44;
            overlayText.alignment = TextAnchor.MiddleCenter;
            overlayText.color = new Color(1f, 0.3f, 0.25f, 1f);
            overlayText.text = string.Empty;
            overlayText.raycastTarget = false;

            canvasObj.SetActive(false);
        }

        private void SetOverlayVisible(bool visible, string text)
        {
            if (overlayCanvas == null)
            {
                return;
            }

            overlayCanvas.gameObject.SetActive(visible);
            if (visible && overlayText != null)
            {
                overlayText.text = text;
            }
        }

        private string BuildOverlayMessage(LocalSafetyState state)
        {
            switch (state)
            {
                case LocalSafetyState.DISCONNECTED:
                    return "STOP / DISCONNECTED";
                case LocalSafetyState.STALE:
                    return "STOP / LINK STALE";
                case LocalSafetyState.SAFE_MODE_REMOTE:
                    return "STOP / SAFE MODE";
                default:
                    return "STOP";
            }
        }

        private void PlayBeep()
        {
            if (beepDurationSec <= 0f || beepFrequencyHz <= 0f)
            {
                return;
            }

            if (beepSource == null)
            {
                beepSource = gameObject.GetComponent<AudioSource>();
                if (beepSource == null)
                {
                    beepSource = gameObject.AddComponent<AudioSource>();
                }
                beepSource.playOnAwake = false;
                beepSource.loop = false;
            }

            var sampleRate = 44100;
            var sampleCount = Mathf.Clamp(Mathf.CeilToInt(sampleRate * Mathf.Clamp(beepDurationSec, 0.02f, 0.5f)), 1, sampleRate);
            var clip = AudioClip.Create("ByesLocalSafetyBeep", sampleCount, 1, sampleRate, false);
            var data = new float[sampleCount];
            var volume = Mathf.Clamp01(beepVolume);
            for (var i = 0; i < sampleCount; i++)
            {
                var t = i / (float)sampleRate;
                data[i] = Mathf.Sin(2f * Mathf.PI * beepFrequencyHz * t) * volume;
            }
            clip.SetData(data, 0);
            beepSource.clip = clip;
            beepSource.Play();
        }

        private void TryPulseHaptics()
        {
            try
            {
                var devices = new System.Collections.Generic.List<InputDevice>();
                InputDevices.GetDevices(devices);
                foreach (var device in devices)
                {
                    if (!device.isValid)
                    {
                        continue;
                    }

                    if (!device.TryGetHapticCapabilities(out var caps))
                    {
                        continue;
                    }

                    if (!caps.supportsImpulse)
                    {
                        continue;
                    }

                    device.SendHapticImpulse(0u, Mathf.Clamp01(hapticAmplitude), Mathf.Clamp(hapticDurationSec, 0.01f, 0.3f));
                }
            }
            catch
            {
            }
        }
    }
}
