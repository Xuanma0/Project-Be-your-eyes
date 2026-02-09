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
        [SerializeField] private float cooldownMs = 1200f;
        [SerializeField] private float overlayDurationSec = 0.9f;
        [SerializeField] private bool playBeep = true;
        [SerializeField] private bool pulseHaptics = true;
        [SerializeField] private float beepFrequencyHz = 920f;
        [SerializeField] private float beepDurationSec = 0.14f;
        [SerializeField] private float beepVolume = 0.22f;
        [SerializeField] private float hapticAmplitude = 0.6f;
        [SerializeField] private float hapticDurationSec = 0.08f;

        private Canvas overlayCanvas;
        private Text overlayText;
        private AudioSource audioSource;
        private AudioClip beepClip;
        private long lastTriggeredAtMs = long.MinValue;
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
            if (!string.Equals(riskLevel, "critical", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (nowMs - lastTriggeredAtMs < Math.Max(0f, cooldownMs))
            {
                CooldownSuppressedCount++;
                return;
            }

            lastTriggeredAtMs = nowMs;
            TriggerCount++;
            ShowCriticalOverlay();
            if (playBeep)
            {
                PlayBeep();
            }
            if (pulseHaptics)
            {
                TryPulseHaptics();
            }
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

        private void PlayBeep()
        {
            EnsureAudio();
            if (audioSource == null || beepClip == null)
            {
                return;
            }

            audioSource.clip = beepClip;
            audioSource.Play();
        }

        private void TryPulseHaptics()
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

                    device.SendHapticImpulse(0u, Mathf.Clamp01(hapticAmplitude), Mathf.Clamp(hapticDurationSec, 0.01f, 0.4f));
                }
            }
            catch
            {
            }
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }
    }
}
