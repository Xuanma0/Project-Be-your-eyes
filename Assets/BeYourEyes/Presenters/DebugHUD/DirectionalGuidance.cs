using System;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;
using BeYourEyes.Unity.Interaction;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class DirectionalGuidance : MonoBehaviour
    {
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;
        [SerializeField] private int defaultEventTtlMs = 1500;
        [SerializeField] private string stopText = "STOP";
        [SerializeField] private string scanText = "SCAN";

        private Canvas overlayCanvas;
        private Text overlayText;

        private bool remoteSafeMode;
        private long latestRiskSeq = -1;
        private long activeUntilMs = -1;
        private string activeGuidanceText = string.Empty;
        private bool hasActiveGuidance;
        private string currentDisplayedText = string.Empty;

        public long GuidanceShownCount { get; private set; }
        public long GuidanceClearedCount { get; private set; }
        public string LastGuidanceKind { get; private set; } = "-";
        public string LastAzimuthText { get; private set; } = "-";
        public string LastDistanceText { get; private set; } = "-";
        public long LastGuidanceSeq { get; private set; } = -1;

        private void Awake()
        {
            EnsureOverlay();
        }

        private void OnEnable()
        {
            BindClient();
            RefreshDisplay(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        }

        private void OnDisable()
        {
            UnbindClient();
            SetDisplay(string.Empty, false);
        }

        private void Update()
        {
            if (gatewayClient == null)
            {
                BindClient();
            }
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (hasActiveGuidance && nowMs > activeUntilMs)
            {
                hasActiveGuidance = false;
                activeGuidanceText = string.Empty;
                GuidanceClearedCount++;
            }

            RefreshDisplay(nowMs);
        }

        private void BindClient()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<BeYourEyes.Adapters.Networking.GatewayClient>();
            }
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
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
            if (string.Equals(type, "health", StringComparison.OrdinalIgnoreCase))
            {
                var status = ReadString(evt, "healthStatus");
                if (string.IsNullOrWhiteSpace(status))
                {
                    status = ParseHealthStatusFromSummary(ReadString(evt, "summary"));
                }

                remoteSafeMode = string.Equals(status, "SAFE_MODE", StringComparison.OrdinalIgnoreCase);
                RefreshDisplay(DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                return;
            }

            if (!string.Equals(type, "risk", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (!ShouldApplyRiskBySeq(evt))
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var ttlMs = ReadInt(evt, "_eventTtlMs", ReadInt(evt, "ttlMs", defaultEventTtlMs));
            var receivedAtMs = ReadLong(evt, "_receivedAtMs");
            if (receivedAtMs <= 0)
            {
                receivedAtMs = nowMs;
            }
            activeUntilMs = receivedAtMs + Math.Max(100, ttlMs);

            var riskLevel = ReadString(evt, "riskLevel");
            if (string.IsNullOrWhiteSpace(riskLevel))
            {
                riskLevel = "warn";
            }
            var hazardKind = ReadString(evt, "hazardKind");
            var hazardState = ReadString(evt, "hazardState");
            var hasAzimuth = TryReadFloat(evt, "azimuthDeg", out var azimuthDeg);
            var hasDistance = TryReadFloat(evt, "distanceM", out var distanceM);

            LastGuidanceKind = !string.IsNullOrWhiteSpace(hazardKind) ? hazardKind : riskLevel;
            LastAzimuthText = hasAzimuth ? $"{azimuthDeg:0.#}" : "-";
            LastDistanceText = hasDistance ? $"{distanceM:0.##}" : "-";

            var forceStop = IsForceStopRisk(riskLevel, hazardKind);
            activeGuidanceText = BuildGuidanceText(forceStop, hasAzimuth, azimuthDeg, hasDistance, distanceM, hazardKind, hazardState);
            hasActiveGuidance = true;
            GuidanceShownCount++;

            RefreshDisplay(nowMs);
        }

        private void RefreshDisplay(long nowMs)
        {
            if (overlayCanvas == null || overlayText == null)
            {
                return;
            }

            var fallbackBlocked = localSafetyFallback != null && !localSafetyFallback.IsOk;
            if (fallbackBlocked || remoteSafeMode)
            {
                SetDisplay(stopText, true);
                return;
            }

            if (hasActiveGuidance && nowMs <= activeUntilMs && !string.IsNullOrWhiteSpace(activeGuidanceText))
            {
                SetDisplay(activeGuidanceText, true);
                return;
            }

            SetDisplay(string.Empty, false);
        }

        private void SetDisplay(string text, bool visible)
        {
            if (overlayCanvas == null || overlayText == null)
            {
                return;
            }

            if (!visible)
            {
                if (overlayCanvas.gameObject.activeSelf)
                {
                    overlayCanvas.gameObject.SetActive(false);
                }
                currentDisplayedText = string.Empty;
                return;
            }

            if (!overlayCanvas.gameObject.activeSelf)
            {
                overlayCanvas.gameObject.SetActive(true);
            }

            if (!string.Equals(currentDisplayedText, text, StringComparison.Ordinal))
            {
                overlayText.text = text;
                currentDisplayedText = text;
            }
        }

        private bool ShouldApplyRiskBySeq(JObject evt)
        {
            var seq = ReadLong(evt, "seq");
            if (seq <= 0)
            {
                return latestRiskSeq <= 0;
            }

            if (latestRiskSeq > 0 && seq < latestRiskSeq)
            {
                return false;
            }

            latestRiskSeq = seq;
            LastGuidanceSeq = seq;
            return true;
        }

        private bool IsForceStopRisk(string riskLevel, string hazardKind)
        {
            if (string.Equals(riskLevel, "critical", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (string.IsNullOrWhiteSpace(hazardKind))
            {
                return false;
            }

            var kind = hazardKind.Trim().ToLowerInvariant();
            return kind.Contains("dropoff")
                   || kind.Contains("transparent_obstacle")
                   || kind.Contains("transparent")
                   || kind.Contains("glass");
        }

        private string BuildGuidanceText(bool forceStop, bool hasAzimuth, float azimuthDeg, bool hasDistance, float distanceM, string hazardKind, string hazardState)
        {
            var direction = ResolveDirectionSymbol(hasAzimuth, azimuthDeg);
            if (forceStop)
            {
                if (hasDistance && hasAzimuth)
                {
                    return $"STOP {direction}\n{distanceM:0.##}m {azimuthDeg:0.#}deg";
                }
                if (hasDistance)
                {
                    return $"STOP\n{distanceM:0.##}m";
                }
                if (!string.IsNullOrWhiteSpace(hazardKind))
                {
                    return $"STOP\n{hazardKind.ToUpperInvariant()}";
                }
                return stopText;
            }

            if (!hasAzimuth)
            {
                if (!string.IsNullOrWhiteSpace(hazardKind))
                {
                    return $"{scanText}\n{hazardKind}";
                }
                return $"{scanText}\nFront";
            }

            if (hasDistance)
            {
                return $"{direction}\n{distanceM:0.##}m {azimuthDeg:0.#}deg";
            }

            if (!string.IsNullOrWhiteSpace(hazardState))
            {
                return $"{direction}\n{hazardState}";
            }

            return $"{direction}\n{azimuthDeg:0.#}deg";
        }

        private static string ResolveDirectionSymbol(bool hasAzimuth, float azimuthDeg)
        {
            if (!hasAzimuth)
            {
                return "^";
            }

            if (azimuthDeg <= -15f)
            {
                return "<";
            }
            if (azimuthDeg >= 15f)
            {
                return ">";
            }
            return "^";
        }

        private void EnsureOverlay()
        {
            if (overlayCanvas != null)
            {
                return;
            }

            var canvasObj = new GameObject("ByesDirectionalGuidanceCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasObj.transform.SetParent(transform, false);
            overlayCanvas = canvasObj.GetComponent<Canvas>();
            overlayCanvas.renderMode = RenderMode.ScreenSpaceOverlay;
            overlayCanvas.sortingOrder = 970;

            var scaler = canvasObj.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);

            var textObj = new GameObject("ByesDirectionalGuidanceText", typeof(RectTransform), typeof(Text));
            textObj.transform.SetParent(canvasObj.transform, false);
            overlayText = textObj.GetComponent<Text>();
            var rect = overlayText.rectTransform;
            rect.anchorMin = new Vector2(0.3f, 0.38f);
            rect.anchorMax = new Vector2(0.7f, 0.62f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;

            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font != null)
            {
                overlayText.font = font;
            }
            overlayText.fontSize = 56;
            overlayText.alignment = TextAnchor.MiddleCenter;
            overlayText.color = new Color(1f, 0.95f, 0.15f, 1f);
            overlayText.raycastTarget = false;
            overlayText.text = string.Empty;

            canvasObj.SetActive(false);
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

        private static int ReadInt(JObject obj, string key, int defaultValue)
        {
            var token = obj[key];
            if (token == null)
            {
                return defaultValue;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<int>();
            }

            return int.TryParse(token.ToString(), out var parsed) ? parsed : defaultValue;
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

        private static string ParseHealthStatusFromSummary(string summary)
        {
            if (string.IsNullOrWhiteSpace(summary))
            {
                return string.Empty;
            }

            var text = summary.Trim().ToLowerInvariant();
            if (text.StartsWith("gateway_safe_mode"))
            {
                return "SAFE_MODE";
            }
            if (text.StartsWith("gateway_throttled"))
            {
                return "THROTTLED";
            }
            if (text.StartsWith("gateway_degraded"))
            {
                return "DEGRADED";
            }
            if (text.StartsWith("gateway_normal"))
            {
                return "NORMAL";
            }
            return string.Empty;
        }
    }
}
