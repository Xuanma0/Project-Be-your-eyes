using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class GatewayHUD : MonoBehaviour
    {
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;

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

        private string pendingConfirmId;
        private string pendingConfirmKind;

        private float nextClientLookupAt;

        private void OnEnable()
        {
            EnsureUi();
            BindClient();
        }

        private void OnDisable()
        {
            UnbindClient();
        }

        private void Update()
        {
            if (gatewayClient == null && Time.unscaledTime >= nextClientLookupAt)
            {
                nextClientLookupAt = Time.unscaledTime + 1f;
                BindClient();
            }

            if (statusText != null)
            {
                statusText.text =
                    "Gateway HUD\n" +
                    $"WS: {wsState}\n" +
                    $"Health: {healthStatus}\n" +
                    $"Reason: {healthReason}\n" +
                    $"Risk: {riskText}\n" +
                    $"RiskLevel: {riskLevel}\n" +
                    $"Action: {actionSummary}\n" +
                    $"PendingConfirm: {(string.IsNullOrWhiteSpace(pendingConfirmId) ? "-" : pendingConfirmKind)}";
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
            switch (type)
            {
                case "health":
                    healthStatus = ReadString(evt, "healthStatus");
                    healthReason = ReadString(evt, "healthReason");
                    if (string.IsNullOrEmpty(healthReason))
                    {
                        healthReason = ReadString(evt, "summary");
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
                    break;
                case "action_plan":
                    actionSummary = ReadString(evt, "summary");
                    HandleConfirmPayload(evt);
                    break;
                case "perception":
                    actionSummary = ReadString(evt, "summary");
                    break;
            }
        }

        private void HandleConfirmPayload(JObject evt)
        {
            var confirmId = ReadString(evt, "confirmId");
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                HideConfirmPanel();
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

            gatewayClient.SendConfirm(pendingConfirmId, choice, "unity_hud");
            Debug.Log($"[GatewayHUD] confirm submitted: id={pendingConfirmId} choice={choice}");
            HideConfirmPanel();
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
            statusText = CreateText(panel, "StatusText", 18, TextAnchor.UpperLeft);
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

        private static string ReadString(JObject obj, string key)
        {
            var token = obj[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }
    }
}
