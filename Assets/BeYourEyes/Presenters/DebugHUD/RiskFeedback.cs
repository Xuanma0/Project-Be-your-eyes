using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.XR;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class RiskFeedback : MonoBehaviour
    {
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;
        [SerializeField] private float criticalCooldownMs = 1200f;
        [SerializeField] private float overlayDurationSec = 0.9f;
        [SerializeField] private bool playBeep = true;
        [SerializeField] private bool pulseHaptics = true;
        [SerializeField] private bool warnHapticOnNewRisk = true;
        [SerializeField] private float warnHapticCooldownMs = 800f;
        [SerializeField] private float beepFrequencyHz = 920f;
        [SerializeField] private float beepDurationSec = 0.14f;
        [SerializeField] private float beepVolume = 0.22f;
        [SerializeField] private float hapticAmplitude = 0.6f;
        [SerializeField] private float hapticDurationSec = 0.08f;
        [SerializeField] private float warnHapticAmplitude = 0.25f;
        [SerializeField] private float warnHapticDurationSec = 0.03f;

        private Canvas overlayCanvas;
        private Text overlayText;
        private AudioSource audioSource;
        private AudioClip beepClip;
        private long lastCriticalTriggeredAtMs = long.MinValue;
        private long lastWarnTriggeredAtMs = long.MinValue;
        private long lastWarnSeq = -1;
        private string lastWarnKind = string.Empty;
        private float overlayHideAtRealtime = -1f;

        public long TriggerCount { get; private set; }
        public long CooldownSuppressedCount { get; private set; }

        private void Awake()
        {
            EnsureOverlay();
            EnsureAudio();
        }

        private void OnEnable()
        {
            BindClient();
        }

        private void OnDisable()
        {
            UnbindClient();
            SetOverlayVisible(false);
        }

        private void Update()
        {
#if !UNITY_WEBGL || UNITY_EDITOR
            if (gatewayClient == null)
            {
                BindClient();
            }
#endif
            if (overlayHideAtRealtime > 0f && Time.unscaledTime >= overlayHideAtRealtime)
            {
                SetOverlayVisible(false);
                overlayHideAtRealtime = -1f;
            }
        }

        private void BindClient()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<BeYourEyes.Adapters.Networking.GatewayClient>();
            }

            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            gatewayClient.OnGatewayEvent += HandleGatewayEvent;
        }

        private void UnbindClient()
        {
            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
        }

        private void HandleGatewayEvent(JObject evt)
        {
            if (evt == null)
            {
                return;
            }

            var type = ReadString(evt, "type");
            if (!string.Equals(type, "risk", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            var riskLevel = ReadString(evt, "riskLevel");
            if (string.Equals(riskLevel, "critical", StringComparison.OrdinalIgnoreCase))
            {
                HandleCriticalRisk(evt);
                return;
            }

            if (string.IsNullOrWhiteSpace(riskLevel))
            {
                riskLevel = "warn";
            }
            if (!string.Equals(riskLevel, "warn", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            HandleWarnRisk(evt);
        }

        private void HandleCriticalRisk(JObject evt)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (nowMs - lastCriticalTriggeredAtMs < Math.Max(0f, criticalCooldownMs))
            {
                CooldownSuppressedCount++;
                return;
            }

            lastCriticalTriggeredAtMs = nowMs;
            TriggerCount++;
            var hasAzimuth = TryReadFloat(evt, "azimuthDeg", out var azimuthDeg);
            ShowCriticalOverlay();
            if (playBeep)
            {
                PlayBeep(hasAzimuth ? AzimuthToPan(azimuthDeg) : 0f);
            }
            if (pulseHaptics)
            {
                TryPulseHaptics(hapticAmplitude, hapticDurationSec);
            }
        }

        private void HandleWarnRisk(JObject evt)
        {
            if (!warnHapticOnNewRisk)
            {
                return;
            }

            var seq = ReadLong(evt, "seq");
            var kind = ReadString(evt, "hazardKind");
            if (string.IsNullOrWhiteSpace(kind))
            {
                kind = ReadString(evt, "riskText");
            }

            var isNew = false;
            if (seq > 0 && seq > lastWarnSeq)
            {
                isNew = true;
            }
            if (!string.IsNullOrWhiteSpace(kind) && !string.Equals(kind, lastWarnKind, StringComparison.Ordinal))
            {
                isNew = true;
            }

            if (!isNew)
            {
                return;
            }

            lastWarnSeq = Math.Max(lastWarnSeq, seq);
            lastWarnKind = kind;

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (nowMs - lastWarnTriggeredAtMs < Math.Max(0f, warnHapticCooldownMs))
            {
                return;
            }
            lastWarnTriggeredAtMs = nowMs;
            TryPulseHaptics(warnHapticAmplitude, warnHapticDurationSec);
        }

        private void ShowCriticalOverlay()
        {
            if (overlayCanvas == null || overlayText == null)
            {
                return;
            }

            overlayText.text = "STOP / CRITICAL RISK";
            SetOverlayVisible(true);
            overlayHideAtRealtime = Time.unscaledTime + Mathf.Max(0.2f, overlayDurationSec);
        }

        private void SetOverlayVisible(bool visible)
        {
            if (overlayCanvas != null)
            {
                overlayCanvas.gameObject.SetActive(visible);
            }
        }

        private void EnsureOverlay()
        {
            if (overlayCanvas != null)
            {
                return;
            }

            var canvasObj = new GameObject("ByesRiskFeedbackCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasObj.transform.SetParent(transform, false);
            overlayCanvas = canvasObj.GetComponent<Canvas>();
            overlayCanvas.renderMode = RenderMode.ScreenSpaceOverlay;
            overlayCanvas.sortingOrder = 980;

            var scaler = canvasObj.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);

            var textObj = new GameObject("ByesRiskFeedbackText", typeof(RectTransform), typeof(Text));
            textObj.transform.SetParent(canvasObj.transform, false);
            overlayText = textObj.GetComponent<Text>();
            var rect = overlayText.rectTransform;
            rect.anchorMin = new Vector2(0.2f, 0.34f);
            rect.anchorMax = new Vector2(0.8f, 0.58f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;

            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font != null)
            {
                overlayText.font = font;
            }
            overlayText.fontSize = 52;
            overlayText.alignment = TextAnchor.MiddleCenter;
            overlayText.color = new Color(1f, 0.18f, 0.18f, 1f);
            overlayText.raycastTarget = false;
            overlayText.text = string.Empty;

            canvasObj.SetActive(false);
        }

        private void EnsureAudio()
        {
            if (audioSource == null)
            {
                audioSource = GetComponent<AudioSource>();
                if (audioSource == null)
                {
                    audioSource = gameObject.AddComponent<AudioSource>();
                }
                audioSource.playOnAwake = false;
                audioSource.loop = false;
            }

            if (beepClip != null)
            {
                return;
            }

            var sampleRate = 44100;
            var sampleCount = Mathf.Clamp(Mathf.CeilToInt(sampleRate * Mathf.Clamp(beepDurationSec, 0.02f, 0.5f)), 1, sampleRate);
            beepClip = AudioClip.Create("ByesRiskFeedbackBeep", sampleCount, 1, sampleRate, false);
            var data = new float[sampleCount];
            var volume = Mathf.Clamp01(beepVolume);
            for (var i = 0; i < sampleCount; i++)
            {
                var t = i / (float)sampleRate;
                data[i] = Mathf.Sin(2f * Mathf.PI * Mathf.Max(100f, beepFrequencyHz) * t) * volume;
            }
            beepClip.SetData(data, 0);
        }

        private void PlayBeep(float panStereo)
        {
            EnsureAudio();
            if (audioSource == null || beepClip == null)
            {
                return;
            }

            audioSource.panStereo = Mathf.Clamp(panStereo, -1f, 1f);
            audioSource.clip = beepClip;
            audioSource.Play();
        }

        private static float AzimuthToPan(float azimuthDeg)
        {
            var clamped = Mathf.Clamp(azimuthDeg, -60f, 60f);
            return clamped / 60f;
        }

        private void TryPulseHaptics(float amplitude, float durationSec)
        {
            try
            {
                var devices = new List<InputDevice>();
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

                    device.SendHapticImpulse(0u, Mathf.Clamp01(amplitude), Mathf.Clamp(durationSec, 0.01f, 0.4f));
                }
            }
            catch
            {
            }
        }

        private static long ReadLong(JObject obj, string key)
        {
            var token = obj[key];
            if (token == null)
            {
                return -1;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<long>();
            }

            return long.TryParse(token.ToString(), out var parsed) ? parsed : -1;
        }

        private static bool TryReadFloat(JObject obj, string key, out float value)
        {
            value = 0f;
            var token = obj[key];
            if (token == null)
            {
                return false;
            }

            if (token.Type == JTokenType.Float || token.Type == JTokenType.Integer)
            {
                value = token.Value<float>();
                return true;
            }

            return float.TryParse(token.ToString(), out value);
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }
    }
}
