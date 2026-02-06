using System;
using BeYourEyes.Adapters;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Core.EventBus;
using BeYourEyes.Core.Events;
using UnityEngine;
using UnityEngine.UI;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class DebugHudPresenter : MonoBehaviour
    {
        private const float RefreshIntervalSec = 0.2f;
        private const float WsLookupIntervalSec = 1f;

        private IEventBus bus;
        private Text hudText;
        private GatewayWsClient wsClient;

        private string gatewayState = "Connecting";
        private int reconnectCount;
        private int lastRttMs = -1;
        private string lastEventSummary = "-";
        private long lastEventTimestampMs;

        private float nextRefreshAt;
        private float nextWsLookupAt;

        private void OnEnable()
        {
            AppServices.Init();
            EnsureHud();

            bus = AppServices.Bus;
            bus.Subscribe<SystemHealthEvent>(OnSystemHealthEvent);
            bus.Subscribe<RiskEvent>(OnRiskEvent);
            bus.Subscribe<PerceptionEvent>(OnPerceptionEvent);
            bus.Subscribe<DialogEvent>(OnDialogEvent);
        }

        private void OnDisable()
        {
            if (bus == null)
            {
                return;
            }

            bus.Unsubscribe<SystemHealthEvent>(OnSystemHealthEvent);
            bus.Unsubscribe<RiskEvent>(OnRiskEvent);
            bus.Unsubscribe<PerceptionEvent>(OnPerceptionEvent);
            bus.Unsubscribe<DialogEvent>(OnDialogEvent);
            bus = null;
        }

        private void Update()
        {
            if (Time.unscaledTime >= nextWsLookupAt)
            {
                if (wsClient == null)
                {
                    wsClient = FindFirstObjectByType<GatewayWsClient>();
                }

                nextWsLookupAt = Time.unscaledTime + WsLookupIntervalSec;
            }

            if (wsClient != null)
            {
                if (!string.IsNullOrWhiteSpace(wsClient.ConnectionState))
                {
                    gatewayState = wsClient.ConnectionState;
                }

                reconnectCount = wsClient.ReconnectCount;
            }

            if (Time.unscaledTime < nextRefreshAt)
            {
                return;
            }

            nextRefreshAt = Time.unscaledTime + RefreshIntervalSec;
            RefreshHudText();
        }

        private void OnSystemHealthEvent(SystemHealthEvent evt)
        {
            if (evt == null || evt.envelope == null)
            {
                return;
            }

            var status = (evt.status ?? string.Empty).Trim().ToLowerInvariant();
            if (status == "gateway_connected")
            {
                gatewayState = "Connected";
            }
            else if (status == "gateway_disconnected" || status == "gateway_unreachable")
            {
                gatewayState = "Disconnected";
                if (wsClient == null)
                {
                    reconnectCount++;
                }
            }
            else if (status == "tick" && gatewayState != "Connected")
            {
                gatewayState = "Connecting";
            }

            if (evt.rttMs.HasValue && evt.rttMs.Value >= 0)
            {
                lastRttMs = evt.rttMs.Value;
            }

            SetLastEvent("System", string.IsNullOrWhiteSpace(evt.status) ? "tick" : evt.status, evt.envelope.timestampMs);
        }

        private void OnRiskEvent(RiskEvent evt)
        {
            if (evt == null || evt.envelope == null)
            {
                return;
            }

            var text = string.IsNullOrWhiteSpace(evt.riskText) ? "risk" : evt.riskText;
            SetLastEvent("Risk", text, evt.envelope.timestampMs);
        }

        private void OnPerceptionEvent(PerceptionEvent evt)
        {
            if (evt == null || evt.envelope == null)
            {
                return;
            }

            var text = string.IsNullOrWhiteSpace(evt.summary) ? "perception" : evt.summary;
            SetLastEvent("Perception", text, evt.envelope.timestampMs);
        }

        private void OnDialogEvent(DialogEvent evt)
        {
            if (evt == null || evt.envelope == null)
            {
                return;
            }

            var text = string.IsNullOrWhiteSpace(evt.text) ? "dialog" : evt.text;
            SetLastEvent("Dialog", text, evt.envelope.timestampMs);
        }

        private void SetLastEvent(string category, string payload, long timestampMs)
        {
            lastEventSummary = $"{category} | {payload}";
            lastEventTimestampMs = timestampMs;
        }

        private void RefreshHudText()
        {
            if (hudText == null)
            {
                return;
            }

            var safeModeText = AppServices.Scheduler != null && AppServices.Scheduler.SafeModeEnabled ? "ON" : "OFF";
            var rttText = lastRttMs >= 0 ? $"{lastRttMs} ms" : "-";
            var eventTimeText = lastEventTimestampMs > 0
                ? DateTimeOffset.FromUnixTimeMilliseconds(lastEventTimestampMs).ToLocalTime().ToString("HH:mm:ss")
                : "-";

            hudText.text =
                "BeYourEyes Debug\n" +
                $"Gateway: {gatewayState}\n" +
                $"SafeMode: {safeModeText}\n" +
                $"Reconnects: {reconnectCount}\n" +
                $"LastEvent: {lastEventSummary}\n" +
                $"LastEventAt: {eventTimeText}\n" +
                $"RTT: {rttText}";
        }

        private void EnsureHud()
        {
            var existing = GetComponentInChildren<Text>(true);
            if (existing != null)
            {
                hudText = existing;
                return;
            }

            var canvasObject = new GameObject("DebugHudCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasObject.transform.SetParent(transform, false);

            var canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 500;

            var scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);

            var textObject = new GameObject("DebugHudText", typeof(RectTransform), typeof(Text));
            textObject.transform.SetParent(canvasObject.transform, false);

            var rect = textObject.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 1f);
            rect.anchorMax = new Vector2(0f, 1f);
            rect.pivot = new Vector2(0f, 1f);
            rect.anchoredPosition = new Vector2(12f, -12f);
            rect.sizeDelta = new Vector2(720f, 220f);

            hudText = textObject.GetComponent<Text>();
            var builtinFont = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (builtinFont != null)
            {
                hudText.font = builtinFont;
            }
            hudText.fontSize = 20;
            hudText.alignment = TextAnchor.UpperLeft;
            hudText.horizontalOverflow = HorizontalWrapMode.Overflow;
            hudText.verticalOverflow = VerticalWrapMode.Overflow;
            hudText.color = Color.white;
            hudText.raycastTarget = false;
        }
    }
}
