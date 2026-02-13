using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class DevIntentPanel : MonoBehaviour
    {
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;

        private InputField baseUrlInput;
        private InputField wsUrlInput;
        private InputField questionInput;
        private Dropdown intentDropdown;
        private Text statusText;

        private readonly List<string> intentOptions = new List<string> { "normal", "scan_text", "ask", "qa" };
        private float nextClientLookupAt;

        public string CurrentQuestion => questionInput != null ? (questionInput.text ?? string.Empty) : string.Empty;

        private void OnEnable()
        {
            EnsureUi();
            BindClient();
            RefreshInputsFromClient();
        }

        private void Update()
        {
            if (gatewayClient == null && Time.unscaledTime >= nextClientLookupAt)
            {
                nextClientLookupAt = Time.unscaledTime + 1f;
                BindClient();
                RefreshInputsFromClient();
            }
        }

        private void BindClient()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<BeYourEyes.Adapters.Networking.GatewayClient>();
            }
        }

        private void RefreshInputsFromClient()
        {
            if (gatewayClient == null)
            {
                return;
            }

            if (baseUrlInput != null && string.IsNullOrWhiteSpace(baseUrlInput.text))
            {
                baseUrlInput.text = gatewayClient.BaseUrl;
            }

            if (wsUrlInput != null && string.IsNullOrWhiteSpace(wsUrlInput.text))
            {
                wsUrlInput.text = gatewayClient.WsUrl;
            }
        }

        private void OnApplyGateway()
        {
            if (gatewayClient == null)
            {
                SetStatus("GatewayClient not found");
                return;
            }

            gatewayClient.SetGatewayEndpoints(baseUrlInput.text, wsUrlInput.text, reconnect: true);
            SetStatus("Gateway endpoints applied");
        }

        private void OnSendIntent()
        {
            if (gatewayClient == null)
            {
                SetStatus("GatewayClient not found");
                return;
            }

            var selected = intentDropdown != null ? intentOptions[Mathf.Clamp(intentDropdown.value, 0, intentOptions.Count - 1)] : "normal";
            var question = questionInput != null ? questionInput.text : string.Empty;
            if ((selected == "ask" || selected == "qa") && string.IsNullOrWhiteSpace(question))
            {
                SetStatus("Question required for ask/qa");
                return;
            }

            gatewayClient.SendDevIntent(selected, question, (ok, message) =>
            {
                SetStatus(ok
                    ? $"Intent sent: {selected}"
                    : $"Intent failed: {message}");
            });
        }

        private void SetStatus(string text)
        {
            if (statusText != null)
            {
                statusText.text = text;
            }
            Debug.Log($"[DevIntentPanel] {text}");
        }

        private void EnsureUi()
        {
            if (statusText != null && baseUrlInput != null && wsUrlInput != null && questionInput != null && intentDropdown != null)
            {
                return;
            }

            var canvasObj = new GameObject("ByesGatewayIntentCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasObj.transform.SetParent(transform, false);
            var canvas = canvasObj.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 810;

            var scaler = canvasObj.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);

            var panel = CreatePanel(canvasObj.transform, new Vector2(-12f, 12f), new Vector2(1f, 0f), new Vector2(520f, 300f));
            var layout = panel.AddComponent<VerticalLayoutGroup>();
            layout.padding = new RectOffset(10, 10, 10, 10);
            layout.spacing = 8f;
            layout.childControlWidth = true;
            layout.childControlHeight = true;
            layout.childForceExpandWidth = true;
            layout.childForceExpandHeight = false;

            CreateLabel(panel.transform, "BaseUrl");
            baseUrlInput = CreateInput(panel.transform, "http://127.0.0.1:8000");

            CreateLabel(panel.transform, "WsUrl");
            wsUrlInput = CreateInput(panel.transform, "ws://127.0.0.1:8000/ws/events");

            CreateLabel(panel.transform, "Intent");
            intentDropdown = CreateDropdown(panel.transform, intentOptions);

            CreateLabel(panel.transform, "Question (ask/qa)");
            questionInput = CreateInput(panel.transform, "what is in front of me?");

            var row = new GameObject("ButtonsRow", typeof(RectTransform), typeof(HorizontalLayoutGroup));
            row.transform.SetParent(panel.transform, false);
            var rowLayout = row.GetComponent<HorizontalLayoutGroup>();
            rowLayout.spacing = 8f;
            rowLayout.childControlWidth = true;
            rowLayout.childControlHeight = true;
            rowLayout.childForceExpandWidth = true;
            rowLayout.childForceExpandHeight = true;

            var applyButton = CreateButton(row.transform, "Apply Gateway");
            applyButton.onClick.AddListener(OnApplyGateway);

            var sendIntentButton = CreateButton(row.transform, "Send Intent");
            sendIntentButton.onClick.AddListener(OnSendIntent);

            statusText = CreateLabel(panel.transform, "Status: idle");
        }

        private static GameObject CreatePanel(Transform parent, Vector2 anchoredPos, Vector2 anchor, Vector2 size)
        {
            var obj = new GameObject("IntentPanel", typeof(RectTransform), typeof(Image));
            obj.transform.SetParent(parent, false);
            var rect = obj.GetComponent<RectTransform>();
            rect.anchorMin = anchor;
            rect.anchorMax = anchor;
            rect.pivot = anchor;
            rect.anchoredPosition = anchoredPos;
            rect.sizeDelta = size;

            var image = obj.GetComponent<Image>();
            image.color = new Color(0.08f, 0.1f, 0.14f, 0.85f);
            return obj;
        }

        private static Text CreateLabel(Transform parent, string content)
        {
            var obj = new GameObject("Label", typeof(RectTransform), typeof(Text));
            obj.transform.SetParent(parent, false);
            var text = obj.GetComponent<Text>();
            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font != null)
            {
                text.font = font;
            }
            text.fontSize = 15;
            text.color = Color.white;
            text.alignment = TextAnchor.MiddleLeft;
            text.text = content;
            var layout = obj.AddComponent<LayoutElement>();
            layout.minHeight = 26f;
            return text;
        }

        private static InputField CreateInput(Transform parent, string placeholder)
        {
            var root = new GameObject("Input", typeof(RectTransform), typeof(Image), typeof(InputField));
            root.transform.SetParent(parent, false);
            var rootImage = root.GetComponent<Image>();
            rootImage.color = new Color(0.16f, 0.2f, 0.26f, 0.95f);

            var input = root.GetComponent<InputField>();

            var text = CreateChildText(root.transform, "Text", string.Empty, TextAnchor.MiddleLeft);
            text.color = Color.white;
            text.rectTransform.offsetMin = new Vector2(10f, 6f);
            text.rectTransform.offsetMax = new Vector2(-10f, -6f);
            input.textComponent = text;

            var placeholderText = CreateChildText(root.transform, "Placeholder", placeholder, TextAnchor.MiddleLeft);
            placeholderText.color = new Color(0.8f, 0.8f, 0.8f, 0.6f);
            placeholderText.rectTransform.offsetMin = new Vector2(10f, 6f);
            placeholderText.rectTransform.offsetMax = new Vector2(-10f, -6f);
            input.placeholder = placeholderText;

            var layout = root.AddComponent<LayoutElement>();
            layout.minHeight = 34f;
            return input;
        }

        private static Dropdown CreateDropdown(Transform parent, List<string> options)
        {
            var root = new GameObject("Dropdown", typeof(RectTransform), typeof(Image), typeof(Dropdown));
            root.transform.SetParent(parent, false);
            var image = root.GetComponent<Image>();
            image.color = new Color(0.16f, 0.2f, 0.26f, 0.95f);

            var dropdown = root.GetComponent<Dropdown>();
            dropdown.options.Clear();
            foreach (var option in options)
            {
                dropdown.options.Add(new Dropdown.OptionData(option));
            }

            var label = CreateChildText(root.transform, "Label", options.Count > 0 ? options[0] : "none", TextAnchor.MiddleLeft);
            label.rectTransform.offsetMin = new Vector2(10f, 6f);
            label.rectTransform.offsetMax = new Vector2(-24f, -6f);
            dropdown.captionText = label;

            var template = BuildDropdownTemplate(root.transform);
            dropdown.template = template;
            dropdown.itemText = template.GetComponentInChildren<Text>(true);

            var layout = root.AddComponent<LayoutElement>();
            layout.minHeight = 34f;
            return dropdown;
        }

        private static RectTransform BuildDropdownTemplate(Transform parent)
        {
            var templateObj = new GameObject("Template", typeof(RectTransform), typeof(Image), typeof(ScrollRect));
            templateObj.transform.SetParent(parent, false);
            var templateRect = templateObj.GetComponent<RectTransform>();
            templateRect.anchorMin = new Vector2(0f, 0f);
            templateRect.anchorMax = new Vector2(1f, 0f);
            templateRect.pivot = new Vector2(0.5f, 1f);
            templateRect.anchoredPosition = new Vector2(0f, 2f);
            templateRect.sizeDelta = new Vector2(0f, 120f);
            templateObj.SetActive(false);

            var viewportObj = new GameObject("Viewport", typeof(RectTransform), typeof(Image), typeof(Mask));
            viewportObj.transform.SetParent(templateObj.transform, false);
            var viewportRect = viewportObj.GetComponent<RectTransform>();
            viewportRect.anchorMin = Vector2.zero;
            viewportRect.anchorMax = Vector2.one;
            viewportRect.offsetMin = Vector2.zero;
            viewportRect.offsetMax = Vector2.zero;
            viewportObj.GetComponent<Image>().color = new Color(0.14f, 0.18f, 0.24f, 0.95f);
            viewportObj.GetComponent<Mask>().showMaskGraphic = false;

            var contentObj = new GameObject("Content", typeof(RectTransform), typeof(VerticalLayoutGroup), typeof(ContentSizeFitter));
            contentObj.transform.SetParent(viewportObj.transform, false);
            var contentRect = contentObj.GetComponent<RectTransform>();
            contentRect.anchorMin = new Vector2(0f, 1f);
            contentRect.anchorMax = new Vector2(1f, 1f);
            contentRect.pivot = new Vector2(0.5f, 1f);
            contentRect.anchoredPosition = Vector2.zero;
            contentRect.sizeDelta = new Vector2(0f, 28f);

            var layout = contentObj.GetComponent<VerticalLayoutGroup>();
            layout.childForceExpandHeight = false;
            layout.childForceExpandWidth = true;
            layout.spacing = 2f;

            var fitter = contentObj.GetComponent<ContentSizeFitter>();
            fitter.verticalFit = ContentSizeFitter.FitMode.PreferredSize;

            var itemObj = new GameObject("Item", typeof(RectTransform), typeof(Toggle), typeof(Image));
            itemObj.transform.SetParent(contentObj.transform, false);
            itemObj.GetComponent<Image>().color = new Color(0.2f, 0.25f, 0.32f, 0.95f);
            var itemLayout = itemObj.AddComponent<LayoutElement>();
            itemLayout.minHeight = 26f;
            var itemText = CreateChildText(itemObj.transform, "Item Label", "option", TextAnchor.MiddleLeft);
            itemText.rectTransform.offsetMin = new Vector2(10f, 4f);
            itemText.rectTransform.offsetMax = new Vector2(-6f, -4f);

            var scrollRect = templateObj.GetComponent<ScrollRect>();
            scrollRect.viewport = viewportRect;
            scrollRect.content = contentRect;
            scrollRect.horizontal = false;
            scrollRect.vertical = true;

            var dropdownTemplate = templateObj.GetComponent<RectTransform>();
            var dropdown = parent.GetComponent<Dropdown>();
            dropdown.itemText = itemText;
            dropdown.itemImage = itemObj.GetComponent<Image>();
            return dropdownTemplate;
        }

        private static Button CreateButton(Transform parent, string label)
        {
            var obj = new GameObject(label, typeof(RectTransform), typeof(Image), typeof(Button));
            obj.transform.SetParent(parent, false);
            var image = obj.GetComponent<Image>();
            image.color = new Color(0.2f, 0.45f, 0.8f, 0.95f);
            var button = obj.GetComponent<Button>();
            button.targetGraphic = image;

            var text = CreateChildText(obj.transform, "Label", label, TextAnchor.MiddleCenter);
            text.color = Color.white;
            text.rectTransform.offsetMin = new Vector2(8f, 4f);
            text.rectTransform.offsetMax = new Vector2(-8f, -4f);
            var layout = obj.AddComponent<LayoutElement>();
            layout.minHeight = 34f;
            return button;
        }

        private static Text CreateChildText(Transform parent, string name, string content, TextAnchor anchor)
        {
            var obj = new GameObject(name, typeof(RectTransform), typeof(Text));
            obj.transform.SetParent(parent, false);
            var rect = obj.GetComponent<RectTransform>();
            rect.anchorMin = Vector2.zero;
            rect.anchorMax = Vector2.one;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;

            var text = obj.GetComponent<Text>();
            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font != null)
            {
                text.font = font;
            }
            text.fontSize = 14;
            text.color = Color.white;
            text.alignment = anchor;
            text.text = content;
            return text;
        }
    }
}
