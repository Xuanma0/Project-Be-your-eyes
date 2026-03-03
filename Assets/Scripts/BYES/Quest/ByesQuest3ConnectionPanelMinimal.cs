using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using BYES.Core;
using BYES.Guidance;
using BYES.Telemetry;
using BYES.UI;
using BYES.XR;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Presenters.Audio;
using BeYourEyes.Unity.Interaction;
using Newtonsoft.Json.Linq;
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
        private const string PrefQuestDeviceId = "BYES_QUEST_DEVICE_ID";
        private const string PrefAutoSpeakOcr = "BYES_AUTOSPEAK_OCR";
        private const string PrefAutoSpeakDet = "BYES_AUTOSPEAK_DET";
        private const string PrefAutoSpeakRisk = "BYES_AUTOSPEAK_RISK";
        private const string PrefAutoSpeakFind = "BYES_AUTOSPEAK_FIND";
        private const string PrefAutoGuidance = "BYES_AUTO_GUIDANCE";
        private const string PrefOcrVerbose = "BYES_OCR_VERBOSE";
        private const string PrefGuidanceAudio = "BYES_GUIDANCE_AUDIO";
        private const string PrefGuidanceHaptics = "BYES_GUIDANCE_HAPTICS";
        private const string PrefGuidanceRateSec = "BYES_GUIDANCE_RATE_SEC";
        private const string PrefAutoVoiceCommand = "BYES_AUTO_VOICE_COMMAND";
        private const string DefaultBaseUrl = "http://127.0.0.1:18000";

        private const float PingTimeoutSec = 2f;
        private const float QueryTimeoutSec = 3f;
        private const float ReachabilityIntervalSec = 10f;
        private const float CapabilitiesRefreshIntervalSec = 30f;

        [Header("Quest Smoke Probe Profile")]
        [SerializeField] private bool applyLowOverheadGatewayProbeProfile = true;
        [SerializeField] private float lowOverheadHealthProbeIntervalSec = 5f;
        [SerializeField] private bool lowOverheadDisableReadinessProbe = true;
        [SerializeField] private bool showActionControlsOnAndroid = false;
        [SerializeField] private bool autoProbeOnAndroid = true;
        [SerializeField] private float defaultPanelDistance = 0.55f;
        [SerializeField] private float minPanelDistance = 0.35f;
        [SerializeField] private float maxPanelDistance = 1.5f;
        [SerializeField] private float defaultPanelScale = 1f;
        [SerializeField] private float minPanelScale = 0.7f;
        [SerializeField] private float maxPanelScale = 1.8f;

        private string _baseUrl = DefaultBaseUrl;
        private string _apiKey = string.Empty;
        private string _deviceId = string.Empty;
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
        private string _lastOcrText = "-";
        private long _lastOcrTsMs = -1;
        private string _lastDetText = "-";
        private long _lastDetTsMs = -1;
        private string _lastRiskText = "-";
        private long _lastRiskTsMs = -1;
        private string _lastFindText = "-";
        private long _lastFindTsMs = -1;
        private string _guidanceText = "-";
        private long _lastGuidanceTsMs = -1;
        private string _lastTargetText = "-";
        private long _lastTargetTsMs = -1;
        private string _lastAsrText = "-";
        private long _lastAsrTsMs = -1;
        private string _lastTtsText = "-";
        private long _lastTtsTsMs = -1;
        private string _providerSummary = "providers: -";
        private string _providerDetail = "-";
        private long _providerTsMs = -1;
        private long _lastCapabilitiesFetchTsMs = -1;
        private string _pendingFindPrompt = string.Empty;
        private long _pendingFindPromptTsMs = -1;
        private long _toastUntilMs = -1;
        private bool _autoProbeEnabled = true;
        private bool _autoSpeakOcr;
        private bool _autoSpeakDet;
        private bool _autoSpeakRisk;
        private bool _autoSpeakFind;
        private bool _autoGuidance;
        private bool _ocrVerbose;
        private bool _guidanceAudioEnabled;
        private bool _guidanceHapticsEnabled;
        private bool _autoVoiceCommandEnabled;
        private float _guidanceRateSec = 0.4f;
        private long _lastSpokenAtMs = -1;
        private string _lastSpokenDigest = string.Empty;
        private Coroutine _reachabilityCoroutine;
        private Coroutine _statusRefreshCoroutine;

        private readonly Queue<long> _probeRequestTsMs = new Queue<long>();

        private GatewayClient _gatewayClient;
        private GatewayWsClient _gatewayWsClient;
        private ScanController _scanController;
        private ByesQuest3SelfTestRunner _selfTestRunner;
        private ByesHitchMonitor _hitchMonitor;
        private SpeechOrchestrator _speechOrchestrator;
        private AndroidTtsBackend _localTtsBackend;
        private bool _localTtsReady;
        private bool _localTtsInitAttempted;
        private ByesHeadLockedPanel _headLockedPanel;
        private ByesSmokePanelGrabHandle _grabHandle;
        private ByesHandGestureShortcuts _shortcuts;
        private ByesGuidanceEngine _guidanceEngine;
        private ByesSpatialAudioCue _guidanceAudioCue;
        private ByesHapticsCue _guidanceHapticsCue;
        private ByesPassthroughController _passthroughController;
        private ByesRoiPanelController _roiPanelController;
        private ByesVisionHudController _visionHud;
        private ByesVoiceCommandRouter _voiceCommandRouter;
        private AudioSource _beepAudioSource;
        private AudioClip _beepClip;
        private bool _voiceRecordingActive;
        private AudioClip _voiceMicClip;
        private int _voiceMicFrequency = 16000;
        private string _voiceMicDevice = null;
        private float _voiceRecordingStartRealtime;
        private bool _recordingActive;
        private string _targetSessionId = string.Empty;
        private string _targetTracker = "botsort";
        private readonly JObject _selectedRoi = new JObject
        {
            ["x"] = 0.35f,
            ["y"] = 0.35f,
            ["w"] = 0.3f,
            ["h"] = 0.3f,
        };

        private ITextView _baseUrlText;
        private ITextView _reachabilityText;
        private ITextView _wsText;
        private ITextView _pingText;
        private ITextView _versionText;
        private ITextView _modeText;
        private ITextView _lastUploadText;
        private ITextView _lastE2eText;
        private ITextView _lastEventText;
        private ITextView _lastOcrTextView;
        private ITextView _lastDetTextView;
        private ITextView _lastRiskTextView;
        private ITextView _lastFindTextView;
        private ITextView _lastTargetTextView;
        private ITextView _guidanceTextView;
        private ITextView _lastAsrTextView;
        private ITextView _lastTtsTextView;
        private ITextView _hudStatsTextView;
        private ITextView _scanStateText;
        private ITextView _selfTestText;
        private ITextView _captureText;
        private ITextView _hitchText;
        private ITextView _toastText;
        private ITextView _rawText;
        private ILabelButton _liveButton;
        private ILabelButton _scanButton;
        private Toggle _liveToggle;
        private bool _suppressLiveToggleCallback;
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
            _deviceId = ResolveStableDeviceId();
            _autoSpeakOcr = PlayerPrefs.GetInt(PrefAutoSpeakOcr, 1) == 1;
            _autoSpeakDet = PlayerPrefs.GetInt(PrefAutoSpeakDet, 0) == 1;
            _autoSpeakRisk = PlayerPrefs.GetInt(PrefAutoSpeakRisk, 1) == 1;
            _autoSpeakFind = PlayerPrefs.GetInt(PrefAutoSpeakFind, 0) == 1;
            _autoGuidance = PlayerPrefs.GetInt(PrefAutoGuidance, 1) == 1;
            _ocrVerbose = PlayerPrefs.GetInt(PrefOcrVerbose, 0) == 1;
            _guidanceAudioEnabled = PlayerPrefs.GetInt(PrefGuidanceAudio, 1) == 1;
            _guidanceHapticsEnabled = PlayerPrefs.GetInt(PrefGuidanceHaptics, 0) == 1;
            _autoVoiceCommandEnabled = PlayerPrefs.GetInt(PrefAutoVoiceCommand, 1) == 1;
            _guidanceRateSec = Mathf.Clamp(PlayerPrefs.GetFloat(PrefGuidanceRateSec, 0.4f), 0.2f, 1.2f);

            EnsureEventSystem();
            BuildRuntimeUi();
            ResolveRefs();
            BindRuntimeEvents();
            ApplyPanelPresentationDefaults();
            ApplyConnectionConfig(reconnect: true);
            StartCoroutine(QueryCapabilities(silent: true));
            RefreshAllStatusLines();
        }

        private void OnEnable()
        {
            ResolveRefs();
            BindRuntimeEvents();
            ApplyConnectionConfig(reconnect: true);
            if (ShouldRefreshCapabilities())
            {
                StartCoroutine(QueryCapabilities(silent: true));
            }
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
            if (_localTtsBackend != null)
            {
                _localTtsBackend.Shutdown();
                _localTtsBackend = null;
                _localTtsReady = false;
                _localTtsInitAttempted = false;
            }
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
                    if (ShouldRefreshCapabilities())
                    {
                        yield return QueryCapabilities(silent: true);
                    }
                }
                yield return new WaitForSecondsRealtime(ReachabilityIntervalSec);
            }
        }

        private IEnumerator StatusRefreshLoop()
        {
            while (enabled)
            {
                RefreshAllStatusLines();
                yield return new WaitForSecondsRealtime(0.5f);
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

            if (_grabHandle == null)
            {
                _grabHandle = GetComponent<ByesSmokePanelGrabHandle>();
            }

            if (_shortcuts == null)
            {
                _shortcuts = FindFirstObjectByType<ByesHandGestureShortcuts>();
            }

            if (_guidanceEngine == null)
            {
                _guidanceEngine = FindFirstObjectByType<ByesGuidanceEngine>();
                if (_guidanceEngine == null)
                {
                    _guidanceEngine = gameObject.AddComponent<ByesGuidanceEngine>();
                }
            }

            if (_guidanceAudioCue == null)
            {
                _guidanceAudioCue = FindFirstObjectByType<ByesSpatialAudioCue>();
                if (_guidanceAudioCue == null)
                {
                    _guidanceAudioCue = gameObject.AddComponent<ByesSpatialAudioCue>();
                }
            }

            if (_guidanceHapticsCue == null)
            {
                _guidanceHapticsCue = FindFirstObjectByType<ByesHapticsCue>();
                if (_guidanceHapticsCue == null)
                {
                    _guidanceHapticsCue = gameObject.AddComponent<ByesHapticsCue>();
                }
            }
            ApplyGuidanceRate();

            if (_passthroughController == null)
            {
                _passthroughController = FindFirstObjectByType<ByesPassthroughController>();
                if (_passthroughController == null)
                {
                    var host = new GameObject("BYES_PassthroughController");
                    _passthroughController = host.AddComponent<ByesPassthroughController>();
                }
            }

            if (_roiPanelController == null)
            {
                _roiPanelController = FindFirstObjectByType<ByesRoiPanelController>();
                if (_roiPanelController == null)
                {
                    var host = new GameObject("BYES_RoiPanelController");
                    _roiPanelController = host.AddComponent<ByesRoiPanelController>();
                }
            }

            if (_visionHud == null)
            {
                _visionHud = FindFirstObjectByType<ByesVisionHudController>();
                if (_visionHud == null)
                {
                    _visionHud = GetComponent<ByesVisionHudController>();
                }
                if (_visionHud == null)
                {
                    _visionHud = gameObject.AddComponent<ByesVisionHudController>();
                }
            }

            if (_voiceCommandRouter == null)
            {
                _voiceCommandRouter = FindFirstObjectByType<ByesVoiceCommandRouter>();
                if (_voiceCommandRouter == null)
                {
                    _voiceCommandRouter = gameObject.GetComponent<ByesVoiceCommandRouter>();
                }
                if (_voiceCommandRouter == null)
                {
                    _voiceCommandRouter = gameObject.AddComponent<ByesVoiceCommandRouter>();
                }
            }

            if (_beepAudioSource == null)
            {
                _beepAudioSource = gameObject.GetComponent<AudioSource>();
                if (_beepAudioSource == null)
                {
                    _beepAudioSource = gameObject.AddComponent<AudioSource>();
                    _beepAudioSource.playOnAwake = false;
                    _beepAudioSource.spatialBlend = 0f;
                    _beepAudioSource.volume = 1f;
                }
            }
            if (_beepClip == null)
            {
                _beepClip = BuildBeepClip();
            }

            if (_speechOrchestrator == null)
            {
                _speechOrchestrator = FindFirstObjectByType<SpeechOrchestrator>();
                if (_speechOrchestrator == null)
                {
                    var bootstrap = FindFirstObjectByType<BeYourEyes.AppBootstrap>();
                    var host = bootstrap != null ? bootstrap.gameObject : gameObject;
                    _speechOrchestrator = host.GetComponent<SpeechOrchestrator>();
                    if (_speechOrchestrator == null)
                    {
                        _speechOrchestrator = host.AddComponent<SpeechOrchestrator>();
                    }
                }
            }

            if (!_localTtsInitAttempted)
            {
                _localTtsInitAttempted = true;
                try
                {
                    _localTtsBackend = new AndroidTtsBackend();
                    _localTtsReady = _localTtsBackend.Initialize(this, 1.0f, 1.0f);
                }
                catch
                {
                    _localTtsReady = false;
                }
            }
        }

        private void ApplyPanelPresentationDefaults()
        {
            _autoProbeEnabled = Application.platform == RuntimePlatform.Android
                ? true
                : autoProbeOnAndroid;

            if (_headLockedPanel != null)
            {
                _headLockedPanel.SetDistance(defaultPanelDistance);
                _headLockedPanel.SetPinned(false);
            }

            SetPanelScale(defaultPanelScale);
            var showActions = Application.platform == RuntimePlatform.Android ? showActionControlsOnAndroid : true;
            SetActionControlsVisible(showActions);

            if (_autoProbeEnabled && isActiveAndEnabled)
            {
                StartCoroutine(SendPing(autoProbe: true));
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

            if (_shortcuts != null)
            {
                _shortcuts.OnShortcutTriggered -= HandleShortcutTriggered;
                _shortcuts.OnShortcutTriggered += HandleShortcutTriggered;
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

            if (_shortcuts != null)
            {
                _shortcuts.OnShortcutTriggered -= HandleShortcutTriggered;
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
            var lowered = _lastEventType.Trim().ToLowerInvariant();
            var payload = evt["payload"] as JObject;
            if (string.Equals(lowered, "ocr.read", StringComparison.Ordinal)
                || string.Equals(lowered, "ocr", StringComparison.Ordinal))
            {
                UpdateOcrFromEvent(payload);
            }
            else if (string.Equals(lowered, "det.objects", StringComparison.Ordinal)
                     || string.Equals(lowered, "det.objects.v1", StringComparison.Ordinal)
                     || string.Equals(lowered, "det", StringComparison.Ordinal))
            {
                UpdateDetFromEvent(payload);
            }
            else if (string.Equals(lowered, "risk.fused", StringComparison.Ordinal)
                     || string.Equals(lowered, "risk.hazards", StringComparison.Ordinal))
            {
                UpdateRiskFromEvent(payload, lowered);
            }
            else if (string.Equals(lowered, "target.update", StringComparison.Ordinal))
            {
                UpdateTargetFromEvent(payload);
            }
            else if (string.Equals(lowered, "target.session", StringComparison.Ordinal))
            {
                UpdateTargetSessionFromEvent(payload);
            }
            else if (string.Equals(lowered, "asr.transcript.v1", StringComparison.Ordinal))
            {
                UpdateAsrFromEvent(payload);
            }
            if (string.Equals(_scanStatus, "sending", StringComparison.OrdinalIgnoreCase) ||
                string.Equals(_scanStatus, "uploaded", StringComparison.OrdinalIgnoreCase))
            {
                _scanStatus = "event_received";
            }
            RefreshAllStatusLines();
        }

        private void HandleShortcutTriggered(string action)
        {
            var label = string.IsNullOrWhiteSpace(action) ? "unknown" : action.Trim().ToLowerInvariant();
            ShowToast("Gesture: " + label);
            RefreshAllStatusLines();
        }

        private void UpdateOcrFromEvent(JObject payload)
        {
            if (payload == null)
            {
                return;
            }

            var source = payload;
            var nested = payload["result"] as JObject;
            if (nested != null && string.IsNullOrWhiteSpace(payload.Value<string>("text")) && payload["lines"] == null)
            {
                source = nested;
            }

            var text = ((source.Value<string>("text") ?? string.Empty).Trim());
            if (string.IsNullOrWhiteSpace(text) && nested != null)
            {
                text = (nested.Value<string>("text") ?? string.Empty).Trim();
            }

            if (string.IsNullOrWhiteSpace(text))
            {
                var lines = source["lines"] as JArray ?? nested?["lines"] as JArray;
                if (lines != null)
                {
                    var parts = new List<string>();
                    for (var i = 0; i < lines.Count; i += 1)
                    {
                        var token = lines[i];
                        if (token == null)
                        {
                            continue;
                        }
                        string lineText;
                        if (token.Type == JTokenType.String)
                        {
                            lineText = (token.Value<string>() ?? string.Empty).Trim();
                        }
                        else
                        {
                            var row = token as JObject;
                            lineText = row != null
                                ? (row.Value<string>("text") ?? row.Value<string>("content") ?? string.Empty).Trim()
                                : string.Empty;
                        }
                        if (!string.IsNullOrWhiteSpace(lineText))
                        {
                            parts.Add(lineText);
                        }
                        if (parts.Count >= (_ocrVerbose ? 5 : 2))
                        {
                            break;
                        }
                    }
                    text = string.Join(" | ", parts);
                }
            }
            if (string.IsNullOrWhiteSpace(text))
            {
                text = "-";
            }

            if (text.Length > 200)
            {
                text = text.Substring(0, 200) + "...";
            }

            _lastOcrText = text;
            _lastOcrTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (_autoSpeakOcr)
            {
                SpeakWithGuard("OCR " + text);
            }
        }

        private void UpdateDetFromEvent(JObject payload)
        {
            if (payload == null)
            {
                return;
            }

            var labels = new List<string>();
            var topLabel = string.Empty;
            var topConf = 0f;
            var objects = payload["objects"] as JArray;
            if (objects == null && payload["result"] is JObject nested && nested["objects"] is JArray nestedObjects)
            {
                objects = nestedObjects;
            }
            if (objects != null)
            {
                for (var i = 0; i < objects.Count; i += 1)
                {
                    var row = objects[i] as JObject;
                    if (row == null)
                    {
                        continue;
                    }
                    var label = (row.Value<string>("label") ?? string.Empty).Trim();
                    if (!string.IsNullOrWhiteSpace(label))
                    {
                        labels.Add(label);
                        if (string.IsNullOrWhiteSpace(topLabel))
                        {
                            topLabel = label;
                            topConf = row.Value<float?>("conf") ?? 0f;
                        }
                    }
                    if (labels.Count >= 3)
                    {
                        break;
                    }
                }
            }

            _lastDetText = labels.Count > 0 ? string.Join(", ", labels) : "none";
            _lastDetTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (_autoSpeakDet && labels.Count > 0)
            {
                SpeakWithGuard("Detected " + string.Join(", ", labels));
            }

            var promptUsed = payload["promptUsed"] as JArray;
            var hasFindPrompt = promptUsed != null && promptUsed.Count > 0;
            if (!hasFindPrompt && payload["result"] is JObject nestedResult && nestedResult["promptUsed"] is JArray nestedPrompt)
            {
                promptUsed = nestedPrompt;
                hasFindPrompt = promptUsed.Count > 0;
            }

            if (!hasFindPrompt && !string.IsNullOrWhiteSpace(_pendingFindPrompt))
            {
                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                hasFindPrompt = nowMs - _pendingFindPromptTsMs <= 7000;
            }

            if (hasFindPrompt)
            {
                UpdateFindFromDet(topLabel, topConf, promptUsed);
            }
        }

        private void UpdateFindFromDet(string topLabel, float topConf, JArray promptUsed)
        {
            string promptToken = string.Empty;
            if (promptUsed != null && promptUsed.Count > 0)
            {
                promptToken = string.Join(",", promptUsed.ToObject<string[]>() ?? Array.Empty<string>()).Trim();
            }

            if (string.IsNullOrWhiteSpace(promptToken))
            {
                promptToken = string.IsNullOrWhiteSpace(_pendingFindPrompt) ? "find" : _pendingFindPrompt;
            }

            var resolvedLabel = string.IsNullOrWhiteSpace(topLabel) ? "none" : topLabel;
            var findText = $"\"{promptToken}\" -> {resolvedLabel}";
            if (topConf > 0f)
            {
                findText += $" conf={topConf:0.00}";
            }
            if (!string.IsNullOrWhiteSpace(_guidanceText) && !string.Equals(_guidanceText, "-", StringComparison.Ordinal))
            {
                findText += $" {_guidanceText}";
            }
            if (findText.Length > 220)
            {
                findText = findText.Substring(0, 220) + "...";
            }

            _lastFindText = findText;
            _lastFindTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            _pendingFindPrompt = string.Empty;
            _pendingFindPromptTsMs = -1;
            if (_autoSpeakFind)
            {
                SpeakWithGuard("Find " + findText);
            }
        }

        private void UpdateRiskFromEvent(JObject payload, string eventName)
        {
            if (payload == null)
            {
                return;
            }
            var source = payload;
            if (payload["result"] is JObject nested)
            {
                source = nested;
            }

            if (string.Equals(eventName, "risk.fused", StringComparison.Ordinal))
            {
                var center = source.Value<double?>("center_min_m");
                var suggested = (source.Value<string>("suggested_dir") ?? string.Empty).Trim();
                if (center.HasValue)
                {
                    _lastRiskText = $"center={center.Value:0.00}m dir={suggested}";
                }
                else
                {
                    _lastRiskText = $"dir={suggested}";
                }
            }
            else
            {
                var hazards = source["hazards"] as JArray;
                if (hazards != null && hazards.Count > 0)
                {
                    var first = hazards[0] as JObject;
                    if (first != null)
                    {
                        var kind = (first.Value<string>("hazardKind") ?? "hazard").Trim();
                        var severity = (first.Value<string>("severity") ?? string.Empty).Trim();
                        _lastRiskText = string.IsNullOrWhiteSpace(severity) ? kind : $"{kind}/{severity}";
                    }
                }
            }

            if (string.IsNullOrWhiteSpace(_lastRiskText))
            {
                _lastRiskText = "-";
            }
            _lastRiskTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var guidanceToken = _lastRiskText;
            _guidanceText = guidanceToken;
            _lastGuidanceTsMs = _lastRiskTsMs;
            if (_autoSpeakRisk)
            {
                SpeakWithGuard("Risk " + _lastRiskText);
            }
            if (_autoGuidance)
            {
                SpeakWithGuard("Guidance " + _guidanceText);
            }
            TriggerGuidanceCueFromText(_guidanceText, centerXNorm: 0.5f, depthM: ParseDepthFromRiskText(_lastRiskText));
        }

        private void UpdateTargetSessionFromEvent(JObject payload)
        {
            if (payload == null)
            {
                return;
            }

            var sessionId = (payload.Value<string>("sessionId") ?? string.Empty).Trim();
            if (!string.IsNullOrWhiteSpace(sessionId))
            {
                _targetSessionId = sessionId;
            }

            var status = (payload.Value<string>("status") ?? string.Empty).Trim();
            if (string.Equals(status, "closed", StringComparison.OrdinalIgnoreCase))
            {
                _targetSessionId = string.Empty;
                _lastTargetText = "session closed";
                _lastTargetTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            }
        }

        private void UpdateTargetFromEvent(JObject payload)
        {
            if (payload == null)
            {
                return;
            }

            var source = payload["result"] as JObject ?? payload;
            var sessionId = (source.Value<string>("sessionId") ?? string.Empty).Trim();
            if (!string.IsNullOrWhiteSpace(sessionId))
            {
                _targetSessionId = sessionId;
            }

            var target = source["target"] as JObject;
            if (target == null)
            {
                _lastTargetText = "none";
                _lastTargetTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                return;
            }

            var label = (target.Value<string>("label") ?? "unknown").Trim();
            var conf = target.Value<float?>("conf") ?? 0f;
            _lastTargetText = $"{label} conf={conf:0.00}";
            _lastTargetTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            var boxNorm = target["boxNorm"] as JArray ?? target["box_norm"] as JArray;
            if (boxNorm != null && boxNorm.Count == 4)
            {
                try
                {
                    var x0 = boxNorm[0].Value<float>();
                    var x1 = boxNorm[2].Value<float>();
                    var centerX = Mathf.Clamp01((x0 + x1) * 0.5f);
                    var output = _guidanceEngine != null
                        ? _guidanceEngine.Evaluate(centerX, ParseDepthFromRiskText(_lastRiskText))
                        : new GuidanceOutput(GuidanceDirection.Center, 0.5f);
                    _guidanceText = output.ToString();
                    _lastGuidanceTsMs = _lastTargetTsMs;
                    TriggerGuidanceCue(output);
                }
                catch
                {
                    // ignore malformed coordinates
                }
            }
        }

        private void UpdateAsrFromEvent(JObject payload)
        {
            if (payload == null)
            {
                return;
            }

            var source = payload["result"] as JObject ?? payload;
            var text = (source.Value<string>("text") ?? payload.Value<string>("text") ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(text))
            {
                text = "-";
            }
            if (text.Length > 220)
            {
                text = text.Substring(0, 220) + "...";
            }

            _lastAsrText = text;
            _lastAsrTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            ShowToast("ASR: " + (text.Length > 48 ? text.Substring(0, 48) + "..." : text));
            if (_autoVoiceCommandEnabled && _voiceCommandRouter != null)
            {
                _voiceCommandRouter.RouteTranscript(text, this);
            }
        }

        private float ParseDepthFromRiskText(string text)
        {
            var raw = string.IsNullOrWhiteSpace(text) ? string.Empty : text.Trim().ToLowerInvariant();
            var marker = "center=";
            var idx = raw.IndexOf(marker, StringComparison.Ordinal);
            if (idx < 0)
            {
                return -1f;
            }
            var start = idx + marker.Length;
            var end = raw.IndexOf("m", start, StringComparison.Ordinal);
            if (end <= start)
            {
                return -1f;
            }
            var token = raw.Substring(start, end - start);
            return float.TryParse(token, out var value) ? value : -1f;
        }

        private void TriggerGuidanceCueFromText(string guidance, float centerXNorm, float depthM)
        {
            var output = _guidanceEngine != null ? _guidanceEngine.Evaluate(centerXNorm, depthM) : default;
            if (!string.IsNullOrWhiteSpace(guidance))
            {
                var lower = guidance.ToLowerInvariant();
                if (lower.Contains("left"))
                {
                    output = new GuidanceOutput(GuidanceDirection.Left, 0.8f);
                }
                else if (lower.Contains("right"))
                {
                    output = new GuidanceOutput(GuidanceDirection.Right, 0.8f);
                }
                else if (lower.Contains("stop"))
                {
                    output = new GuidanceOutput(GuidanceDirection.Stop, 1f);
                }
                else if (lower.Contains("center"))
                {
                    output = new GuidanceOutput(GuidanceDirection.Center, 0.7f);
                }
            }
            TriggerGuidanceCue(output);
        }

        private void TriggerGuidanceCue(GuidanceOutput output)
        {
            if (!_autoGuidance)
            {
                return;
            }
            if (_guidanceAudioEnabled)
            {
                _guidanceAudioCue?.Play(output);
            }
            if (_guidanceHapticsEnabled)
            {
                _guidanceHapticsCue?.Pulse(output);
            }
        }

        private void ApplyGuidanceRate()
        {
            var rate = Mathf.Clamp(_guidanceRateSec, 0.2f, 1.2f);
            _guidanceAudioCue?.SetCooldownSec(rate);
            _guidanceHapticsCue?.SetCooldownSec(rate);
        }

        private void SpeakWithGuard(string text)
        {
            var normalized = string.IsNullOrWhiteSpace(text) ? string.Empty : text.Trim();
            if (string.IsNullOrWhiteSpace(normalized))
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (_lastSpokenAtMs > 0 && nowMs - _lastSpokenAtMs < 2000)
            {
                return;
            }

            var digest = normalized.ToLowerInvariant();
            if (string.Equals(digest, _lastSpokenDigest, StringComparison.Ordinal))
            {
                return;
            }

            ResolveRefs();
            var spoken = false;
            if (_localTtsReady && _localTtsBackend != null && Application.platform == RuntimePlatform.Android)
            {
                _localTtsBackend.Speak(normalized, flushQueue: false);
                spoken = true;
            }
            else if (_speechOrchestrator != null)
            {
                _speechOrchestrator.SpeakLocalHint(normalized);
                spoken = true;
            }

            if (spoken)
            {
                _lastSpokenAtMs = nowMs;
                _lastSpokenDigest = digest;
                _lastTtsText = normalized;
                _lastTtsTsMs = nowMs;
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
            _runtimeCanvas = canvas;

            var canvasRect = canvasGo.GetComponent<RectTransform>();
            canvasRect.sizeDelta = new Vector2(1720f, 1860f);
            canvasRect.localScale = Vector3.one * 0.00025f;
            canvasRect.localPosition = Vector3.zero;
            canvasRect.localRotation = Quaternion.identity;

            canvasGo.AddComponent<CanvasScaler>();
            AddBestRaycaster(canvasGo);

            var panel = CreateUiObject("Panel", canvasGo.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(1720f, 1820f), Vector2.zero);
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
            _lastOcrTextView = CreateText("LastOCR", panel.transform, "Last OCR: -", 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -642f), new Vector2(1480f, 62f));
            _lastDetTextView = CreateText("LastDET", panel.transform, "Last DET: -", 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -696f), new Vector2(1480f, 62f));
            _lastRiskTextView = CreateText("LastRISK", panel.transform, "Last RISK: -", 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -750f), new Vector2(1480f, 62f));
            _lastFindTextView = CreateText("LastFIND", panel.transform, "Last FIND: -", 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -804f), new Vector2(1480f, 62f));
            _lastTargetTextView = CreateText("LastTarget", panel.transform, "Last TARGET: -", 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -858f), new Vector2(1480f, 62f));
            _guidanceTextView = CreateText("Guidance", panel.transform, "Guidance: -", 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -912f), new Vector2(1480f, 62f));
            _lastAsrTextView = CreateText("LastASR", panel.transform, "Last ASR: -", 26, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -966f), new Vector2(1480f, 58f));
            _lastTtsTextView = CreateText("LastTTS", panel.transform, "Last TTS: -", 26, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -1018f), new Vector2(1480f, 58f));
            _hudStatsTextView = CreateText("HudStats", panel.transform, "HUD: -", 24, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -1070f), new Vector2(1480f, 58f));
            _scanStateText = CreateText("ScanState", panel.transform, "Scan: idle", 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -1126f), new Vector2(1480f, 62f));
            _selfTestText = CreateText("SelfTest", panel.transform, "SelfTest: IDLE", 26, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -1178f), new Vector2(1480f, 96f));
            _captureText = CreateText("CaptureStats", panel.transform, "Capture: -", 22, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -1272f), new Vector2(1480f, 52f));
            _hitchText = CreateText("HitchStats", panel.transform, "Hitch30s: -", 22, TextAnchor.MiddleLeft, new Vector2(0.5f, 1f), new Vector2(0f, -1320f), new Vector2(1480f, 52f));
            _toastText = CreateText("Toast", panel.transform, "-", 32, TextAnchor.MiddleCenter, new Vector2(0.5f, 0f), new Vector2(0f, 290f), new Vector2(1480f, 72f));
            _rawText = CreateText("Raw", panel.transform, "-", 24, TextAnchor.UpperLeft, new Vector2(0.5f, 0f), new Vector2(0f, 210f), new Vector2(1480f, 170f), allowWrap: true);

            CreateButton(panel.transform, "PingButton", "Ping", new Vector2(-650f, -1508f), OnPingClicked, markAsAction: true);
            CreateButton(panel.transform, "VersionButton", "Version", new Vector2(-420f, -1508f), OnVersionClicked, markAsAction: true);
            CreateButton(panel.transform, "ModeReadButton", "Read", new Vector2(-190f, -1508f), () => OnSetModeClicked("read_text"), markAsAction: true);
            CreateButton(panel.transform, "ModeWalkButton", "Walk", new Vector2(40f, -1508f), () => OnSetModeClicked("walk"), markAsAction: true);
            CreateButton(panel.transform, "ModeInspectButton", "Inspect", new Vector2(270f, -1508f), () => OnSetModeClicked("inspect"), markAsAction: true);
            _scanButton = CreateButton(panel.transform, "ScanButton", "Scan Once", new Vector2(500f, -1508f), OnScanClicked, markAsAction: true);
            _liveButton = CreateButton(panel.transform, "LiveButton", "Live Start", new Vector2(730f, -1508f), OnLiveClicked, markAsAction: true);
            _liveToggle = CreateLiveToggle(panel.transform, "LiveToggle", "Live", new Vector2(730f, -1588f), OnLiveToggleChanged, markAsAction: true);

            CreateButton(panel.transform, "RefreshButton", "Refresh", new Vector2(-420f, -1588f), OnRefreshClicked, markAsAction: true);
            CreateButton(panel.transform, "SelfTestButton", "SelfTest", new Vector2(-190f, -1588f), OnSelfTestClicked, markAsAction: true);
            CreateButton(panel.transform, "ReconnectWsButton", "WS Reconnect", new Vector2(40f, -1588f), OnReconnectWsClicked, markAsAction: true);
            CreateButton(panel.transform, "RecordStartButton", "Rec Start", new Vector2(270f, -1588f), OnRecordStartClicked, markAsAction: true);
            CreateButton(panel.transform, "RecordStopButton", "Rec Stop", new Vector2(500f, -1588f), OnRecordStopClicked, markAsAction: true);
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
            yield return QueryCapabilities(silent: false);
        }

        private IEnumerator TriggerAssistThenFallback(
            string action,
            string[] targets,
            JObject prompt,
            Action fallbackAction,
            string toastOnAssist,
            string toastOnFallback)
        {
            ResolveRefs();
            _scanStatus = "sending";
            _scanError = string.Empty;
            RefreshAllStatusLines();

            var assistDone = false;
            var assistOk = false;
            var assistError = string.Empty;
            yield return PostAssist(action, targets, prompt, (ok, error) =>
            {
                assistDone = true;
                assistOk = ok;
                assistError = error;
            });

            if (assistDone && assistOk)
            {
                _scanStatus = "assist_ok";
                _scanError = string.Empty;
                ShowToast(toastOnAssist);
                RefreshAllStatusLines();
                yield break;
            }

            var cacheMiss = !string.IsNullOrWhiteSpace(assistError)
                            && assistError.IndexOf("assist_cache_miss", StringComparison.OrdinalIgnoreCase) >= 0;
            if (cacheMiss && fallbackAction != null)
            {
                fallbackAction.Invoke();
                _scanStatus = "sending";
                _scanError = string.Empty;
                ShowToast(toastOnFallback);
                RefreshAllStatusLines();
                yield break;
            }

            if (fallbackAction != null)
            {
                fallbackAction.Invoke();
                _scanStatus = "sending";
                _scanError = string.Empty;
                ShowToast(toastOnFallback);
            }
            else
            {
                _scanStatus = "failed";
                _scanError = string.IsNullOrWhiteSpace(assistError) ? "assist failed" : assistError;
                ShowToast("Assist failed");
            }
            RefreshAllStatusLines();
        }

        private IEnumerator StartRecording()
        {
            var payload = new JObject
            {
                ["deviceId"] = GetDeviceId(),
                ["note"] = "quest3_smoke",
                ["maxSec"] = 180,
                ["maxFrames"] = 0,
            };

            var done = false;
            var ok = false;
            var message = string.Empty;
            yield return SendJsonRequest(UnityWebRequest.kHttpVerbPOST, "/api/record/start", payload, (success, obj, error) =>
            {
                done = true;
                ok = success;
                if (success && obj != null)
                {
                    message = (obj.Value<string>("runId") ?? "record started").Trim();
                }
                else
                {
                    message = string.IsNullOrWhiteSpace(error) ? "record start failed" : error;
                }
            });

            if (!done || !ok)
            {
                var normalized = (message ?? string.Empty).Trim();
                if (normalized.IndexOf("already active recording", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    _recordingActive = true;
                    _scanError = string.Empty;
                    ShowToast("Record already active");
                }
                else
                {
                    ShowToast("Record start failed");
                    _scanError = string.IsNullOrWhiteSpace(normalized) ? "record start failed" : normalized;
                }
            }
            else
            {
                _recordingActive = true;
                ShowToast("Record start");
                _scanError = string.Empty;
            }
            RefreshAllStatusLines();
        }

        private IEnumerator StopRecording()
        {
            var payload = new JObject
            {
                ["deviceId"] = GetDeviceId(),
            };

            var done = false;
            var ok = false;
            var message = string.Empty;
            yield return SendJsonRequest(UnityWebRequest.kHttpVerbPOST, "/api/record/stop", payload, (success, obj, error) =>
            {
                done = true;
                ok = success;
                if (success && obj != null)
                {
                    message = (obj.Value<string>("recordingPath") ?? "record stopped").Trim();
                }
                else
                {
                    message = string.IsNullOrWhiteSpace(error) ? "record stop failed" : error;
                }
            });

            if (!done || !ok)
            {
                var normalized = (message ?? string.Empty).Trim();
                if (normalized.IndexOf("no active recording", StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    _recordingActive = false;
                    _scanError = string.Empty;
                    ShowToast("Record not active");
                }
                else
                {
                    ShowToast("Record stop failed");
                    _scanError = string.IsNullOrWhiteSpace(normalized) ? "record stop failed" : normalized;
                }
            }
            else
            {
                _recordingActive = false;
                ShowToast("Record stop");
                _scanError = string.Empty;
            }
            RefreshAllStatusLines();
        }

        private IEnumerator PostAssist(string action, string[] targets, JObject prompt, Action<bool, string> onDone)
        {
            var payload = new JObject
            {
                ["deviceId"] = GetDeviceId(),
                ["action"] = string.IsNullOrWhiteSpace(action) ? "det" : action.Trim().ToLowerInvariant(),
                ["maxAgeMs"] = 5000,
            };
            if (targets != null && targets.Length > 0)
            {
                var arr = new JArray();
                for (var i = 0; i < targets.Length; i += 1)
                {
                    var token = string.IsNullOrWhiteSpace(targets[i]) ? string.Empty : targets[i].Trim().ToLowerInvariant();
                    if (!string.IsNullOrWhiteSpace(token))
                    {
                        arr.Add(token);
                    }
                }
                if (arr.Count > 0)
                {
                    payload["targets"] = arr;
                }
            }

            if (prompt != null)
            {
                payload["prompt"] = prompt;
            }

            var done = false;
            var successResult = false;
            var errorResult = string.Empty;
            yield return SendJsonRequest(UnityWebRequest.kHttpVerbPOST, "/api/assist", payload, (success, _, error) =>
            {
                done = true;
                successResult = success;
                errorResult = error;
            });

            if (!done)
            {
                onDone?.Invoke(false, "assist no response");
                yield break;
            }

            onDone?.Invoke(successResult, errorResult);
        }

        private JObject BuildTrackPayload(string action)
        {
            var payload = new JObject
            {
                ["deviceId"] = GetDeviceId(),
                ["action"] = action,
                ["maxAgeMs"] = 5000,
                ["tracker"] = _targetTracker,
            };

            if (string.Equals(action, "target_start", StringComparison.Ordinal))
            {
                payload["roi"] = new JObject
                {
                    ["x"] = _selectedRoi.Value<float?>("x") ?? 0.35f,
                    ["y"] = _selectedRoi.Value<float?>("y") ?? 0.35f,
                    ["w"] = _selectedRoi.Value<float?>("w") ?? 0.3f,
                    ["h"] = _selectedRoi.Value<float?>("h") ?? 0.3f,
                };
                var prompt = string.IsNullOrWhiteSpace(_pendingFindPrompt) ? "person" : _pendingFindPrompt.Trim();
                payload["prompt"] = new JObject
                {
                    ["text"] = prompt,
                    ["openVocab"] = true,
                    ["task"] = "find",
                };
                payload["seg"] = new JObject
                {
                    ["enabled"] = false,
                    ["mode"] = "sam3",
                };
            }
            else if (!string.IsNullOrWhiteSpace(_targetSessionId))
            {
                payload["sessionId"] = _targetSessionId;
            }

            return payload;
        }

        private IEnumerator StartTargetTrack()
        {
            var done = false;
            var ok = false;
            var error = string.Empty;
            JObject response = null;
            yield return SendJsonRequest(UnityWebRequest.kHttpVerbPOST, "/api/assist", BuildTrackPayload("target_start"), (success, obj, err) =>
            {
                done = true;
                ok = success;
                response = obj;
                error = err;
            });

            var normalizedError = string.IsNullOrWhiteSpace(error) ? string.Empty : error.Trim();
            var likelyCacheMiss =
                normalizedError.IndexOf("assist_cache_miss", StringComparison.OrdinalIgnoreCase) >= 0
                || (normalizedError.IndexOf("404", StringComparison.OrdinalIgnoreCase) >= 0
                    && normalizedError.IndexOf("/api/assist", StringComparison.OrdinalIgnoreCase) >= 0);
            if ((!done || !ok || response == null) && likelyCacheMiss && _scanController != null)
            {
                // Assist requires a fresh cached frame for this deviceId. Seed once then retry.
                _scanController.ScanOnceFromUi();
                yield return new WaitForSecondsRealtime(0.35f);

                done = false;
                ok = false;
                error = string.Empty;
                response = null;
                yield return SendJsonRequest(UnityWebRequest.kHttpVerbPOST, "/api/assist", BuildTrackPayload("target_start"), (success, obj, err) =>
                {
                    done = true;
                    ok = success;
                    response = obj;
                    error = err;
                });
            }

            if (!done || !ok || response == null)
            {
                _scanStatus = "failed";
                _scanError = string.IsNullOrWhiteSpace(error) ? "target_start failed" : error;
                ShowToast("Start Track failed");
                RefreshAllStatusLines();
                yield break;
            }

            _targetSessionId = (response.Value<string>("sessionId") ?? string.Empty).Trim();
            _scanStatus = "track_active";
            _scanError = string.Empty;
            ShowToast(string.IsNullOrWhiteSpace(_targetSessionId) ? "Track started" : $"Track { _targetSessionId }");
            RefreshAllStatusLines();
        }

        private IEnumerator TargetTrackStep()
        {
            if (string.IsNullOrWhiteSpace(_targetSessionId))
            {
                ShowToast("Track step skipped: no session");
                yield break;
            }

            var done = false;
            var ok = false;
            var error = string.Empty;
            yield return SendJsonRequest(UnityWebRequest.kHttpVerbPOST, "/api/assist", BuildTrackPayload("target_step"), (success, _, err) =>
            {
                done = true;
                ok = success;
                error = err;
            });

            if (!done || !ok)
            {
                _scanStatus = "failed";
                _scanError = string.IsNullOrWhiteSpace(error) ? "target_step failed" : error;
                ShowToast("Track step failed");
            }
            else
            {
                _scanStatus = "track_step";
                _scanError = string.Empty;
                ShowToast("Track step");
            }
            RefreshAllStatusLines();
        }

        private IEnumerator StopTargetTrack()
        {
            var done = false;
            var ok = false;
            var error = string.Empty;
            yield return SendJsonRequest(UnityWebRequest.kHttpVerbPOST, "/api/assist", BuildTrackPayload("target_stop"), (success, _, err) =>
            {
                done = true;
                ok = success;
                error = err;
            });

            if (!done || !ok)
            {
                _scanStatus = "failed";
                _scanError = string.IsNullOrWhiteSpace(error) ? "target_stop failed" : error;
                ShowToast("Stop Track failed");
            }
            else
            {
                _targetSessionId = string.Empty;
                _scanStatus = "track_stopped";
                _scanError = string.Empty;
                ShowToast("Track stopped");
            }
            RefreshAllStatusLines();
        }

        private IEnumerator SendJsonRequest(
            string method,
            string path,
            JObject payload,
            Action<bool, JObject, string> onDone)
        {
            var uri = $"{_baseUrl}{path}";
            TrackProbeRequest(path);
            using var request = new UnityWebRequest(uri, method);
            request.downloadHandler = new DownloadHandlerBuffer();
            if (payload != null)
            {
                request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(payload.ToString(Newtonsoft.Json.Formatting.None)));
                request.SetRequestHeader("Content-Type", "application/json");
            }
            ApplyApiKeyHeader(request);
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                var detail = request.error ?? "request failed";
                var body = request.downloadHandler != null ? request.downloadHandler.text : string.Empty;
                if (!string.IsNullOrWhiteSpace(body))
                {
                    detail = detail + " | " + body;
                }
                onDone?.Invoke(false, null, detail);
                yield break;
            }

            try
            {
                var text = request.downloadHandler != null ? request.downloadHandler.text : "{}";
                var obj = JObject.Parse(string.IsNullOrWhiteSpace(text) ? "{}" : text);
                onDone?.Invoke(true, obj, string.Empty);
            }
            catch (Exception ex)
            {
                onDone?.Invoke(false, null, "json parse failed: " + ex.Message);
            }
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

            SetLiveEnabledFromUi(!_scanController.IsLiveEnabled);
        }

        private void OnLiveToggleChanged(bool enabled)
        {
            if (_suppressLiveToggleCallback)
            {
                return;
            }

            SetLiveEnabledFromUi(enabled);
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

        private void OnRecordStartClicked()
        {
            StartCoroutine(StartRecording());
        }

        private void OnRecordStopClicked()
        {
            StartCoroutine(StopRecording());
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

        public void TriggerReadTextOnceFromUi()
        {
            StartCoroutine(TriggerAssistThenFallback(
                action: "ocr",
                targets: new[] {"ocr"},
                prompt: null,
                fallbackAction: () => _scanController?.ReadTextOnceFromUi(),
                toastOnAssist: "ReadText assist",
                toastOnFallback: "ReadText upload"));
        }

        public void TriggerDetectObjectsOnceFromUi()
        {
            StartCoroutine(TriggerAssistThenFallback(
                action: "det",
                targets: new[] {"det"},
                prompt: null,
                fallbackAction: () => _scanController?.DetectObjectsOnceFromUi(),
                toastOnAssist: "Detect assist",
                toastOnFallback: "Detect upload"));
        }

        public void TriggerDepthRiskOnceFromUi()
        {
            ResolveRefs();
            if (_scanController == null)
            {
                ShowToast("Depth/Risk Failed: scan missing");
                return;
            }

            _scanController.DepthRiskOnceFromUi();
            _scanStatus = "sending";
            _scanError = string.Empty;
            ShowToast("Depth/Risk trigger");
            RefreshAllStatusLines();
        }

        public void TriggerToggleLiveFromUi()
        {
            OnLiveClicked();
        }

        public void TriggerFindConceptFromUi(string concept)
        {
            var normalized = string.IsNullOrWhiteSpace(concept) ? string.Empty : concept.Trim();
            _pendingFindPrompt = normalized;
            _pendingFindPromptTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            var prompt = new JObject
            {
                ["text"] = normalized,
                ["openVocab"] = true,
                ["task"] = "find",
            };
            StartCoroutine(TriggerAssistThenFallback(
                action: "find",
                targets: new[] {"det"},
                prompt: prompt,
                fallbackAction: () => _scanController?.FindConceptOnceFromUi(normalized),
                toastOnAssist: $"Find assist: {normalized}",
                toastOnFallback: $"Find upload: {normalized}"));
        }

        public void TriggerSelectRoiFromUi()
        {
            ResolveRefs();
            if (_roiPanelController == null)
            {
                ShowToast("ROI panel missing");
                return;
            }
            _roiPanelController.ShowDefaultRoi();
            var roi = _roiPanelController.SelectedRoiNorm;
            _selectedRoi["x"] = roi.x;
            _selectedRoi["y"] = roi.y;
            _selectedRoi["w"] = roi.width;
            _selectedRoi["h"] = roi.height;
            ShowToast($"ROI selected {roi.x:0.00},{roi.y:0.00},{roi.width:0.00},{roi.height:0.00}");
        }

        public void TriggerStartTrackFromUi()
        {
            StartCoroutine(StartTargetTrack());
        }

        public void TriggerTrackStepFromUi()
        {
            StartCoroutine(TargetTrackStep());
        }

        public void TriggerStopTrackFromUi()
        {
            StartCoroutine(StopTargetTrack());
        }

        public void TriggerStartRecordFromUi()
        {
            StartCoroutine(StartRecording());
        }

        public void TriggerStopRecordFromUi()
        {
            StartCoroutine(StopRecording());
        }

        public void TriggerPlayBeepFromUi()
        {
            ResolveRefs();
            if (_beepAudioSource == null || _beepClip == null)
            {
                ShowToast("Beep unavailable");
                return;
            }
            _beepAudioSource.PlayOneShot(_beepClip, 1f);
            _lastTtsText = "beep";
            _lastTtsTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            ShowToast("Beep");
        }

        public void TriggerSpeakTestFromUi()
        {
            SpeakWithGuard("hello from be your eyes");
            ShowToast("Speak test");
        }

        public void TriggerPushToTalkStartFromUi()
        {
            StartVoiceCapture();
        }

        public void TriggerPushToTalkStopFromUi()
        {
            StopVoiceCaptureAndSend();
        }

        public void SetAutoVoiceCommand(bool enabled)
        {
            _autoVoiceCommandEnabled = enabled;
            PlayerPrefs.SetInt(PrefAutoVoiceCommand, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("Auto Voice Cmd " + (enabled ? "ON" : "OFF"));
        }

        public bool AutoVoiceCommandEnabled => _autoVoiceCommandEnabled;

        public bool AutoSpeakOcrEnabled => _autoSpeakOcr;
        public bool AutoSpeakDetEnabled => _autoSpeakDet;
        public bool AutoSpeakRiskEnabled => _autoSpeakRisk;
        public bool AutoSpeakFindEnabled => _autoSpeakFind;
        public bool AutoGuidanceEnabled => _autoGuidance;
        public bool OcrVerboseEnabled => _ocrVerbose;
        public bool GuidanceAudioEnabled => _guidanceAudioEnabled;
        public bool GuidanceHapticsEnabled => _guidanceHapticsEnabled;

        public void SetAutoSpeakOcr(bool enabled)
        {
            _autoSpeakOcr = enabled;
            PlayerPrefs.SetInt(PrefAutoSpeakOcr, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("AutoSpeak OCR " + (enabled ? "ON" : "OFF"));
        }

        public void SetAutoSpeakDet(bool enabled)
        {
            _autoSpeakDet = enabled;
            PlayerPrefs.SetInt(PrefAutoSpeakDet, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("AutoSpeak DET " + (enabled ? "ON" : "OFF"));
        }

        public void SetAutoSpeakRisk(bool enabled)
        {
            _autoSpeakRisk = enabled;
            PlayerPrefs.SetInt(PrefAutoSpeakRisk, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("AutoSpeak RISK " + (enabled ? "ON" : "OFF"));
        }

        public void SetAutoSpeakFind(bool enabled)
        {
            _autoSpeakFind = enabled;
            PlayerPrefs.SetInt(PrefAutoSpeakFind, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("AutoSpeak FIND " + (enabled ? "ON" : "OFF"));
        }

        public void SetAutoGuidance(bool enabled)
        {
            _autoGuidance = enabled;
            PlayerPrefs.SetInt(PrefAutoGuidance, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("Auto Guidance " + (enabled ? "ON" : "OFF"));
        }

        public void SetGuidanceAudio(bool enabled)
        {
            _guidanceAudioEnabled = enabled;
            PlayerPrefs.SetInt(PrefGuidanceAudio, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("Guidance Audio " + (enabled ? "ON" : "OFF"));
        }

        public void SetGuidanceHaptics(bool enabled)
        {
            _guidanceHapticsEnabled = enabled;
            PlayerPrefs.SetInt(PrefGuidanceHaptics, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("Guidance Haptics " + (enabled ? "ON" : "OFF"));
        }

        public void SetGuidanceRate(float seconds)
        {
            _guidanceRateSec = Mathf.Clamp(seconds, 0.2f, 1.2f);
            PlayerPrefs.SetFloat(PrefGuidanceRateSec, _guidanceRateSec);
            PlayerPrefs.Save();
            ApplyGuidanceRate();
            ShowToast($"Guidance rate {_guidanceRateSec:0.00}s");
        }

        public float GetGuidanceRate()
        {
            return _guidanceRateSec;
        }

        public bool IsRecording()
        {
            return _recordingActive;
        }

        public void SetOcrVerbose(bool enabled)
        {
            _ocrVerbose = enabled;
            PlayerPrefs.SetInt(PrefOcrVerbose, enabled ? 1 : 0);
            PlayerPrefs.Save();
            ShowToast("OCR Verbose " + (enabled ? "ON" : "OFF"));
        }

        public void SetPassthroughEnabled(bool enabled)
        {
            ResolveRefs();
            if (_passthroughController == null)
            {
                ShowToast("Passthrough unavailable");
                return;
            }
            _passthroughController.SetEnabled(enabled);
            ShowToast("Passthrough " + (enabled ? "ON" : "OFF"));
        }

        public string GetPassthroughStatus()
        {
            ResolveRefs();
            return _passthroughController != null ? _passthroughController.StatusString : "unavailable";
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
            StartCoroutine(SetMode(ByesModeManager.ToApiMode(next)));
        }

        public string GetBaseUrl()
        {
            return _baseUrl;
        }

        public string GetDeviceId()
        {
            return string.IsNullOrWhiteSpace(_deviceId) ? "quest3-unknown" : _deviceId;
        }

        public bool IsWsConnected()
        {
            return (_gatewayClient != null && _gatewayClient.IsConnected)
                   || (_gatewayWsClient != null && string.Equals(_gatewayWsClient.ConnectionState, "Connected", StringComparison.Ordinal));
        }

        public string GetCurrentModeText()
        {
            return string.IsNullOrWhiteSpace(_currentMode) ? "-" : _currentMode;
        }

        public long GetLastUploadMs()
        {
            return _scanController != null ? Convert.ToInt64(Math.Round(_scanController.LastUploadCostMs)) : -1;
        }

        public long GetLastE2eMs()
        {
            return _scanController != null ? Convert.ToInt64(Math.Round(_scanController.LastE2eMs)) : -1;
        }

        public string GetLastEventType()
        {
            return string.IsNullOrWhiteSpace(_lastEventType) ? "-" : _lastEventType;
        }

        public string GetLastFindText()
        {
            return string.IsNullOrWhiteSpace(_lastFindText) ? "-" : _lastFindText;
        }

        public string GetLastTargetText()
        {
            return string.IsNullOrWhiteSpace(_lastTargetText) ? "-" : _lastTargetText;
        }

        public string GetGuidanceText()
        {
            return string.IsNullOrWhiteSpace(_guidanceText) ? "-" : _guidanceText;
        }

        public string GetLastAsrText()
        {
            return string.IsNullOrWhiteSpace(_lastAsrText) ? "-" : _lastAsrText;
        }

        public string GetLastTtsText()
        {
            return string.IsNullOrWhiteSpace(_lastTtsText) ? "-" : _lastTtsText;
        }

        public long GetHudSegAgeMs()
        {
            return _visionHud != null ? _visionHud.LastSegAgeMs : -1L;
        }

        public long GetHudDepthAgeMs()
        {
            return _visionHud != null ? _visionHud.LastDepthAgeMs : -1L;
        }

        public long GetHudDetAgeMs()
        {
            return _visionHud != null ? _visionHud.LastDetAgeMs : -1L;
        }

        public long GetLastOcrTsMs()
        {
            return _lastOcrTsMs;
        }

        public long GetLastDetTsMs()
        {
            return _lastDetTsMs;
        }

        public long GetLastRiskTsMs()
        {
            return _lastRiskTsMs;
        }

        public string GetScanErrorText()
        {
            return _scanError ?? string.Empty;
        }

        public bool IsLockToHead()
        {
            return _headLockedPanel != null && _headLockedPanel.IsLockToHeadEnabled;
        }

        public void SetLockToHead(bool value)
        {
            if (_headLockedPanel == null)
            {
                return;
            }

            _headLockedPanel.SetLockToHead(value);
            if (value)
            {
                _headLockedPanel.SetPinned(false);
            }
            RefreshAllStatusLines();
        }

        public bool IsMoveResizeEnabled()
        {
            return _grabHandle != null && _grabHandle.IsMoveResizeEnabled;
        }

        public void SetMoveResizeEnabled(bool enabled)
        {
            if (_grabHandle == null)
            {
                return;
            }

            _grabHandle.SetMoveResizeEnabled(enabled);
            RefreshAllStatusLines();
        }

        public string BuildDebugSummary()
        {
            return
                $"baseUrl={_baseUrl}\n" +
                $"deviceId={GetDeviceId()}\n" +
                $"http={(_lastPingRttMs >= 0 ? "reachable" : "unknown")} rttMs={_lastPingRttMs}\n" +
                $"ws={(_gatewayClient != null && _gatewayClient.IsConnected ? "connected" : "disconnected")}\n" +
                $"mode={_currentMode}\n" +
                $"scan={_scanStatus} err={_scanError}\n" +
                $"event={_lastEventType} ts={_lastEventTsMs}\n" +
                $"ocr={_lastOcrText} ts={_lastOcrTsMs}\n" +
                $"det={_lastDetText} ts={_lastDetTsMs}\n" +
                $"risk={_lastRiskText} ts={_lastRiskTsMs}\n" +
                $"find={_lastFindText} ts={_lastFindTsMs}\n" +
                $"target={_lastTargetText} ts={_lastTargetTsMs} session={_targetSessionId}\n" +
                $"guidance={_guidanceText} ts={_lastGuidanceTsMs}\n" +
                $"providers={_providerSummary} detail={_providerDetail}\n" +
                $"passthrough={GetPassthroughStatus()}\n" +
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

            if (isActiveAndEnabled && ShouldRefreshCapabilities())
            {
                StartCoroutine(QueryCapabilities(silent: true));
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
            TrackProbeRequest("/api/ping");
            var seq = _pingSeq++;
            var clientSendTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var payload = new JObject
            {
                ["deviceId"] = GetDeviceId(),
                ["seq"] = seq,
                ["clientSendTsMs"] = clientSendTsMs,
            };
            var bodyBytes = System.Text.Encoding.UTF8.GetBytes(payload.ToString(Newtonsoft.Json.Formatting.None));

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
            TrackProbeRequest("/api/version");
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
            var escapedDeviceId = UnityWebRequest.EscapeURL(GetDeviceId());
            var uri = $"{_baseUrl}/api/mode?deviceId={escapedDeviceId}";
            TrackProbeRequest("/api/mode");
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
                    SyncLocalModeState(parsed.mode);
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

        private IEnumerator QueryCapabilities(bool silent)
        {
            var uri = $"{_baseUrl}/api/capabilities";
            TrackProbeRequest("/api/capabilities");
            using var request = UnityWebRequest.Get(uri);
            ApplyApiKeyHeader(request);
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                _providerSummary = "providers: failed";
                _providerDetail = request.error ?? "capabilities failed";
                _providerTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                _lastCapabilitiesFetchTsMs = _providerTsMs;
                if (!silent)
                {
                    ShowToast("Capabilities failed");
                }
                yield break;
            }

            var payload = request.downloadHandler != null ? request.downloadHandler.text : string.Empty;
            try
            {
                var obj = JObject.Parse(string.IsNullOrWhiteSpace(payload) ? "{}" : payload);
                var providers = obj["available_providers"] as JObject;
                _providerSummary = BuildProviderSummary(providers);
                _providerDetail = providers != null
                    ? providers.ToString(Newtonsoft.Json.Formatting.None)
                    : "available_providers missing";
            }
            catch (Exception ex)
            {
                _providerSummary = "providers: parse_failed";
                _providerDetail = ex.GetType().Name;
            }

            _providerTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            _lastCapabilitiesFetchTsMs = _providerTsMs;
            if (!silent)
            {
                ShowToast("Capabilities OK");
            }
        }

        private bool ShouldRefreshCapabilities()
        {
            if (_lastCapabilitiesFetchTsMs <= 0)
            {
                return true;
            }
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            return (nowMs - _lastCapabilitiesFetchTsMs) >= Mathf.RoundToInt(CapabilitiesRefreshIntervalSec * 1000f);
        }

        private static string BuildProviderSummary(JObject providers)
        {
            if (providers == null)
            {
                return "providers: unavailable";
            }

            static string Token(JObject root, string key)
            {
                var row = root?[key] as JObject;
                if (row == null)
                {
                    return $"{key}=na";
                }

                var backend = (row.Value<string>("backend") ?? "unknown").Trim().ToLowerInvariant();
                var enabled = row.Value<bool?>("enabled") == true;
                var reason = (row.Value<string>("reason") ?? string.Empty).Trim().ToLowerInvariant();

                var mode = "real";
                if (!enabled)
                {
                    mode = "off";
                }
                else if (backend.IndexOf("mock", StringComparison.Ordinal) >= 0
                         || backend.IndexOf("reference", StringComparison.Ordinal) >= 0
                         || backend == "none")
                {
                    mode = "mock";
                }
                else if (reason.IndexOf("missing", StringComparison.Ordinal) >= 0
                         || reason.IndexOf("disabled", StringComparison.Ordinal) >= 0
                         || reason.IndexOf("not_ready", StringComparison.Ordinal) >= 0)
                {
                    mode = "off";
                }

                var compactBackend = backend.Length > 14 ? backend.Substring(0, 14) : backend;
                return $"{key}={mode}/{compactBackend}";
            }

            return string.Join(
                " ",
                new[]
                {
                    Token(providers, "ocr"),
                    Token(providers, "det"),
                    Token(providers, "seg"),
                    Token(providers, "depth"),
                    Token(providers, "slam"),
                    Token(providers, "asr"),
                }
            );
        }

        private IEnumerator SetMode(string mode)
        {
            var normalized = NormalizeMode(mode);
            var uri = $"{_baseUrl}/api/mode";
            var tsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var safeFrameSeq = Math.Max(1, _modeSeq++);
            var payload = new JObject
            {
                ["runId"] = "quest3-smoke",
                ["frameSeq"] = safeFrameSeq,
                ["mode"] = normalized,
                ["source"] = "xr",
                ["tsMs"] = tsMs,
                ["deviceId"] = GetDeviceId(),
            };

            using var request = new UnityWebRequest(uri, UnityWebRequest.kHttpVerbPOST);
            request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(payload.ToString(Newtonsoft.Json.Formatting.None)));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            request.SetRequestHeader("Content-Type", "application/json");
            ApplyApiKeyHeader(request);

            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                // Backward compatibility: some gateways still accept "read" instead of "read_text".
                if (string.Equals(normalized, "read_text", StringComparison.OrdinalIgnoreCase))
                {
                    var fallbackOk = false;
                    var fallbackError = request.error ?? "unknown";
                    yield return TrySetModeFallbackRead(modeRaw: "read", onDone: (ok, error) =>
                    {
                        fallbackOk = ok;
                        fallbackError = error;
                    });
                    if (fallbackOk)
                    {
                        SyncLocalModeState(normalized);
                        _modeText.Set($"Mode: {_currentMode}");
                        ShowToast("Set mode -> read");
                        yield return QueryMode();
                        yield break;
                    }

                    _rawText.Set($"Set mode error: {fallbackError}");
                    ShowToast($"Set mode failed: {fallbackError}");
                    yield break;
                }

                _rawText.Set($"Set mode error: {request.error}");
                ShowToast($"Set mode failed: {request.error}");
                yield break;
            }

            SyncLocalModeState(normalized);
            _modeText.Set($"Mode: {_currentMode}");
            ShowToast($"Set mode -> {normalized}");
            var readbackOk = false;
            for (var attempt = 0; attempt < 3; attempt += 1)
            {
                yield return QueryMode();
                if (string.Equals(_currentMode, normalized, StringComparison.OrdinalIgnoreCase))
                {
                    readbackOk = true;
                    break;
                }
                yield return new WaitForSecondsRealtime(0.2f);
            }

            if (!readbackOk)
            {
                if (string.Equals(normalized, "read_text", StringComparison.OrdinalIgnoreCase))
                {
                    var fallbackOk = false;
                    var fallbackError = string.Empty;
                    yield return TrySetModeFallbackRead(modeRaw: "read", onDone: (ok, error) =>
                    {
                        fallbackOk = ok;
                        fallbackError = error;
                    });
                    if (fallbackOk)
                    {
                        for (var attempt = 0; attempt < 3; attempt += 1)
                        {
                            yield return QueryMode();
                            if (string.Equals(_currentMode, normalized, StringComparison.OrdinalIgnoreCase))
                            {
                                readbackOk = true;
                                break;
                            }
                            yield return new WaitForSecondsRealtime(0.2f);
                        }
                    }
                    else
                    {
                        _rawText.Set($"Set mode fallback(read) failed: {fallbackError}");
                    }
                }
            }

            if (!readbackOk)
            {
                ShowToast($"Mode readback mismatch (want {normalized}, got {_currentMode})");
            }
        }

        private IEnumerator TrySetModeFallbackRead(string modeRaw, Action<bool, string> onDone)
        {
            var uri = $"{_baseUrl}/api/mode";
            var payload = new JObject
            {
                ["runId"] = "quest3-smoke",
                ["frameSeq"] = Math.Max(1, _modeSeq++),
                ["mode"] = modeRaw,
                ["source"] = "xr",
                ["tsMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["deviceId"] = GetDeviceId(),
            };
            using var request = new UnityWebRequest(uri, UnityWebRequest.kHttpVerbPOST);
            request.uploadHandler = new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(payload.ToString(Newtonsoft.Json.Formatting.None)));
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            request.SetRequestHeader("Content-Type", "application/json");
            ApplyApiKeyHeader(request);

            yield return request.SendWebRequest();
            if (request.result == UnityWebRequest.Result.Success)
            {
                onDone?.Invoke(true, string.Empty);
                yield break;
            }

            onDone?.Invoke(false, request.error ?? "unknown");
        }

        private void RefreshAllStatusLines()
        {
            ResolveRefs();
            var liveEnabled = _scanController != null && _scanController.IsLiveEnabled;
            if (_scanController != null)
            {
                _liveButton?.SetLabel(liveEnabled ? "Live Stop" : "Live Start");
            }
            else
            {
                _liveButton?.SetLabel("Live Start");
            }
            if (_liveToggle != null)
            {
                _suppressLiveToggleCallback = true;
                _liveToggle.SetIsOnWithoutNotify(liveEnabled);
                _suppressLiveToggleCallback = false;
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
                    $"CaptureHz: {_scanController.CaptureTargetHz} | Src: {_scanController.CaptureSource} {_scanController.CaptureFrameWidth}x{_scanController.CaptureFrameHeight} | Inflight: {_scanController.InflightCount}/{_scanController.LiveMaxInflight} | ReadbackReq: {_scanController.CaptureActiveReadbacks} | Async: {(_scanController.CaptureAsyncReadbackEnabled ? "ON" : "OFF")} / {(_scanController.CaptureSupportsAsyncReadback ? "supported" : "unsupported")}";
            }
            var probeCount10s = GetProbeCount10s();
            captureText += $" | probe10s={probeCount10s}";
            if (!string.IsNullOrWhiteSpace(_providerSummary))
            {
                captureText += $" | {_providerSummary}";
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
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var ocrAge = _lastOcrTsMs > 0 ? $"{Math.Max(0, nowMs - _lastOcrTsMs)}ms" : "-";
            var detAge = _lastDetTsMs > 0 ? $"{Math.Max(0, nowMs - _lastDetTsMs)}ms" : "-";
            var riskAge = _lastRiskTsMs > 0 ? $"{Math.Max(0, nowMs - _lastRiskTsMs)}ms" : "-";
            var findAge = _lastFindTsMs > 0 ? $"{Math.Max(0, nowMs - _lastFindTsMs)}ms" : "-";
            var targetAge = _lastTargetTsMs > 0 ? $"{Math.Max(0, nowMs - _lastTargetTsMs)}ms" : "-";
            var guidanceAge = _lastGuidanceTsMs > 0 ? $"{Math.Max(0, nowMs - _lastGuidanceTsMs)}ms" : "-";
            var asrAge = _lastAsrTsMs > 0 ? $"{Math.Max(0, nowMs - _lastAsrTsMs)}ms" : "-";
            var ttsAge = _lastTtsTsMs > 0 ? $"{Math.Max(0, nowMs - _lastTtsTsMs)}ms" : "-";
            _lastOcrTextView?.Set($"Last OCR: {_lastOcrText} | Age: {ocrAge}");
            _lastDetTextView?.Set($"Last DET: {_lastDetText} | Age: {detAge}");
            _lastRiskTextView?.Set($"Last RISK: {_lastRiskText} | Age: {riskAge}");
            _lastFindTextView?.Set($"Last FIND: {_lastFindText} | Age: {findAge}");
            _lastTargetTextView?.Set($"Last TARGET: {_lastTargetText} | Age: {targetAge}");
            _guidanceTextView?.Set($"Guidance: {_guidanceText} | Age: {guidanceAge}");
            _lastAsrTextView?.Set($"Last ASR: {_lastAsrText} | Age: {asrAge}");
            _lastTtsTextView?.Set($"Last TTS: {_lastTtsText} | Age: {ttsAge}");

            if (_visionHud != null)
            {
                _hudStatsTextView?.Set(
                    $"HUD: fps={_visionHud.OverlayFps:0.0} decode={_visionHud.LastDecodeMs:0.0}ms bytes={_visionHud.LastAssetBytes} " +
                    $"segAge={(_visionHud.LastSegAgeMs >= 0 ? _visionHud.LastSegAgeMs + "ms" : "-")} " +
                    $"depthAge={(_visionHud.LastDepthAgeMs >= 0 ? _visionHud.LastDepthAgeMs + "ms" : "-")} " +
                    $"detAge={(_visionHud.LastDetAgeMs >= 0 ? _visionHud.LastDetAgeMs + "ms" : "-")}");
            }
            else
            {
                _hudStatsTextView?.Set("HUD: unavailable");
            }

            var state = _scanController != null ? _scanController.LastScanState : _scanStatus;
            var scanErr = _scanController != null ? _scanController.LastScanError : string.Empty;
            var err = !string.IsNullOrWhiteSpace(_scanError) ? _scanError : scanErr;
            _scanStateText.Set(string.IsNullOrWhiteSpace(err)
                ? $"Scan: {state} | live={(liveEnabled ? "ON" : "OFF")} | rec={(_recordingActive ? "ON" : "OFF")} | pinned={IsPinned()} | controls={(_actionControlsVisible ? "on" : "off")}"
                : $"Scan: {state} ({err}) | live={(liveEnabled ? "ON" : "OFF")} | rec={(_recordingActive ? "ON" : "OFF")} | pinned={IsPinned()} | controls={(_actionControlsVisible ? "on" : "off")}");

            if (_selfTestRunner != null)
            {
                _selfTestStatus = _selfTestRunner.CurrentStatus;
                _selfTestSummary = _selfTestRunner.CurrentSummary;
            }
            _selfTestText.Set($"SelfTest: {_selfTestStatus} | {_selfTestSummary}");

            if (_rawVisible)
            {
                var providerAge = _providerTsMs > 0 ? $"{Math.Max(0, nowMs - _providerTsMs)}ms" : "-";
                var hint = $"trackSession={_targetSessionId} | passthrough={GetPassthroughStatus()} | guideAudio={(_guidanceAudioEnabled ? "on" : "off")} | guideHaptics={(_guidanceHapticsEnabled ? "on" : "off")} | asr={_lastAsrText}({asrAge}) | tts={_lastTtsText}({ttsAge}) | autoVoice={(_autoVoiceCommandEnabled ? "on" : "off")} | providers=[{_providerSummary}] age={providerAge}";
                if (probeCount10s >= 8 && !liveEnabled)
                {
                    hint = "MainThread Spike suspect: probe polling | " + hint;
                }
                _rawText.Set(hint);
            }

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

        private void TrackProbeRequest(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            _probeRequestTsMs.Enqueue(nowMs);
            while (_probeRequestTsMs.Count > 0 && nowMs - _probeRequestTsMs.Peek() > 10000)
            {
                _probeRequestTsMs.Dequeue();
            }
        }

        private int GetProbeCount10s()
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            while (_probeRequestTsMs.Count > 0 && nowMs - _probeRequestTsMs.Peek() > 10000)
            {
                _probeRequestTsMs.Dequeue();
            }
            return _probeRequestTsMs.Count;
        }

        private void SetLiveEnabledFromUi(bool enabled)
        {
            ResolveRefs();
            if (_scanController == null)
            {
                ShowToast("Live Failed: scan-controller missing");
                RefreshAllStatusLines();
                return;
            }

            _scanController.SetLiveEnabled(enabled);
            _scanStatus = enabled ? "live" : "idle";
            _liveButton?.SetLabel(enabled ? "Live Stop" : "Live Start");
            ShowToast(enabled ? "Live ON" : "Live OFF");
            RefreshAllStatusLines();
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

        private void StartVoiceCapture()
        {
            if (_voiceRecordingActive)
            {
                return;
            }
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!UnityEngine.Android.Permission.HasUserAuthorizedPermission(UnityEngine.Android.Permission.Microphone))
            {
                UnityEngine.Android.Permission.RequestUserPermission(UnityEngine.Android.Permission.Microphone);
                ShowToast("Mic permission requested");
                return;
            }
#endif
            if (Microphone.devices == null || Microphone.devices.Length == 0)
            {
                ShowToast("Mic unavailable");
                return;
            }

            _voiceMicDevice = Microphone.devices[0];
            _voiceMicFrequency = 16000;
            _voiceMicClip = Microphone.Start(_voiceMicDevice, false, 8, _voiceMicFrequency);
            _voiceRecordingStartRealtime = Time.realtimeSinceStartup;
            _voiceRecordingActive = _voiceMicClip != null;
            ShowToast(_voiceRecordingActive ? "PTT recording..." : "PTT start failed");
        }

        private void StopVoiceCaptureAndSend()
        {
            if (!_voiceRecordingActive)
            {
                ShowToast("PTT not active");
                return;
            }
            _voiceRecordingActive = false;
            var device = string.IsNullOrWhiteSpace(_voiceMicDevice) ? null : _voiceMicDevice;
            var clip = _voiceMicClip;
            var position = device != null ? Microphone.GetPosition(device) : 0;
            try
            {
                if (device != null)
                {
                    Microphone.End(device);
                }
            }
            catch
            {
                // ignore stop errors
            }
            _voiceMicClip = null;
            if (clip == null || position <= 0)
            {
                ShowToast("PTT empty audio");
                return;
            }

            var channels = Math.Max(1, clip.channels);
            var sampleCount = Math.Max(1, position * channels);
            var samples = new float[sampleCount];
            if (!clip.GetData(samples, 0))
            {
                ShowToast("PTT read failed");
                return;
            }
            var wav = EncodePcm16Wav(samples, clip.frequency, channels);
            StartCoroutine(PostAsrAudio(wav));
        }

        private IEnumerator PostAsrAudio(byte[] wavBytes)
        {
            if (wavBytes == null || wavBytes.Length == 0)
            {
                ShowToast("ASR send failed");
                yield break;
            }
            var url = $"{_baseUrl}/api/asr";
            TrackProbeRequest("/api/asr");
            using var request = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST);
            request.uploadHandler = new UploadHandlerRaw(wavBytes);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.timeout = Mathf.CeilToInt(QueryTimeoutSec);
            request.SetRequestHeader("Content-Type", "audio/wav");
            ApplyApiKeyHeader(request);
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                ShowToast("ASR request failed");
                _scanError = request.error ?? "asr failed";
                yield break;
            }

            var text = request.downloadHandler != null ? request.downloadHandler.text : "{}";
            try
            {
                var obj = JObject.Parse(string.IsNullOrWhiteSpace(text) ? "{}" : text);
                var payload = new JObject
                {
                    ["text"] = (obj.Value<string>("text") ?? string.Empty).Trim(),
                };
                UpdateAsrFromEvent(payload);
            }
            catch
            {
                _lastAsrText = "asr ok";
                _lastAsrTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            }
            ShowToast("PTT sent");
        }

        private static byte[] EncodePcm16Wav(float[] samples, int sampleRate, int channels)
        {
            var sampleCount = samples != null ? samples.Length : 0;
            var byteCount = sampleCount * 2;
            var outBytes = new byte[44 + byteCount];
            // RIFF header
            System.Text.Encoding.ASCII.GetBytes("RIFF").CopyTo(outBytes, 0);
            BitConverter.GetBytes(36 + byteCount).CopyTo(outBytes, 4);
            System.Text.Encoding.ASCII.GetBytes("WAVE").CopyTo(outBytes, 8);
            // fmt chunk
            System.Text.Encoding.ASCII.GetBytes("fmt ").CopyTo(outBytes, 12);
            BitConverter.GetBytes(16).CopyTo(outBytes, 16); // PCM header size
            BitConverter.GetBytes((short)1).CopyTo(outBytes, 20); // PCM
            BitConverter.GetBytes((short)channels).CopyTo(outBytes, 22);
            BitConverter.GetBytes(sampleRate).CopyTo(outBytes, 24);
            var byteRate = sampleRate * channels * 2;
            BitConverter.GetBytes(byteRate).CopyTo(outBytes, 28);
            BitConverter.GetBytes((short)(channels * 2)).CopyTo(outBytes, 32);
            BitConverter.GetBytes((short)16).CopyTo(outBytes, 34);
            // data chunk
            System.Text.Encoding.ASCII.GetBytes("data").CopyTo(outBytes, 36);
            BitConverter.GetBytes(byteCount).CopyTo(outBytes, 40);
            var offset = 44;
            for (var i = 0; i < sampleCount; i += 1)
            {
                var v = Mathf.Clamp(samples[i], -1f, 1f);
                var s = (short)Mathf.RoundToInt(v * short.MaxValue);
                BitConverter.GetBytes(s).CopyTo(outBytes, offset);
                offset += 2;
            }
            return outBytes;
        }

        private static AudioClip BuildBeepClip()
        {
            const int frequency = 24000;
            const float duration = 0.2f;
            var length = Mathf.Max(1, Mathf.RoundToInt(frequency * duration));
            var clip = AudioClip.Create("BYES_Beep", length, 1, frequency, false);
            var samples = new float[length];
            for (var i = 0; i < length; i += 1)
            {
                var t = (float)i / frequency;
                samples[i] = Mathf.Sin(2f * Mathf.PI * 880f * t) * 0.22f;
            }
            clip.SetData(samples, 0);
            return clip;
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
            Vector2 size,
            bool allowWrap = false)
        {
            var textGo = CreateUiObject(name, parent, anchor, anchor, size, anchoredPos);
            var tmpType = Type.GetType("TMPro.TextMeshProUGUI, Unity.TextMeshPro");
            if (tmpType != null)
            {
                var component = textGo.AddComponent(tmpType);
                return new TmpTextView(component, value, fontSize, allowWrap);
            }

            var uiText = textGo.AddComponent<Text>();
            uiText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            uiText.color = Color.white;
            uiText.alignment = fallbackAnchor;
            uiText.horizontalOverflow = allowWrap ? HorizontalWrapMode.Wrap : HorizontalWrapMode.Overflow;
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

        private Toggle CreateLiveToggle(Transform parent, string name, string label, Vector2 anchoredPos, Action<bool> onChanged, bool markAsAction = false)
        {
            var rowGo = CreateUiObject(name, parent, new Vector2(0.5f, 0f), new Vector2(0.5f, 0f), new Vector2(210f, 74f), anchoredPos);
            var rowImage = rowGo.AddComponent<Image>();
            rowImage.color = new Color(0.12f, 0.20f, 0.33f, 0.95f);

            var labelView = CreateText("Label", rowGo.transform, label, 28, TextAnchor.MiddleLeft, new Vector2(0.5f, 0.5f), new Vector2(-24f, 0f), new Vector2(130f, 56f));
            labelView.Set(label);

            var box = CreateUiObject("Box", rowGo.transform, new Vector2(1f, 0.5f), new Vector2(1f, 0.5f), new Vector2(44f, 44f), new Vector2(-20f, 0f));
            var boxImage = box.AddComponent<Image>();
            boxImage.color = new Color(0.17f, 0.17f, 0.17f, 0.98f);

            var check = CreateUiObject("Check", box.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(30f, 30f), Vector2.zero);
            var checkImage = check.AddComponent<Image>();
            checkImage.color = new Color(0.08f, 0.78f, 0.24f, 1f);

            var toggle = rowGo.AddComponent<Toggle>();
            toggle.targetGraphic = rowImage;
            toggle.graphic = checkImage;
            toggle.transition = Selectable.Transition.ColorTint;
            var colors = toggle.colors;
            colors.normalColor = new Color(0.12f, 0.20f, 0.33f, 0.95f);
            colors.highlightedColor = new Color(0.20f, 0.30f, 0.46f, 1f);
            colors.pressedColor = new Color(0.10f, 0.15f, 0.24f, 1f);
            colors.selectedColor = colors.highlightedColor;
            colors.disabledColor = new Color(0.25f, 0.25f, 0.25f, 0.7f);
            colors.fadeDuration = 0.05f;
            toggle.colors = colors;
            toggle.onValueChanged.AddListener(value => onChanged?.Invoke(value));

            if (markAsAction)
            {
                _actionControls.Add(rowGo);
            }

            return toggle;
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
                case "read":
                case "read_text":
                case "inspect":
                    return normalized == "read" ? "read_text" : normalized;
                default:
                    return "walk";
            }
        }

        private static string ResolveStableDeviceId()
        {
            var fromTelemetry = (ByesFrameTelemetry.DeviceId ?? string.Empty).Trim();
            if (!string.IsNullOrWhiteSpace(fromTelemetry))
            {
                return fromTelemetry;
            }

            var cached = PlayerPrefs.GetString(PrefQuestDeviceId, string.Empty).Trim();
            if (!string.IsNullOrWhiteSpace(cached))
            {
                return cached;
            }

            var generated = Guid.NewGuid().ToString("N");
            PlayerPrefs.SetString(PrefQuestDeviceId, generated);
            PlayerPrefs.Save();
            return generated;
        }

        private void SyncLocalModeState(string apiMode)
        {
            var normalized = NormalizeMode(apiMode);
            _currentMode = normalized;

            var mode = normalized switch
            {
                "read_text" => ByesMode.ReadText,
                "inspect" => ByesMode.Inspect,
                _ => ByesMode.Walk,
            };

            var state = ByesSystemState.Instance;
            state?.SetMode(mode);

            var manager = ByesModeManager.Instance;
            if (manager != null)
            {
                manager.SetModeLocal(mode);
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
            private readonly PropertyInfo _wordWrapProperty;
            private string _lastValue = string.Empty;

            public TmpTextView(Component component, string value, int fontSize, bool allowWrap)
            {
                _component = component;
                var type = component.GetType();
                _textProperty = type.GetProperty("text");
                _fontSizeProperty = type.GetProperty("fontSize");
                _colorProperty = type.GetProperty("color");
                _alignmentProperty = type.GetProperty("alignment");
                _wordWrapProperty = type.GetProperty("enableWordWrapping");

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

                if (_wordWrapProperty != null && _wordWrapProperty.PropertyType == typeof(bool))
                {
                    _wordWrapProperty.SetValue(_component, allowWrap, null);
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
