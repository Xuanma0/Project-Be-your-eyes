using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;
using BeYourEyes.Unity.Interaction;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class GatewayHUD : MonoBehaviour
    {
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;
        [SerializeField] private BeYourEyes.Unity.Capture.FrameCapture frameCapture;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;
        [SerializeField] private float confirmPollIntervalSec = 1.5f;
        [SerializeField] private bool showDebugCounters = true;

        private Text statusText;
        private Text confirmPromptText;
        private RectTransform confirmOptionsRoot;
        private readonly List<Button> confirmButtons = new List<Button>();

        private string wsState = "Disconnected";
        private string healthStatus = "-";
        private string healthReason = "-";
        private string riskText = "-";
        private string riskLevel = "-";
        private string actionSummary = "-";
        private string lastEventType = "-";
        private string lastEventSummary = "-";
        private string lastEventStage = "-";

        private string pendingConfirmId;
        private string pendingConfirmKind;
        private bool confirmSubmitting;
        private readonly HashSet<string> resolvedConfirmIds = new HashSet<string>();
        private readonly HashSet<string> expiredConfirmIds = new HashSet<string>();
        private readonly Dictionary<string, long> confirmFirstSeenAtMs = new Dictionary<string, long>();
        private readonly Dictionary<string, int> confirmTtlById = new Dictionary<string, int>();
        private long latestContentSeq = -1;
        private long displayedEventSeq = -1;
        private long displayedEventReceivedAtMs = -1;
        private int displayedEventTtlMs = 1500;

        private float nextClientLookupAt;
        private Coroutine confirmPollRoutine;

        private void OnEnable()
        {
            EnsureUi();
            BindClient();
            StartConfirmPoller();
        }

        private void OnDisable()
        {
            StopConfirmPoller();
            UnbindClient();
        }

        private void Update()
        {
            if (gatewayClient == null && Time.unscaledTime >= nextClientLookupAt)
            {
                nextClientLookupAt = Time.unscaledTime + 1f;
                BindClient();
            }

            if (frameCapture == null)
            {
                frameCapture = FindFirstObjectByType<BeYourEyes.Unity.Capture.FrameCapture>();
            }
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
            }

            if (statusText != null)
            {
                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (IsDisplayedEventExpired(nowMs))
                {
                    ClearDisplayedContent();
                }

                var lastMsgAgeText = gatewayClient != null && gatewayClient.LastMessageAtMs > 0
                    ? $"{Mathf.Max(0f, (float)(nowMs - gatewayClient.LastMessageAtMs) / 1000f):0.0}s ago"
                    : "-";
                var reconnectText = gatewayClient != null ? gatewayClient.ReconnectAttempt.ToString() : "-";
                var healthRttText = gatewayClient != null && gatewayClient.LastHealthRttMs >= 0
                    ? $"{gatewayClient.LastHealthRttMs} ms"
                    : "-";
                var ttfaText = gatewayClient != null && gatewayClient.LastTtfaMs >= 0 ? $"{gatewayClient.LastTtfaMs} ms" : "-";
                var ttfaEmaText = gatewayClient != null && gatewayClient.TtfaEmaMs >= 0 ? $"{gatewayClient.TtfaEmaMs:0.0} ms" : "-";
                var captureStats = frameCapture == null
                    ? "-"
                    : $"cap={frameCapture.FramesCaptured} sent={frameCapture.FramesSent} dropBusy={frameCapture.FramesDroppedBusy} dropNoConn={frameCapture.FramesDroppedNoConn}";
                var bytesEmaText = frameCapture != null && frameCapture.BytesEma >= 0
                    ? $"{frameCapture.BytesEma:0}"
                    : "-";
                var keyframeReasonText = frameCapture == null ? "-" : frameCapture.LastKeyframeReason;
                var fallbackStateText = localSafetyFallback == null ? "OK" : localSafetyFallback.CurrentState.ToString();
                var fallbackSinceText = "-";
                var fallbackReasonText = localSafetyFallback == null ? "-" : localSafetyFallback.LastReason;
                if (localSafetyFallback != null && localSafetyFallback.StateEnteredAtMs > 0)
                {
                    fallbackSinceText = $"{Mathf.Max(0f, (float)(nowMs - localSafetyFallback.StateEnteredAtMs) / 1000f):0.0}s";
                }
                if (localSafetyFallback != null && !localSafetyFallback.IsOk)
                {
                    ClearDisplayedContent();
                }

                var lastEventAgeMs = displayedEventReceivedAtMs > 0 ? Math.Max(0, nowMs - displayedEventReceivedAtMs) : -1;
                var safeBanner = string.Equals(healthStatus, "SAFE_MODE", StringComparison.OrdinalIgnoreCase)
                    ? "\nSAFE MODE: STOP / RISK ONLY"
                    : string.Empty;
                var debugLines = string.Empty;
                if (showDebugCounters && gatewayClient != null)
                {
                    debugLines =
                        $"\nGuard: acc={gatewayClient.EventAcceptedCount} exp={gatewayClient.EventDroppedExpiredCount} ooo={gatewayClient.EventDroppedOutOfOrderCount} fb={gatewayClient.EventDroppedByFallbackCount}" +
                        $"\nlastSeqSeen={gatewayClient.EventLastSeqSeen} displayedSeq={displayedEventSeq} lastEventAgeMs={(lastEventAgeMs >= 0 ? lastEventAgeMs.ToString() : "-")}";
                }

                statusText.text =
                    "Gateway HUD\n" +
                    $"WS: {wsState}\n" +
                    $"Reconnects: {reconnectText}\n" +
                    $"LastMsg: {lastMsgAgeText}\n" +
                    $"HealthRTT: {healthRttText}\n" +
                    $"Health: {healthStatus}\n" +
                    $"Reason: {healthReason}\n" +
                    $"Risk: {riskText}\n" +
                    $"RiskLevel: {riskLevel}\n" +
                    $"Action: {actionSummary}\n" +
                    $"Event: {lastEventType} stage={lastEventStage}\n" +
                    $"Summary: {lastEventSummary}\n" +
                    $"TTFA: {ttfaText} | EMA: {ttfaEmaText}\n" +
                    $"Frames: {captureStats}\n" +
                    $"BytesEMA: {bytesEmaText}\n" +
                    $"Keyframe: {keyframeReasonText}\n" +
                    $"Fallback: {fallbackStateText} since={fallbackSinceText} reason={fallbackReasonText}\n" +
                    $"PendingConfirm: {(string.IsNullOrWhiteSpace(pendingConfirmId) ? "-" : pendingConfirmKind)}" +
                    debugLines +
                    safeBanner;
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
            gatewayClient.OnWebSocketStateChanged -= HandleWsStateChanged;
            gatewayClient.OnWebSocketStateChanged += HandleWsStateChanged;
            wsState = gatewayClient.IsConnected ? "Connected" : "Disconnected";
        }

        private void UnbindClient()
        {
            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            gatewayClient.OnWebSocketStateChanged -= HandleWsStateChanged;
        }

        private void HandleWsStateChanged(bool connected, string reason)
        {
            wsState = connected ? "Connected" : $"Disconnected ({reason})";
        }

        private void HandleGatewayEvent(JObject evt)
        {
            var type = ReadString(evt, "type");
            var summary = ReadString(evt, "summary");
            if (string.IsNullOrWhiteSpace(summary))
            {
                summary = ReadString(evt, "riskText");
            }
            if (string.IsNullOrWhiteSpace(type))
            {
                return;
            }
            lastEventStage = ReadString(evt, "stage");
            if (string.IsNullOrWhiteSpace(lastEventStage))
            {
                lastEventStage = "-";
            }

            if (!ShouldApplyEventBySeq(type, evt))
            {
                return;
            }

            lastEventType = type;
            lastEventSummary = string.IsNullOrWhiteSpace(summary) ? "-" : summary;
            displayedEventReceivedAtMs = ReadLong(evt, "_receivedAtMs");
            displayedEventTtlMs = ReadInt(evt, "_eventTtlMs", gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500);
            switch (type)
            {
                case "health":
                    healthStatus = ReadString(evt, "healthStatus");
                    if (string.IsNullOrWhiteSpace(healthStatus))
                    {
                        healthStatus = ParseHealthStatusFromSummary(summary);
                    }
                    healthReason = ReadString(evt, "healthReason");
                    if (string.IsNullOrEmpty(healthReason))
                    {
                        healthReason = ParseHealthReasonFromSummary(summary);
                    }
                    if (string.IsNullOrEmpty(healthReason))
                    {
                        healthReason = summary;
                    }
                    break;
                case "risk":
                    riskText = ReadString(evt, "riskText");
                    if (string.IsNullOrEmpty(riskText))
                    {
                        riskText = ReadString(evt, "summary");
                    }
                    riskLevel = ReadString(evt, "riskLevel");
                    if (string.IsNullOrEmpty(riskLevel))
                    {
                        riskLevel = "warn";
                    }
                    actionSummary = "-";
                    break;
                case "action_plan":
                    actionSummary = summary;
                    HandleConfirmPayload(evt);
                    break;
                case "perception":
                    actionSummary = summary;
                    riskText = "-";
                    riskLevel = "-";
                    break;
            }
        }

        private void HandleConfirmPayload(JObject evt)
        {
            if (localSafetyFallback != null && !localSafetyFallback.IsOk)
            {
                return;
            }

            var confirmId = ReadString(evt, "confirmId");
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                return;
            }
            if (expiredConfirmIds.Contains(confirmId))
            {
                return;
            }

            RegisterConfirmFreshness(confirmId, evt);
            ApplyConfirmFreshness(confirmId, evt);
            if (IsEventExpired(evt, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()))
            {
                expiredConfirmIds.Add(confirmId);
                return;
            }
            if (resolvedConfirmIds.Contains(confirmId))
            {
                return;
            }
            if (!string.IsNullOrWhiteSpace(pendingConfirmId) && string.Equals(pendingConfirmId, confirmId, StringComparison.Ordinal))
            {
                return;
            }

            pendingConfirmId = confirmId;
            pendingConfirmKind = ReadString(evt, "confirmKind");
            var prompt = ReadString(evt, "confirmPrompt");
            if (string.IsNullOrWhiteSpace(prompt))
            {
                prompt = ReadString(evt, "summary");
            }

            var options = new List<string>();
            if (evt["confirmOptions"] is JArray arr)
            {
                foreach (var token in arr)
                {
                    var option = token?.ToString().Trim();
                    if (!string.IsNullOrWhiteSpace(option))
                    {
                        options.Add(option);
                    }
                }
            }

            if (options.Count == 0)
            {
                options.Add("yes");
                options.Add("no");
            }

            ShowConfirmPanel(prompt, options);
        }

        private void ShowConfirmPanel(string prompt, List<string> options)
        {
            if (confirmPromptText != null)
            {
                confirmPromptText.text = string.IsNullOrWhiteSpace(prompt) ? "Please confirm" : prompt;
            }

            foreach (var button in confirmButtons)
            {
                if (button != null)
                {
                    Destroy(button.gameObject);
                }
            }
            confirmButtons.Clear();

            if (confirmOptionsRoot == null)
            {
                return;
            }

            foreach (var option in options)
            {
                var optionCopy = option;
                var button = CreateOptionButton(confirmOptionsRoot, optionCopy);
                button.onClick.AddListener(() => OnConfirmChoice(optionCopy));
                confirmButtons.Add(button);
            }

            confirmSubmitting = false;
            SetConfirmButtonsInteractable(true);
            confirmPromptText.gameObject.SetActive(true);
            confirmOptionsRoot.gameObject.SetActive(true);
        }

        private void HideConfirmPanel()
        {
            pendingConfirmId = null;
            pendingConfirmKind = null;
            if (confirmPromptText != null)
            {
                confirmPromptText.text = string.Empty;
                confirmPromptText.gameObject.SetActive(false);
            }
            confirmSubmitting = false;

            if (confirmOptionsRoot != null)
            {
                confirmOptionsRoot.gameObject.SetActive(false);
            }
        }

        private void OnConfirmChoice(string choice)
        {
            if (gatewayClient == null || string.IsNullOrWhiteSpace(pendingConfirmId))
            {
                return;
            }
            if (confirmSubmitting)
            {
                return;
            }

            confirmSubmitting = true;
            SetConfirmButtonsInteractable(false);
            var confirmId = pendingConfirmId;
            gatewayClient.SendConfirm(confirmId, choice, "unity_hud", success =>
            {
                if (success)
                {
                    resolvedConfirmIds.Add(confirmId);
                    confirmFirstSeenAtMs.Remove(confirmId);
                    confirmTtlById.Remove(confirmId);
                    Debug.Log($"[GatewayHUD] confirm submitted: id={confirmId} choice={choice}");
                    HideConfirmPanel();
                }
                else
                {
                    confirmSubmitting = false;
                    SetConfirmButtonsInteractable(true);
                }
            });
        }

        private void StartConfirmPoller()
        {
            if (confirmPollRoutine != null)
            {
                return;
            }

            confirmPollRoutine = StartCoroutine(ConfirmPollLoop());
        }

        private void StopConfirmPoller()
        {
            if (confirmPollRoutine == null)
            {
                return;
            }

            StopCoroutine(confirmPollRoutine);
            confirmPollRoutine = null;
        }

        private IEnumerator ConfirmPollLoop()
        {
            while (true)
            {
                if (localSafetyFallback == null)
                {
                    localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
                }

                if (localSafetyFallback != null && !localSafetyFallback.IsOk)
                {
                    yield return new WaitForSecondsRealtime(Mathf.Max(0.5f, confirmPollIntervalSec));
                    continue;
                }

                if (gatewayClient != null)
                {
                    gatewayClient.FetchPendingConfirm((ok, payload) =>
                    {
                        if (!ok || payload == null)
                        {
                            return;
                        }

                        var pendingToken = payload["pending"];
                        if (!(pendingToken is JObject pendingObj))
                        {
                            return;
                        }

                        var confirmId = ReadString(pendingObj, "confirmId");
                        if (string.IsNullOrWhiteSpace(confirmId) || expiredConfirmIds.Contains(confirmId))
                        {
                            return;
                        }

                        RegisterConfirmFreshness(confirmId, pendingObj);
                        ApplyConfirmFreshness(confirmId, pendingObj);
                        if (!gatewayClient.TryAcceptUiEvent(pendingObj, "action_plan", out _, out _, out var rejectReason))
                        {
                            if (string.Equals(rejectReason, "expired", StringComparison.OrdinalIgnoreCase))
                            {
                                expiredConfirmIds.Add(confirmId);
                            }
                            return;
                        }

                        if (resolvedConfirmIds.Contains(confirmId))
                        {
                            return;
                        }

                        if (!string.IsNullOrWhiteSpace(pendingConfirmId) &&
                            string.Equals(confirmId, pendingConfirmId, StringComparison.Ordinal))
                        {
                            return;
                        }

                        HandleConfirmPayload(pendingObj);
                    });
                }

                yield return new WaitForSecondsRealtime(Mathf.Max(0.5f, confirmPollIntervalSec));
            }
        }

        private void SetConfirmButtonsInteractable(bool interactable)
        {
            foreach (var button in confirmButtons)
            {
                if (button != null)
                {
                    button.interactable = interactable;
                }
            }
        }

        private void EnsureUi()
        {
            if (statusText != null && confirmPromptText != null && confirmOptionsRoot != null)
            {
                return;
            }

            var canvasObj = new GameObject("ByesGatewayHudCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasObj.transform.SetParent(transform, false);
            var canvas = canvasObj.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 800;

            var scaler = canvasObj.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);

            var panel = CreatePanel(canvasObj.transform, new Vector2(12f, -12f), new Vector2(0f, 1f), new Vector2(520f, 360f));
            statusText = CreateText(panel.transform, "StatusText", 18, TextAnchor.UpperLeft);
            statusText.rectTransform.anchorMin = new Vector2(0f, 0.45f);
            statusText.rectTransform.anchorMax = new Vector2(1f, 1f);
            statusText.rectTransform.offsetMin = new Vector2(8f, 8f);
            statusText.rectTransform.offsetMax = new Vector2(-8f, -8f);

            var confirmPanel = CreatePanel(panel.transform, new Vector2(0f, 0f), new Vector2(0f, 0f), new Vector2(0f, 0f));
            var confirmRect = confirmPanel.GetComponent<RectTransform>();
            confirmRect.anchorMin = new Vector2(0f, 0f);
            confirmRect.anchorMax = new Vector2(1f, 0.42f);
            confirmRect.offsetMin = new Vector2(8f, 8f);
            confirmRect.offsetMax = new Vector2(-8f, -8f);

            confirmPromptText = CreateText(confirmPanel.transform, "ConfirmPrompt", 16, TextAnchor.UpperLeft);
            confirmPromptText.rectTransform.anchorMin = new Vector2(0f, 0.45f);
            confirmPromptText.rectTransform.anchorMax = new Vector2(1f, 1f);
            confirmPromptText.rectTransform.offsetMin = new Vector2(6f, 6f);
            confirmPromptText.rectTransform.offsetMax = new Vector2(-6f, -6f);

            var optionsObj = new GameObject("ConfirmOptions", typeof(RectTransform), typeof(HorizontalLayoutGroup));
            optionsObj.transform.SetParent(confirmPanel.transform, false);
            confirmOptionsRoot = optionsObj.GetComponent<RectTransform>();
            confirmOptionsRoot.anchorMin = new Vector2(0f, 0f);
            confirmOptionsRoot.anchorMax = new Vector2(1f, 0.42f);
            confirmOptionsRoot.offsetMin = new Vector2(6f, 6f);
            confirmOptionsRoot.offsetMax = new Vector2(-6f, -6f);

            var layout = optionsObj.GetComponent<HorizontalLayoutGroup>();
            layout.spacing = 8f;
            layout.childForceExpandHeight = true;
            layout.childForceExpandWidth = true;
            layout.childControlHeight = true;
            layout.childControlWidth = true;

            HideConfirmPanel();
        }

        private static GameObject CreatePanel(Transform parent, Vector2 anchoredPos, Vector2 anchor, Vector2 size)
        {
            var obj = new GameObject("Panel", typeof(RectTransform), typeof(Image));
            obj.transform.SetParent(parent, false);
            var rect = obj.GetComponent<RectTransform>();
            rect.anchorMin = anchor;
            rect.anchorMax = anchor;
            rect.pivot = anchor;
            rect.anchoredPosition = anchoredPos;
            rect.sizeDelta = size;

            var image = obj.GetComponent<Image>();
            image.color = new Color(0.05f, 0.08f, 0.12f, 0.82f);
            return obj;
        }

        private static Text CreateText(Transform parent, string name, int fontSize, TextAnchor anchor)
        {
            var obj = new GameObject(name, typeof(RectTransform), typeof(Text));
            obj.transform.SetParent(parent, false);
            var text = obj.GetComponent<Text>();
            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font != null)
            {
                text.font = font;
            }
            text.fontSize = fontSize;
            text.color = Color.white;
            text.alignment = anchor;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            text.raycastTarget = false;
            return text;
        }

        private static Button CreateOptionButton(Transform parent, string label)
        {
            var buttonObj = new GameObject($"Option_{label}", typeof(RectTransform), typeof(Image), typeof(Button));
            buttonObj.transform.SetParent(parent, false);

            var image = buttonObj.GetComponent<Image>();
            image.color = new Color(0.2f, 0.45f, 0.8f, 0.95f);

            var button = buttonObj.GetComponent<Button>();
            button.targetGraphic = image;

            var text = CreateText(buttonObj.transform, "Label", 16, TextAnchor.MiddleCenter);
            text.text = label;
            text.rectTransform.anchorMin = Vector2.zero;
            text.rectTransform.anchorMax = Vector2.one;
            text.rectTransform.offsetMin = new Vector2(4f, 4f);
            text.rectTransform.offsetMax = new Vector2(-4f, -4f);
            return button;
        }

        private bool ShouldApplyEventBySeq(string type, JObject evt)
        {
            if (string.Equals(type, "health", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (!string.Equals(type, "risk", StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(type, "perception", StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(type, "action_plan", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (ReadLong(evt, "seq") is long seq && seq > 0)
            {
                if (latestContentSeq > 0 && seq < latestContentSeq)
                {
                    return false;
                }

                latestContentSeq = seq;
                displayedEventSeq = seq;
                return true;
            }

            return latestContentSeq <= 0;
        }

        private bool IsDisplayedEventExpired(long nowMs)
        {
            if (displayedEventReceivedAtMs <= 0)
            {
                return false;
            }

            var ttlMs = Math.Max(100, displayedEventTtlMs);
            return nowMs - displayedEventReceivedAtMs > ttlMs;
        }

        private void ClearDisplayedContent()
        {
            riskText = "-";
            riskLevel = "-";
            actionSummary = "-";
            lastEventType = "-";
            lastEventSummary = "-";
            lastEventStage = "-";
            displayedEventReceivedAtMs = -1;
            displayedEventTtlMs = gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500;
            displayedEventSeq = -1;
            HideConfirmPanel();
        }

        private bool IsEventExpired(JObject evt, long nowMs)
        {
            var receivedAt = ReadLong(evt, "_receivedAtMs") ?? nowMs;
            var ttlMs = ReadInt(evt, "_eventTtlMs", gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500);
            return nowMs - receivedAt > Math.Max(100, ttlMs);
        }

        private void RegisterConfirmFreshness(string confirmId, JObject evt)
        {
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                return;
            }

            var ttlMs = ReadInt(evt, "_eventTtlMs", gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500);
            confirmTtlById[confirmId] = Math.Max(100, ttlMs);
            if (!confirmFirstSeenAtMs.ContainsKey(confirmId))
            {
                confirmFirstSeenAtMs[confirmId] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            }
        }

        private void ApplyConfirmFreshness(string confirmId, JObject evt)
        {
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                return;
            }

            if (confirmFirstSeenAtMs.TryGetValue(confirmId, out var firstSeen))
            {
                evt["_receivedAtMs"] = firstSeen;
            }

            if (confirmTtlById.TryGetValue(confirmId, out var ttl))
            {
                evt["_eventTtlMs"] = ttl;
            }
        }

        private static long? ReadLong(JObject obj, string key)
        {
            var token = obj[key];
            if (token == null)
            {
                return null;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<long>();
            }

            return long.TryParse(token.ToString(), out var parsed) ? parsed : (long?)null;
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

            var normalized = summary.Trim().ToLowerInvariant();
            if (normalized.StartsWith("gateway_safe_mode"))
            {
                return "SAFE_MODE";
            }
            if (normalized.StartsWith("gateway_throttled"))
            {
                return "THROTTLED";
            }
            if (normalized.StartsWith("gateway_degraded"))
            {
                return "DEGRADED";
            }
            if (normalized.StartsWith("gateway_waiting_client"))
            {
                return "WAITING_CLIENT";
            }
            if (normalized.StartsWith("gateway_normal"))
            {
                return "NORMAL";
            }

            return string.Empty;
        }

        private static string ParseHealthReasonFromSummary(string summary)
        {
            if (string.IsNullOrWhiteSpace(summary))
            {
                return string.Empty;
            }

            var open = summary.IndexOf('(');
            var close = summary.LastIndexOf(')');
            if (open >= 0 && close > open)
            {
                return summary.Substring(open + 1, close - open - 1).Trim();
            }

            return string.Empty;
        }
    }
}
