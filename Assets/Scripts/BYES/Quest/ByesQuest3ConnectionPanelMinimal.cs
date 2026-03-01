using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace BYES.Quest
{
    public sealed class ByesQuest3ConnectionPanelMinimal : MonoBehaviour
    {
        private const string PrefBaseUrl = "BYES_GATEWAY_BASE_URL";
        private const string DefaultBaseUrl = "http://127.0.0.1:18000";

        private const float PingTimeoutSec = 2f;
        private const float QueryTimeoutSec = 3f;
        private const float ReachabilityIntervalSec = 2f;

        private string _baseUrl = DefaultBaseUrl;
        private int _pingSeq;
        private Coroutine _reachabilityCoroutine;

        private ITextView _titleText;
        private ITextView _baseUrlText;
        private ITextView _reachabilityText;
        private ITextView _pingText;
        private ITextView _versionText;
        private ITextView _modeText;
        private ITextView _rawText;

        private void Awake()
        {
            _baseUrl = NormalizeBaseUrl(PlayerPrefs.GetString(PrefBaseUrl, DefaultBaseUrl));
            EnsureEventSystem();
            BuildRuntimeUi();
            RefreshBaseUrlLabel();
        }

        private void OnEnable()
        {
            if (_reachabilityCoroutine == null)
            {
                _reachabilityCoroutine = StartCoroutine(ReachabilityLoop());
            }
        }

        private void OnDisable()
        {
            if (_reachabilityCoroutine != null)
            {
                StopCoroutine(_reachabilityCoroutine);
                _reachabilityCoroutine = null;
            }
        }

        private IEnumerator ReachabilityLoop()
        {
            while (enabled)
            {
                yield return SendPing(autoProbe: true);
                yield return new WaitForSecondsRealtime(ReachabilityIntervalSec);
            }
        }

        private void BuildRuntimeUi()
        {
            var canvasGo = new GameObject("Canvas", typeof(RectTransform), typeof(Canvas));
            canvasGo.transform.SetParent(transform, false);

            var canvas = canvasGo.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = ResolveWorldCamera();
            canvas.additionalShaderChannels = AdditionalCanvasShaderChannels.TexCoord1;
            canvas.sortingOrder = 5000;

            var canvasRect = canvasGo.GetComponent<RectTransform>();
            canvasRect.sizeDelta = new Vector2(1400f, 900f);
            canvasRect.localScale = Vector3.one * 0.00025f;
            canvasRect.localPosition = Vector3.zero;
            canvasRect.localRotation = Quaternion.identity;

            canvasGo.AddComponent<CanvasScaler>();
            AddBestRaycaster(canvasGo);

            var panel = CreateUiObject("Panel", canvasGo.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(1400f, 900f), Vector2.zero);
            var panelImage = panel.AddComponent<Image>();
            panelImage.color = new Color(0f, 0f, 0f, 0.78f);
            var panelGroup = panel.AddComponent<CanvasGroup>();
            panelGroup.blocksRaycasts = true;
            panelGroup.interactable = true;

            _titleText = CreateText("Title", panel.transform, "BYES Quest3 Gateway Panel", 46, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -70f), new Vector2(1220f, 90f));
            _baseUrlText = CreateText("BaseUrl", panel.transform, string.Empty, 36, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -180f), new Vector2(1220f, 75f));
            _reachabilityText = CreateText("Reachability", panel.transform, "HTTP: probing...", 38, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -260f), new Vector2(1220f, 75f));
            _pingText = CreateText("Ping", panel.transform, "Ping RTT: -", 36, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -335f), new Vector2(1220f, 70f));
            _versionText = CreateText("Version", panel.transform, "Version: -", 36, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -405f), new Vector2(1220f, 70f));
            _modeText = CreateText("Mode", panel.transform, "Mode: -", 36, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -475f), new Vector2(1220f, 70f));
            _rawText = CreateText("Raw", panel.transform, "-", 28, TextAnchor.UpperLeft, new Vector2(0.5f, 0f), new Vector2(0f, 95f), new Vector2(1220f, 160f));

            CreateButton(panel.transform, "PingButton", "Ping", new Vector2(-360f, -560f), () => StartCoroutine(SendPing(autoProbe: false)));
            CreateButton(panel.transform, "VersionButton", "Version", new Vector2(0f, -560f), () => StartCoroutine(QueryVersion()));
            CreateButton(panel.transform, "ModeButton", "Mode", new Vector2(360f, -560f), () => StartCoroutine(QueryMode()));
        }

        private static void EnsureEventSystem()
        {
            if (FindFirstObjectByType<EventSystem>() != null)
            {
                return;
            }

            var eventSystemGo = new GameObject("EventSystem", typeof(EventSystem));
            var inputSystemModuleType = Type.GetType("UnityEngine.InputSystem.UI.InputSystemUIInputModule, Unity.InputSystem");
            if (inputSystemModuleType != null)
            {
                eventSystemGo.AddComponent(inputSystemModuleType);
            }
            else
            {
                eventSystemGo.AddComponent<StandaloneInputModule>();
            }
        }

        private static void AddBestRaycaster(GameObject canvasGo)
        {
            var trackedRaycasterType = Type.GetType("UnityEngine.XR.Interaction.Toolkit.UI.TrackedDeviceGraphicRaycaster, Unity.XR.Interaction.Toolkit");
            if (trackedRaycasterType != null)
            {
                if (canvasGo.GetComponent(trackedRaycasterType) == null)
                {
                    canvasGo.AddComponent(trackedRaycasterType);
                }

                var graphicRaycaster = canvasGo.GetComponent<GraphicRaycaster>();
                if (graphicRaycaster != null)
                {
                    graphicRaycaster.enabled = false;
                }
                return;
            }

            if (canvasGo.GetComponent<GraphicRaycaster>() == null)
            {
                canvasGo.AddComponent<GraphicRaycaster>();
            }
        }

        private static Camera ResolveWorldCamera()
        {
            if (Camera.main != null && Camera.main.isActiveAndEnabled)
            {
                return Camera.main;
            }

            var cameras = Camera.allCameras;
            for (var i = 0; i < cameras.Length; i += 1)
            {
                if (cameras[i] != null && cameras[i].isActiveAndEnabled)
                {
                    return cameras[i];
                }
            }

            return null;
        }

        private static GameObject CreateUiObject(string name, Transform parent, Vector2 anchorMin, Vector2 anchorMax, Vector2 size, Vector2 anchoredPos)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            var rect = go.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.sizeDelta = size;
            rect.anchoredPosition = anchoredPos;
            return go;
        }

        private ITextView CreateText(
            string name,
            Transform parent,
            string value,
            int fontSize,
            TextAnchor fallbackAnchor,
            Vector2 anchor,
            Vector2 anchoredPos,
            Vector2 size)
        {
            var textGo = CreateUiObject(name, parent, anchor, anchor, size, anchoredPos);
            var tmpType = Type.GetType("TMPro.TextMeshProUGUI, Unity.TextMeshPro");
            if (tmpType != null)
            {
                var component = textGo.AddComponent(tmpType);
                return new TmpTextView(component, value, fontSize);
            }

            var uiText = textGo.AddComponent<Text>();
            uiText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            uiText.color = Color.white;
            uiText.alignment = fallbackAnchor;
            uiText.horizontalOverflow = HorizontalWrapMode.Wrap;
            uiText.verticalOverflow = VerticalWrapMode.Truncate;
            uiText.resizeTextForBestFit = false;
            uiText.fontSize = fontSize;
            uiText.text = value;
            return new UguiTextView(uiText);
        }

        private void CreateButton(Transform parent, string name, string label, Vector2 anchoredPos, Action onClick)
        {
            var buttonGo = CreateUiObject(name, parent, new Vector2(0.5f, 0f), new Vector2(0.5f, 0f), new Vector2(320f, 110f), anchoredPos);
            var image = buttonGo.AddComponent<Image>();
            image.color = new Color(0.22f, 0.55f, 0.94f, 0.95f);

            var button = buttonGo.AddComponent<Button>();
            button.targetGraphic = image;
            button.onClick.AddListener(() => onClick?.Invoke());

            _ = CreateText("Label", buttonGo.transform, label, 42, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(280f, 90f));
        }

        private IEnumerator SendPing(bool autoProbe)
        {
            var uri = $"{_baseUrl}/api/ping";
            var seq = _pingSeq++;
            var clientSendTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var body = $"{{\"deviceId\":\"quest3-smoke\",\"seq\":{seq},\"clientSendTsMs\":{clientSendTsMs}}}";
            var bodyBytes = Encoding.UTF8.GetBytes(body);

            using var request = new UnityWebRequest(uri, UnityWebRequest.kHttpVerbPOST);
            request.uploadHandler = new UploadHandlerRaw(bodyBytes);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            request.timeout = Mathf.CeilToInt(PingTimeoutSec);

            var start = Time.realtimeSinceStartupAsDouble;
            yield return request.SendWebRequest();
            var rttMs = Math.Max(0, Mathf.RoundToInt((float)((Time.realtimeSinceStartupAsDouble - start) * 1000.0)));

            if (request.result == UnityWebRequest.Result.Success)
            {
                _pingText.Set($"Ping RTT: {rttMs} ms");
                _reachabilityText.Set("HTTP: reachable");
                if (!autoProbe)
                {
                    _rawText.Set("Ping OK");
                }
                yield break;
            }

            _reachabilityText.Set("HTTP: unreachable");
            if (!autoProbe)
            {
                _rawText.Set($"Ping failed: {request.error}");
            }
        }

        private IEnumerator QueryVersion()
        {
            var uri = $"{_baseUrl}/api/version";
            using var request = UnityWebRequest.Get(uri);
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                _versionText.Set("Version: failed");
                _rawText.Set($"Version error: {request.error}");
                yield break;
            }

            var payload = request.downloadHandler.text ?? string.Empty;
            try
            {
                var parsed = JsonUtility.FromJson<VersionResponse>(payload);
                if (parsed != null && !string.IsNullOrWhiteSpace(parsed.version))
                {
                    var sha = string.IsNullOrWhiteSpace(parsed.gitSha) ? "-" : parsed.gitSha;
                    _versionText.Set($"Version: {parsed.version} / {sha}");
                    _rawText.Set("Version OK");
                    yield break;
                }
            }
            catch
            {
            }

            _versionText.Set("Version: raw");
            _rawText.Set(payload);
        }

        private IEnumerator QueryMode()
        {
            var uri = $"{_baseUrl}/api/mode";
            using var request = UnityWebRequest.Get(uri);
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                _modeText.Set("Mode: failed");
                _rawText.Set($"Mode error: {request.error}");
                yield break;
            }

            var payload = request.downloadHandler.text ?? string.Empty;
            try
            {
                var parsed = JsonUtility.FromJson<ModeResponse>(payload);
                if (parsed != null && !string.IsNullOrWhiteSpace(parsed.mode))
                {
                    _modeText.Set($"Mode: {parsed.mode}");
                    _rawText.Set("Mode OK");
                    yield break;
                }
            }
            catch
            {
            }

            _modeText.Set("Mode: raw");
            _rawText.Set(payload);
        }

        private void RefreshBaseUrlLabel()
        {
            _baseUrlText.Set($"Base URL: {_baseUrl}");
        }

        private static string NormalizeBaseUrl(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return DefaultBaseUrl;
            }

            var trimmed = value.Trim();
            return trimmed.EndsWith("/", StringComparison.Ordinal)
                ? trimmed.Substring(0, trimmed.Length - 1)
                : trimmed;
        }

        [Serializable]
        private sealed class VersionResponse
        {
            public string version;
            public string gitSha;
        }

        [Serializable]
        private sealed class ModeResponse
        {
            public string mode;
        }

        private interface ITextView
        {
            void Set(string value);
        }

        private sealed class UguiTextView : ITextView
        {
            private readonly Text _text;

            public UguiTextView(Text text)
            {
                _text = text;
            }

            public void Set(string value)
            {
                if (_text != null)
                {
                    _text.text = value ?? string.Empty;
                }
            }
        }

        private sealed class TmpTextView : ITextView
        {
            private readonly Component _component;
            private readonly System.Reflection.PropertyInfo _textProperty;
            private readonly System.Reflection.PropertyInfo _fontSizeProperty;
            private readonly System.Reflection.PropertyInfo _colorProperty;
            private readonly System.Reflection.PropertyInfo _alignmentProperty;

            public TmpTextView(Component component, string value, int fontSize)
            {
                _component = component;
                var type = component.GetType();
                _textProperty = type.GetProperty("text");
                _fontSizeProperty = type.GetProperty("fontSize");
                _colorProperty = type.GetProperty("color");
                _alignmentProperty = type.GetProperty("alignment");

                if (_fontSizeProperty != null)
                {
                    _fontSizeProperty.SetValue(_component, (float)fontSize, null);
                }

                if (_colorProperty != null)
                {
                    _colorProperty.SetValue(_component, Color.white, null);
                }

                if (_alignmentProperty != null)
                {
                    var enumType = _alignmentProperty.PropertyType;
                    object centerValue = null;
                    try
                    {
                        centerValue = Enum.Parse(enumType, "Center", ignoreCase: true);
                    }
                    catch
                    {
                        // ignore enum parse failures for package/version differences
                    }

                    if (centerValue != null)
                    {
                        _alignmentProperty.SetValue(_component, centerValue, null);
                    }
                }

                Set(value);
            }

            public void Set(string value)
            {
                if (_textProperty != null)
                {
                    _textProperty.SetValue(_component, value ?? string.Empty, null);
                }
            }
        }
    }
}
