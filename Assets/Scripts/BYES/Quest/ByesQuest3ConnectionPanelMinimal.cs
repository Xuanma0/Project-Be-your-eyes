using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BYES.Core;
using BYES.Telemetry;
using BYES.UI;
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
        private const float ReachabilityIntervalSec = 5f;

        [Header("Quest Smoke Probe Profile")]
        [SerializeField] private bool applyLowOverheadGatewayProbeProfile = true;
        [SerializeField] private float lowOverheadHealthProbeIntervalSec = 5f;
        [SerializeField] private bool lowOverheadDisableReadinessProbe = true;
        [SerializeField] private bool showActionControlsOnAndroid = false;
        [SerializeField] private bool autoProbeOnAndroid = false;
        [SerializeField] private float defaultPanelDistance = 0.55f;
        [SerializeField] private float minPanelDistance = 0.35f;
        [SerializeField] private float maxPanelDistance = 1.5f;
        [SerializeField] private float defaultPanelScale = 1f;
        [SerializeField] private float minPanelScale = 0.7f;
        [SerializeField] private float maxPanelScale = 1.8f;

        private string _baseUrl = DefaultBaseUrl;
        private string _apiKey = string.Empty;
        private int _pingSeq;
        private int _modeSeq = 1;
        private long _lastPingRttMs = -1;
        private long _lastEventTsMs = -1;
        private string _lastEventType = "-";
        private string _scanStatus = "idle";
        private string _scanError = string.Empty;
        private string _selfTestStatus = "IDLE";
        private string _selfTestSummary = "-";
        private string _currentMode = "-";
        private long _toastUntilMs = -1;
        private bool _autoProbeEnabled = true;
        private Coroutine _reachabilityCoroutine;
        private Coroutine _statusRefreshCoroutine;

        private GatewayClient _gatewayClient;
        private GatewayWsClient _gatewayWsClient;
        private ScanController _scanController;
        private ByesQuest3SelfTestRunner _selfTestRunner;
        private ByesHitchMonitor _hitchMonitor;
        private ByesHeadLockedPanel _headLockedPanel;

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
        private ITextView _captureText;
        private ITextView _hitchText;
        private ITextView _toastText;
        private ITextView _rawText;
        private ILabelButton _liveButton;
        private ILabelButton _scanButton;
        private readonly List<GameObject> _actionControls = new List<GameObject>();
        private Canvas _runtimeCanvas;
        private bool _rawVisible = true;
        private bool _actionControlsVisible = true;

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
            ApplyPanelPresentationDefaults();
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
                if (_autoProbeEnabled)
                {
                    yield return SendPing(autoProbe: true);
                }
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

            if (_hitchMonitor == null)
            {
                _hitchMonitor = FindFirstObjectByType<ByesHitchMonitor>();
                if (_hitchMonitor == null)
                {
                    var host = new GameObject("BYES_HitchMonitor");
                    _hitchMonitor = host.AddComponent<ByesHitchMonitor>();
                }
            }

            if (_headLockedPanel == null)
            {
                _headLockedPanel = GetComponent<ByesHeadLockedPanel>();
            }
        }

        private void ApplyPanelPresentationDefaults()
        {
            _autoProbeEnabled = Application.platform == RuntimePlatform.Android
                ? autoProbeOnAndroid
                : true;

            if (_headLockedPanel != null)
            {
                _headLockedPanel.SetDistance(defaultPanelDistance);
                _headLockedPanel.SetPinned(false);
            }

            SetPanelScale(defaultPanelScale);
            var showActions = Application.platform == RuntimePlatform.Android ? showActionControlsOnAndroid : true;
            SetActionControlsVisible(showActions);
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
            _runtimeCanvas = canvas;

            var canvasRect = canvasGo.GetComponent<RectTransform>();
            canvasRect.sizeDelta = new Vector2(1650f, 1180f);
            canvasRect.localScale = Vector3.one * 0.00025f;
            canvasRect.localPosition = Vector3.zero;
            canvasRect.localRotation = Quaternion.identity;

            canvasGo.AddComponent<CanvasScaler>();
            AddBestRaycaster(canvasGo);

            var panel = CreateUiObject("Panel", canvasGo.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(1650f, 1180f), Vector2.zero);
            var panelImage = panel.AddComponent<Image>();
            panelImage.color = new Color(0f, 0f, 0f, 0.8f);
            var panelGroup = panel.AddComponent<CanvasGroup>();
            panelGroup.blocksRaycasts = true;
            panelGroup.interactable = true;

            _ = CreateText("Title", panel.transform, "BYES Quest3 Smoke Panel", 46, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -64f), new Vector2(1480f, 80f));
            _baseUrlText = CreateText("BaseUrl", panel.transform, "-", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -138f), new Vector2(1480f, 62f));
            _reachabilityText = CreateText("Reachability", panel.transform, "HTTP: probing...", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -194f), new Vector2(1480f, 62f));
            _wsText = CreateText("WsStatus", panel.transform, "WS: disconnected", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -250f), new Vector2(1480f, 62f));
            _pingText = CreateText("Ping", panel.transform, "Ping RTT: -", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -306f), new Vector2(1480f, 62f));
            _versionText = CreateText("Version", panel.transform, "Version: -", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -362f), new Vector2(1480f, 62f));
            _modeText = CreateText("Mode", panel.transform, "Mode: -", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -418f), new Vector2(1480f, 62f));
            _lastUploadText = CreateText("Upload", panel.transform, "Last Upload: -", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -474f), new Vector2(1480f, 62f));
            _lastE2eText = CreateText("E2E", panel.transform, "Last E2E: -", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -530f), new Vector2(1480f, 62f));
            _lastEventText = CreateText("Event", panel.transform, "Last Event: -", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -586f), new Vector2(1480f, 62f));
            _scanStateText = CreateText("ScanState", panel.transform, "Scan: idle", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -642f), new Vector2(1480f, 62f));
            _selfTestText = CreateText("SelfTest", panel.transform, "SelfTest: IDLE", 32, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -698f), new Vector2(1480f, 62f));
            _captureText = CreateText("CaptureStats", panel.transform, "Capture: -", 30, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -754f), new Vector2(1480f, 62f));
            _hitchText = CreateText("HitchStats", panel.transform, "Hitch30s: -", 30, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -808f), new Vector2(1480f, 62f));
            _toastText = CreateText("Toast", panel.transform, "-", 34, TextAnchor.MiddleCenter, new Vector2(0.5f, 0f), new Vector2(0f, 168f), new Vector2(1480f, 72f));
            _rawText = CreateText("Raw", panel.transform, "-", 26, TextAnchor.UpperLeft, new Vector2(0.5f, 0f), new Vector2(0f, 96f), new Vector2(1480f, 124f));

            CreateButton(panel.transform, "PingButton", "Ping", new Vector2(-650f, -1030f), OnPingClicked, markAsAction: true);
            CreateButton(panel.transform, "VersionButton", "Version", new Vector2(-420f, -1030f), OnVersionClicked, markAsAction: true);
            CreateButton(panel.transform, "ModeReadButton", "Read", new Vector2(-190f, -1030f), () => OnSetModeClicked("read_text"), markAsAction: true);
            CreateButton(panel.transform, "ModeWalkButton", "Walk", new Vector2(40f, -1030f), () => OnSetModeClicked("walk"), markAsAction: true);
            CreateButton(panel.transform, "ModeInspectButton", "Inspect", new Vector2(270f, -1030f), () => OnSetModeClicked("inspect"), markAsAction: true);
            _scanButton = CreateButton(panel.transform, "ScanButton", "Scan Once", new Vector2(500f, -1030f), OnScanClicked, markAsAction: true);
            _liveButton = CreateButton(panel.transform, "LiveButton", "Live Start", new Vector2(730f, -1030f), OnLiveClicked, markAsAction: true);

            CreateButton(panel.transform, "RefreshButton", "Refresh", new Vector2(-420f, -1110f), OnRefreshClicked, markAsAction: true);
            CreateButton(panel.transform, "SelfTestButton", "SelfTest", new Vector2(-190f, -1110f), OnSelfTestClicked, markAsAction: true);
            CreateButton(panel.transform, "ReconnectWsButton", "WS Reconnect", new Vector2(40f, -1110f), OnReconnectWsClicked, markAsAction: true);
        }

        private void OnPingClicked()
        {
            StartCoroutine(SendPing(autoProbe: false));
        }

        private void OnVersionClicked()
        {
            StartCoroutine(QueryVersion());
        }

        private void OnSetModeClicked(string mode)
        {
            StartCoroutine(SetMode(mode));
        }

        private void OnRefreshClicked()
        {
            StartCoroutine(RefreshNow());
        }

        private IEnumerator RefreshNow()
        {
            yield return SendPing(autoProbe: false);
            yield return QueryVersion();
            yield return QueryMode();
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

            _autoProbeEnabled = true;
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

        public bool IsPanelVisible()
        {
            return _runtimeCanvas == null || _runtimeCanvas.enabled;
        }

        public bool IsActionControlsVisible()
        {
            return _actionControlsVisible;
        }

        public bool IsPinned()
        {
            return _headLockedPanel != null && _headLockedPanel.IsPinned;
        }

        public float GetPanelDistance()
        {
            return _headLockedPanel != null ? _headLockedPanel.Distance : defaultPanelDistance;
        }

        public float GetPanelScale()
        {
            return transform.localScale.x;
        }

        public void SetPanelVisible(bool visible)
        {
            if (_runtimeCanvas != null)
            {
                _runtimeCanvas.enabled = visible;
            }
        }

        public void SetActionControlsVisible(bool visible)
        {
            _actionControlsVisible = visible;
            for (var i = 0; i < _actionControls.Count; i += 1)
            {
                if (_actionControls[i] != null)
                {
                    _actionControls[i].SetActive(visible);
                }
            }
        }

        public void SetPanelScale(float scale)
        {
            var clamped = Mathf.Clamp(scale, minPanelScale, maxPanelScale);
            transform.localScale = Vector3.one * clamped;
        }

        public void SetPanelDistance(float distance)
        {
            if (_headLockedPanel == null)
            {
                return;
            }

            var clamped = Mathf.Clamp(distance, minPanelDistance, maxPanelDistance);
            _headLockedPanel.SetDistance(clamped);
        }

        public void SetPinned(bool pinned)
        {
            if (_headLockedPanel == null)
            {
                return;
            }

            _headLockedPanel.SetPinned(pinned);
        }

        public void SnapToDefaultPose()
        {
            if (_headLockedPanel != null)
            {
                _headLockedPanel.SetDistance(defaultPanelDistance);
                _headLockedPanel.SetPinned(false);
                _headLockedPanel.SnapToDefault();
            }

            SetPanelScale(defaultPanelScale);
            RefreshAllStatusLines();
        }

        public void ToggleRawDebugText()
        {
            _rawVisible = !_rawVisible;
            RefreshAllStatusLines();
        }

        public void ToggleOverlayVisible()
        {
            var overlay = FindFirstObjectByType<ByesOverlayRenderer>();
            if (overlay == null)
            {
                overlay = ByesOverlayRenderer.Instance;
            }

            if (overlay == null)
            {
                ShowToast("Overlay missing");
                return;
            }

            if (overlay.enabled && overlay.gameObject.activeInHierarchy)
            {
                overlay.Hide();
                overlay.enabled = false;
                ShowToast("Overlay OFF");
            }
            else
            {
                overlay.enabled = true;
                ShowToast("Overlay ON");
            }
        }

        public void TriggerPingFromUi()
        {
            OnPingClicked();
        }

        public void TriggerVersionFromUi()
        {
            OnVersionClicked();
        }

        public void TriggerModeReadFromUi()
        {
            StartCoroutine(QueryMode());
        }

        public void TriggerSelfTestFromUi()
        {
            OnSelfTestClicked();
        }

        public void TriggerScanOnceFromUi()
        {
            OnScanClicked();
        }

        public void TriggerToggleLiveFromUi()
        {
            OnLiveClicked();
        }

        public void TriggerRefreshFromUi()
        {
            OnRefreshClicked();
        }

        public void TriggerSetModeWalk()
        {
            StartCoroutine(SetMode("walk"));
        }

        public void TriggerSetModeRead()
        {
            StartCoroutine(SetMode("read_text"));
        }

        public void TriggerSetModeInspect()
        {
            StartCoroutine(SetMode("inspect"));
        }

        public void TriggerCycleMode()
        {
            var manager = ByesModeManager.Instance;
            if (manager == null)
            {
                StartCoroutine(SetMode("walk"));
                return;
            }

            var current = manager.GetMode();
            var next = current switch
            {
                ByesMode.Walk => ByesMode.ReadText,
                ByesMode.ReadText => ByesMode.Inspect,
                _ => ByesMode.Walk,
            };
            manager.SetMode(next, "xr");
            StartCoroutine(SetMode(ByesModeManager.ToApiMode(next)));
        }

        public string BuildDebugSummary()
        {
            return
                $"baseUrl={_baseUrl}\n" +
                $"http={(_lastPingRttMs >= 0 ? "reachable" : "unknown")} rttMs={_lastPingRttMs}\n" +
                $"ws={(_gatewayClient != null && _gatewayClient.IsConnected ? "connected" : "disconnected")}\n" +
                $"mode={_currentMode}\n" +
                $"scan={_scanStatus} err={_scanError}\n" +
                $"event={_lastEventType} ts={_lastEventTsMs}\n" +
                $"selfTest={_selfTestStatus} summary={_selfTestSummary}\n" +
                $"hitch={(_hitchMonitor != null ? _hitchMonitor.HitchCount30s : -1)}";
        }

        public string ExportDebugText()
        {
            var path = Path.Combine(Application.persistentDataPath, "byes_quest3_debug.txt");
            File.WriteAllText(path, BuildDebugSummary());
            ShowToast("Debug exported");
            return path;
        }

        private void ApplyConnectionConfig(bool reconnect)
        {
            ResolveRefs();
            if (_gatewayClient == null)
            {
                return;
            }

            if (applyLowOverheadGatewayProbeProfile)
            {
                _gatewayClient.ConfigureProbeRuntime(
                    enableHealth: true,
                    healthIntervalSec: Mathf.Max(1f, lowOverheadHealthProbeIntervalSec),
                    enableReadiness: !lowOverheadDisableReadinessProbe,
                    readinessIntervalSec: Mathf.Max(2f, lowOverheadHealthProbeIntervalSec),
                    restartLoop: true);
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
            var body = $"{{\"deviceId\":\"{ByesFrameTelemetry.DeviceId}\",\"seq\":{seq},\"clientSendTsMs\":{clientSendTsMs}}}";
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
            var uri = $"{_baseUrl}/api/mode?deviceId={UnityWebRequest.EscapeURL(ByesFrameTelemetry.DeviceId)}";
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
                    _currentMode = parsed.mode.Trim();
                    _modeText.Set($"Mode: {_currentMode}");
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

        private IEnumerator SetMode(string mode)
        {
            var normalized = NormalizeMode(mode);
            var uri = $"{_baseUrl}/api/mode";
            var tsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var safeFrameSeq = Math.Max(1, _modeSeq++);
            var body =
                "{" +
                "\"runId\":\"quest3-smoke\"," +
                $"\"frameSeq\":{safeFrameSeq}," +
                $"\"mode\":\"{normalized}\"," +
                "\"source\":\"xr\"," +
                $"\"tsMs\":{tsMs}," +
                $"\"deviceId\":\"{ByesFrameTelemetry.DeviceId}\"" +
                "}";

            using var request = new UnityWebRequest(uri, UnityWebRequest.kHttpVerbPOST);
            request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(body));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            request.SetRequestHeader("Content-Type", "application/json");
            ApplyApiKeyHeader(request);

            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                _rawText.Set($"Set mode error: {request.error}");
                ShowToast($"Set mode failed: {request.error}");
                yield break;
            }

            ShowToast($"Set mode -> {normalized}");
            yield return QueryMode();
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
            var captureText = "Capture: -";
            if (_scanController != null)
            {
                uploadText = _scanController.LastUploadCostMs >= 0
                    ? $"Last Upload: {_scanController.LastUploadCostMs:0} ms"
                    : "Last Upload: -";
                e2eText = _scanController.LastE2eMs >= 0
                    ? $"Last E2E: {_scanController.LastE2eMs:0} ms"
                    : "Last E2E: -";
                captureText =
                    $"CaptureHz: {_scanController.CaptureTargetHz} | Inflight: {_scanController.InflightCount}/{_scanController.LiveMaxInflight} | ReadbackReq: {_scanController.CaptureActiveReadbacks} | Async: {(_scanController.CaptureAsyncReadbackEnabled ? "ON" : "OFF")} / {(_scanController.CaptureSupportsAsyncReadback ? "supported" : "unsupported")}";
            }
            _lastUploadText.Set(uploadText);
            _lastE2eText.Set(e2eText);
            _captureText.Set(captureText);

            if (_hitchMonitor != null)
            {
                _hitchText.Set($"Hitch30s: {_hitchMonitor.HitchCount30s} | WorstDt: {_hitchMonitor.WorstDt30sMs:0.0}ms | AvgDt: {_hitchMonitor.AvgDt30sMs:0.0}ms | GC0/1/2 d: {_hitchMonitor.Gc0Delta}/{_hitchMonitor.Gc1Delta}/{_hitchMonitor.Gc2Delta}");
            }
            else
            {
                _hitchText.Set("Hitch30s: monitor missing");
            }

            var eventTs = _lastEventTsMs > 0 ? $" @{_lastEventTsMs}" : string.Empty;
            _lastEventText.Set($"Last Event: {_lastEventType}{eventTs}");

            var state = _scanController != null ? _scanController.LastScanState : _scanStatus;
            var err = _scanController != null ? _scanController.LastScanError : _scanError;
            _scanStateText.Set(string.IsNullOrWhiteSpace(err)
                ? $"Scan: {state} | pinned={IsPinned()} | controls={(_actionControlsVisible ? "on" : "off")}"
                : $"Scan: {state} ({err}) | pinned={IsPinned()} | controls={(_actionControlsVisible ? "on" : "off")}");

            if (_selfTestRunner != null)
            {
                _selfTestStatus = _selfTestRunner.CurrentStatus;
                _selfTestSummary = _selfTestRunner.CurrentSummary;
            }
            _selfTestText.Set($"SelfTest: {_selfTestStatus} | {_selfTestSummary}");

            if (!_rawVisible)
            {
                _rawText.Set("(debug hidden)");
            }

            if (string.Equals(_selfTestStatus, "PASS", StringComparison.OrdinalIgnoreCase)
                || string.Equals(_selfTestStatus, "FAIL", StringComparison.OrdinalIgnoreCase))
            {
                _autoProbeEnabled = false;
            }

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

        private ILabelButton CreateButton(Transform parent, string name, string label, Vector2 anchoredPos, Action onClick, bool markAsAction = false)
        {
            var buttonGo = CreateUiObject(name, parent, new Vector2(0.5f, 0f), new Vector2(0.5f, 0f), new Vector2(210f, 74f), anchoredPos);
            var image = buttonGo.AddComponent<Image>();
            image.color = new Color(0.22f, 0.55f, 0.94f, 0.95f);

            var button = buttonGo.AddComponent<Button>();
            button.targetGraphic = image;
            button.onClick.AddListener(() => onClick?.Invoke());

            var labelView = CreateText("Label", buttonGo.transform, label, 30, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(190f, 64f));
            if (markAsAction)
            {
                _actionControls.Add(buttonGo);
            }
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

        private static string NormalizeMode(string mode)
        {
            var normalized = string.IsNullOrWhiteSpace(mode) ? "walk" : mode.Trim().ToLowerInvariant();
            switch (normalized)
            {
                case "walk":
                case "read_text":
                case "inspect":
                    return normalized;
                default:
                    return "walk";
            }
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
            private string _lastValue = string.Empty;

            public UguiTextView(Text text)
            {
                _text = text;
            }

            public void Set(string value)
            {
                var resolved = value ?? string.Empty;
                if (string.Equals(_lastValue, resolved, StringComparison.Ordinal))
                {
                    return;
                }

                _lastValue = resolved;
                if (_text != null)
                {
                    _text.text = resolved;
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
            private string _lastValue = string.Empty;

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
                var resolved = value ?? string.Empty;
                if (string.Equals(_lastValue, resolved, StringComparison.Ordinal))
                {
                    return;
                }

                _lastValue = resolved;
                if (_textProperty != null)
                {
                    _textProperty.SetValue(_component, resolved, null);
                }
            }
        }
    }
}
