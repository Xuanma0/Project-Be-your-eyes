using System;
using System.Collections;
using System.Reflection;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Unity.Interaction;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace BYES.Quest
{
    public sealed class ByesQuest3ConnectionPanelMinimal : MonoBehaviour
    {
        private const string PrefBaseUrl = "BYES_GATEWAY_BASE_URL";
        private const string PrefApiKeyLegacy = "byes.connection.api_key";
        private const string DefaultBaseUrl = "http://127.0.0.1:18000";

        private const float PingTimeoutSec = 2f;
        private const float QueryTimeoutSec = 3f;
        private const float ReachabilityIntervalSec = 2f;

        private string _baseUrl = DefaultBaseUrl;
        private string _apiKey = string.Empty;
        private int _pingSeq;
        private long _lastPingRttMs = -1;
        private long _lastEventTsMs = -1;
        private string _lastEventType = "-";
        private string _scanStatus = "idle";
        private string _scanError = string.Empty;
        private string _selfTestStatus = "IDLE";
        private string _selfTestSummary = "-";
        private long _toastUntilMs = -1;
        private Coroutine _reachabilityCoroutine;
        private Coroutine _statusRefreshCoroutine;

        private GatewayClient _gatewayClient;
        private GatewayWsClient _gatewayWsClient;
        private ScanController _scanController;
        private ByesQuest3SelfTestRunner _selfTestRunner;

        private ITextView _baseUrlText;
        private ITextView _reachabilityText;
        private ITextView _wsText;
        private ITextView _pingText;
        private ITextView _versionText;
        private ITextView _modeText;
        private ITextView _lastUploadText;
        private ITextView _lastE2eText;
        private ITextView _lastEventText;
        private ITextView _scanStateText;
        private ITextView _selfTestText;
        private ITextView _toastText;
        private ITextView _rawText;
        private ILabelButton _liveButton;
        private ILabelButton _scanButton;

        private void Awake()
        {
            _baseUrl = NormalizeBaseUrl(PlayerPrefs.GetString(PrefBaseUrl, DefaultBaseUrl));
            _apiKey = string.IsNullOrWhiteSpace(PlayerPrefs.GetString(PrefApiKeyLegacy, string.Empty))
                ? string.Empty
                : PlayerPrefs.GetString(PrefApiKeyLegacy, string.Empty).Trim();

            EnsureEventSystem();
            BuildRuntimeUi();
            ResolveRefs();
            BindRuntimeEvents();
            ApplyConnectionConfig(reconnect: true);
            RefreshAllStatusLines();
        }

        private void OnEnable()
        {
            ResolveRefs();
            BindRuntimeEvents();
            ApplyConnectionConfig(reconnect: true);
            if (_reachabilityCoroutine == null)
            {
                _reachabilityCoroutine = StartCoroutine(ReachabilityLoop());
            }

            if (_statusRefreshCoroutine == null)
            {
                _statusRefreshCoroutine = StartCoroutine(StatusRefreshLoop());
            }
        }

        private void OnDisable()
        {
            UnbindRuntimeEvents();
            if (_reachabilityCoroutine != null)
            {
                StopCoroutine(_reachabilityCoroutine);
                _reachabilityCoroutine = null;
            }

            if (_statusRefreshCoroutine != null)
            {
                StopCoroutine(_statusRefreshCoroutine);
                _statusRefreshCoroutine = null;
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

        private IEnumerator StatusRefreshLoop()
        {
            while (enabled)
            {
                RefreshAllStatusLines();
                yield return new WaitForSecondsRealtime(0.2f);
            }
        }

        private void ResolveRefs()
        {
            if (_gatewayClient == null)
            {
                _gatewayClient = FindFirstObjectByType<GatewayClient>();
            }

            if (_gatewayWsClient == null)
            {
                _gatewayWsClient = FindFirstObjectByType<GatewayWsClient>();
            }

            if (_scanController == null)
            {
                _scanController = FindFirstObjectByType<ScanController>();
            }

            if (_selfTestRunner == null)
            {
                _selfTestRunner = FindFirstObjectByType<ByesQuest3SelfTestRunner>();
            }
        }

        private void BindRuntimeEvents()
        {
            if (_gatewayClient != null)
            {
                _gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
                _gatewayClient.OnGatewayEvent += HandleGatewayEvent;
            }

            if (_scanController != null)
            {
                _scanController.OnUploadFinished -= HandleUploadFinished;
                _scanController.OnUploadFinished += HandleUploadFinished;
            }
        }

        private void UnbindRuntimeEvents()
        {
            if (_gatewayClient != null)
            {
                _gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            }

            if (_scanController != null)
            {
                _scanController.OnUploadFinished -= HandleUploadFinished;
            }
        }

        private void HandleUploadFinished(ScanController.UploadMetrics metrics)
        {
            if (metrics.Ok)
            {
                _scanStatus = "uploaded";
                _scanError = string.Empty;
                ShowToast("Scan OK");
            }
            else
            {
                _scanStatus = "failed";
                _scanError = string.IsNullOrWhiteSpace(metrics.Error) ? "upload failed" : metrics.Error;
                ShowToast($"Scan Failed: {_scanError}");
            }

            RefreshAllStatusLines();
        }

        private void HandleGatewayEvent(Newtonsoft.Json.Linq.JObject evt)
        {
            if (evt == null)
            {
                return;
            }

            var type = (evt.Value<string>("type") ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(type))
            {
                var name = (evt.Value<string>("name") ?? string.Empty).Trim();
                if (!string.IsNullOrWhiteSpace(name))
                {
                    type = name;
                }
                else
                {
                    var category = (evt.Value<string>("category") ?? string.Empty).Trim();
                    type = string.IsNullOrWhiteSpace(category) ? "event" : category;
                }
            }

            _lastEventType = type;
            _lastEventTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (string.Equals(_scanStatus, "sending", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(_scanStatus, "uploaded", StringComparison.OrdinalIgnoreCase))
            {
                _scanStatus = "event_received";
            }
            RefreshAllStatusLines();
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
            canvasRect.sizeDelta = new Vector2(1500f, 1050f);
            canvasRect.localScale = Vector3.one * 0.00025f;
            canvasRect.localPosition = Vector3.zero;
            canvasRect.localRotation = Quaternion.identity;

            canvasGo.AddComponent<CanvasScaler>();
            AddBestRaycaster(canvasGo);

            var panel = CreateUiObject("Panel", canvasGo.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(1500f, 1050f), Vector2.zero);
            var panelImage = panel.AddComponent<Image>();
            panelImage.color = new Color(0f, 0f, 0f, 0.8f);
            var panelGroup = panel.AddComponent<CanvasGroup>();
            panelGroup.blocksRaycasts = true;
            panelGroup.interactable = true;

            _ = CreateText("Title", panel.transform, "BYES Quest3 Smoke Panel", 46, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -64f), new Vector2(1320f, 80f));
            _baseUrlText = CreateText("BaseUrl", panel.transform, "-", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -140f), new Vector2(1320f, 64f));
            _reachabilityText = CreateText("Reachability", panel.transform, "HTTP: probing...", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -200f), new Vector2(1320f, 64f));
            _wsText = CreateText("WsStatus", panel.transform, "WS: disconnected", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -260f), new Vector2(1320f, 64f));
            _pingText = CreateText("Ping", panel.transform, "Ping RTT: -", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -320f), new Vector2(1320f, 64f));
            _versionText = CreateText("Version", panel.transform, "Version: -", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -380f), new Vector2(1320f, 64f));
            _modeText = CreateText("Mode", panel.transform, "Mode: -", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -440f), new Vector2(1320f, 64f));
            _lastUploadText = CreateText("Upload", panel.transform, "Last Upload: -", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -500f), new Vector2(1320f, 64f));
            _lastE2eText = CreateText("E2E", panel.transform, "Last E2E: -", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -560f), new Vector2(1320f, 64f));
            _lastEventText = CreateText("Event", panel.transform, "Last Event: -", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -620f), new Vector2(1320f, 64f));
            _scanStateText = CreateText("ScanState", panel.transform, "Scan: idle", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -680f), new Vector2(1320f, 64f));
            _selfTestText = CreateText("SelfTest", panel.transform, "SelfTest: IDLE", 34, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -740f), new Vector2(1320f, 64f));
            _toastText = CreateText("Toast", panel.transform, "-", 36, TextAnchor.MiddleCenter, new Vector2(0.5f, 0f), new Vector2(0f, 160f), new Vector2(1320f, 72f));
            _rawText = CreateText("Raw", panel.transform, "-", 28, TextAnchor.UpperLeft, new Vector2(0.5f, 0f), new Vector2(0f, 84f), new Vector2(1320f, 120f));

            CreateButton(panel.transform, "PingButton", "Ping", new Vector2(-520f, -900f), OnPingClicked);
            CreateButton(panel.transform, "VersionButton", "Version", new Vector2(-260f, -900f), OnVersionClicked);
            CreateButton(panel.transform, "ModeButton", "Mode", new Vector2(0f, -900f), OnModeClicked);
            _scanButton = CreateButton(panel.transform, "ScanButton", "Scan Once", new Vector2(260f, -900f), OnScanClicked);
            _liveButton = CreateButton(panel.transform, "LiveButton", "Live Start", new Vector2(520f, -900f), OnLiveClicked);
            CreateButton(panel.transform, "SelfTestButton", "SelfTest", new Vector2(-260f, -980f), OnSelfTestClicked);
            CreateButton(panel.transform, "ReconnectWsButton", "WS Reconnect", new Vector2(260f, -980f), OnReconnectWsClicked);
        }

        private void OnPingClicked()
        {
            StartCoroutine(SendPing(autoProbe: false));
        }

        private void OnVersionClicked()
        {
            StartCoroutine(QueryVersion());
        }

        private void OnModeClicked()
        {
            StartCoroutine(QueryMode());
        }

        private void OnScanClicked()
        {
            ResolveRefs();
            if (_scanController == null)
            {
                _scanStatus = "failed";
                _scanError = "scan-controller missing";
                ShowToast("Scan Failed: scan-controller missing");
                RefreshAllStatusLines();
                return;
            }

            _scanStatus = "sending";
            _scanError = string.Empty;
            _scanButton?.SetLabel("SCAN...");
            _scanController.ScanOnceFromUi();
            StartCoroutine(ResetButtonLabelAfterDelay(_scanButton, "Scan Once", 1.0f));
            RefreshAllStatusLines();
        }

        private void OnLiveClicked()
        {
            ResolveRefs();
            if (_scanController == null)
            {
                ShowToast("Live Failed: scan-controller missing");
                RefreshAllStatusLines();
                return;
            }

            _scanController.ToggleLiveFromUi();
            var liveNow = _scanController.IsLiveEnabled;
            _scanStatus = liveNow ? "live" : "idle";
            _liveButton?.SetLabel(liveNow ? "Live Stop" : "Live Start");
            ShowToast(liveNow ? "Live ON" : "Live OFF");
            RefreshAllStatusLines();
        }

        private void OnSelfTestClicked()
        {
            ResolveRefs();
            if (_selfTestRunner == null)
            {
                ShowToast("SelfTest Failed: runner missing");
                return;
            }

            _selfTestRunner.StartSelfTest();
            ShowToast("SelfTest RUNNING...");
        }

        private void OnReconnectWsClicked()
        {
            ResolveRefs();
            ApplyConnectionConfig(reconnect: true);
            if (_gatewayClient != null)
            {
                _gatewayClient.ConnectWebSocket();
            }

            ShowToast("WS reconnect requested");
            RefreshAllStatusLines();
        }

        private void ApplyConnectionConfig(bool reconnect)
        {
            ResolveRefs();
            if (_gatewayClient == null)
            {
                return;
            }

            var wsUrl = BuildWsUrl();
            _gatewayClient.SetApiKey(_apiKey, reconnect: false);
            _gatewayClient.SetGatewayEndpoints(_baseUrl, wsUrl, reconnect: reconnect);

            if (_gatewayWsClient != null)
            {
                _gatewayWsClient.SetConnectionConfig(wsUrl, _apiKey, reconnect: reconnect);
            }
        }

        private IEnumerator ResetButtonLabelAfterDelay(ILabelButton button, string label, float seconds)
        {
            if (button == null)
            {
                yield break;
            }

            yield return new WaitForSecondsRealtime(Mathf.Max(0.1f, seconds));
            button.SetLabel(label);
        }

        private IEnumerator SendPing(bool autoProbe)
        {
            var uri = $"{_baseUrl}/api/ping";
            var seq = _pingSeq++;
            var clientSendTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var body = $"{{\"deviceId\":\"quest3-smoke\",\"seq\":{seq},\"clientSendTsMs\":{clientSendTsMs}}}";
            var bodyBytes = System.Text.Encoding.UTF8.GetBytes(body);

            using var request = new UnityWebRequest(uri, UnityWebRequest.kHttpVerbPOST);
            request.uploadHandler = new UploadHandlerRaw(bodyBytes);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");
            ApplyApiKeyHeader(request);
            request.timeout = Mathf.CeilToInt(PingTimeoutSec);

            var start = Time.realtimeSinceStartupAsDouble;
            yield return request.SendWebRequest();
            var rttMs = Math.Max(0, Mathf.RoundToInt((float)((Time.realtimeSinceStartupAsDouble - start) * 1000.0)));

            if (request.result == UnityWebRequest.Result.Success)
            {
                _lastPingRttMs = rttMs;
                _reachabilityText.Set("HTTP: reachable");
                if (!autoProbe)
                {
                    ShowToast($"Ping OK ({rttMs} ms)");
                }
                RefreshAllStatusLines();
                yield break;
            }

            _reachabilityText.Set("HTTP: unreachable");
            if (!autoProbe)
            {
                ShowToast($"Ping failed: {request.error}");
            }
            RefreshAllStatusLines();
        }

        private IEnumerator QueryVersion()
        {
            var uri = $"{_baseUrl}/api/version";
            using var request = UnityWebRequest.Get(uri);
            ApplyApiKeyHeader(request);
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                _versionText.Set("Version: failed");
                _rawText.Set($"Version error: {request.error}");
                ShowToast("Version failed");
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
                    ShowToast("Version OK");
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
            ApplyApiKeyHeader(request);
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                _modeText.Set("Mode: failed");
                _rawText.Set($"Mode error: {request.error}");
                ShowToast("Mode failed");
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
                    ShowToast("Mode OK");
                    yield break;
                }
            }
            catch
            {
            }

            _modeText.Set("Mode: raw");
            _rawText.Set(payload);
        }

        private void RefreshAllStatusLines()
        {
            ResolveRefs();
            if (_scanController != null)
            {
                _liveButton?.SetLabel(_scanController.IsLiveEnabled ? "Live Stop" : "Live Start");
            }
            else
            {
                _liveButton?.SetLabel("Live Start");
            }

            var wsConnected = (_gatewayClient != null && _gatewayClient.IsConnected)
                              || (_gatewayWsClient != null && string.Equals(_gatewayWsClient.ConnectionState, "Connected", StringComparison.Ordinal));
            _baseUrlText.Set($"Base URL: {_baseUrl} (apiKey: {(string.IsNullOrWhiteSpace(_apiKey) ? "not-set" : "set")})");
            _wsText.Set($"WS: {(wsConnected ? "connected" : "disconnected")}");
            _pingText.Set(_lastPingRttMs >= 0 ? $"Ping RTT: {_lastPingRttMs} ms" : "Ping RTT: -");

            var uploadText = "Last Upload: -";
            var e2eText = "Last E2E: -";
            if (_scanController != null)
            {
                uploadText = _scanController.LastUploadCostMs >= 0
                    ? $"Last Upload: {_scanController.LastUploadCostMs:0} ms"
                    : "Last Upload: -";
                e2eText = _scanController.LastE2eMs >= 0
                    ? $"Last E2E: {_scanController.LastE2eMs:0} ms"
                    : "Last E2E: -";
            }
            _lastUploadText.Set(uploadText);
            _lastE2eText.Set(e2eText);

            var eventTs = _lastEventTsMs > 0 ? $" @{_lastEventTsMs}" : string.Empty;
            _lastEventText.Set($"Last Event: {_lastEventType}{eventTs}");

            var state = _scanController != null ? _scanController.LastScanState : _scanStatus;
            var err = _scanController != null ? _scanController.LastScanError : _scanError;
            _scanStateText.Set(string.IsNullOrWhiteSpace(err)
                ? $"Scan: {state}"
                : $"Scan: {state} ({err})");

            if (_selfTestRunner != null)
            {
                _selfTestStatus = _selfTestRunner.CurrentStatus;
                _selfTestSummary = _selfTestRunner.CurrentSummary;
            }
            _selfTestText.Set($"SelfTest: {_selfTestStatus} | {_selfTestSummary}");

            if (_toastUntilMs > 0 && DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() > _toastUntilMs)
            {
                _toastUntilMs = -1;
                _toastText.Set("-");
            }
        }

        private void ShowToast(string message)
        {
            _toastUntilMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 1800;
            _toastText.Set(string.IsNullOrWhiteSpace(message) ? "-" : message.Trim());
        }

        private static void EnsureEventSystem()
        {
            if (FindFirstObjectByType<EventSystem>() != null)
            {
                return;
            }

            var eventSystemGo = new GameObject("EventSystem", typeof(EventSystem));
            var xrUiType = Type.GetType("UnityEngine.XR.Interaction.Toolkit.UI.XRUIInputModule, Unity.XR.Interaction.Toolkit");
            if (xrUiType != null)
            {
                eventSystemGo.AddComponent(xrUiType);
                return;
            }

            var inputSystemModuleType = Type.GetType("UnityEngine.InputSystem.UI.InputSystemUIInputModule, Unity.InputSystem");
            if (inputSystemModuleType != null)
            {
                eventSystemGo.AddComponent(inputSystemModuleType);
                return;
            }

            eventSystemGo.AddComponent<StandaloneInputModule>();
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

        private ILabelButton CreateButton(Transform parent, string name, string label, Vector2 anchoredPos, Action onClick)
        {
            var buttonGo = CreateUiObject(name, parent, new Vector2(0.5f, 0f), new Vector2(0.5f, 0f), new Vector2(230f, 84f), anchoredPos);
            var image = buttonGo.AddComponent<Image>();
            image.color = new Color(0.22f, 0.55f, 0.94f, 0.95f);

            var button = buttonGo.AddComponent<Button>();
            button.targetGraphic = image;
            button.onClick.AddListener(() => onClick?.Invoke());

            var labelView = CreateText("Label", buttonGo.transform, label, 34, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(210f, 72f));
            return new RuntimeButton(button, labelView);
        }

        private void ApplyApiKeyHeader(UnityWebRequest request)
        {
            if (request == null || string.IsNullOrWhiteSpace(_apiKey))
            {
                return;
            }

            request.SetRequestHeader("X-BYES-API-Key", _apiKey.Trim());
        }

        private string BuildWsUrl()
        {
            if (!Uri.TryCreate(_baseUrl, UriKind.Absolute, out var uri))
            {
                return "ws://127.0.0.1:18000/ws/events";
            }

            var wsScheme = string.Equals(uri.Scheme, "https", StringComparison.OrdinalIgnoreCase) ? "wss" : "ws";
            var builder = new UriBuilder(uri)
            {
                Scheme = wsScheme,
                Path = "/ws/events",
            };
            return builder.Uri.ToString().TrimEnd('/');
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

        private interface ILabelButton
        {
            void SetLabel(string value);
        }

        private sealed class RuntimeButton : ILabelButton
        {
            private readonly Button _button;
            private readonly ITextView _label;

            public RuntimeButton(Button button, ITextView label)
            {
                _button = button;
                _label = label;
            }

            public void SetLabel(string value)
            {
                if (_button == null)
                {
                    return;
                }

                _label?.Set(value ?? string.Empty);
            }
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
            private readonly PropertyInfo _textProperty;
            private readonly PropertyInfo _fontSizeProperty;
            private readonly PropertyInfo _colorProperty;
            private readonly PropertyInfo _alignmentProperty;

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
                        // ignore package/version enum mismatch
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
