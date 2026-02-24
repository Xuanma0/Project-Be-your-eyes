using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NativeWebSocket;
using UnityEngine;
using UnityEngine.Networking;
using BeYourEyes.Presenters.DebugHUD;
using BYES.Telemetry;

namespace BeYourEyes.Adapters.Networking
{
    public enum FrameSendResult
    {
        Accepted,
        DroppedBusy,
        DroppedNoConnection,
        DroppedInvalid,
    }

    public sealed class GatewayClient : MonoBehaviour
    {
        [Header("Gateway")]
        [SerializeField] private string baseUrl = "http://127.0.0.1:8000";
        [SerializeField] private string wsUrl = "ws://127.0.0.1:8000/ws/events";
        [SerializeField] private string sessionId = "default";
        [SerializeField] private bool connectOnEnable = true;
        [SerializeField] private bool autoReconnect = true;
        [SerializeField] private float reconnectMinDelaySec = 0.5f;
        [SerializeField] private float reconnectMaxDelaySec = 8f;

        [Header("Logging")]
        [SerializeField] private bool verboseLogs = true;
        [SerializeField] private int frameOkLogEvery = 30;

        [Header("Health Probe")]
        [SerializeField] private bool enableHealthProbe = true;
        [SerializeField] private float healthProbeIntervalSec = 1f;
        [SerializeField] private int healthProbeStaleThresholdMs = 1500;

        [Header("Capability Probe")]
        [SerializeField] private bool enableExternalReadinessProbe = true;
        [SerializeField] private float readinessProbeIntervalSec = 2f;
        [SerializeField] private int probeFailureThreshold = 2;

        [Header("Event Guard")]
        [SerializeField] private EventGuard eventGuard = new EventGuard();
        [SerializeField] private LocalActionPlanGate localActionPlanGate = new LocalActionPlanGate();
        [SerializeField] private BeYourEyes.Unity.Interaction.LocalSafetyFallback localSafetyFallback;

        private WebSocket webSocket;
        private bool wsConnecting;
        private bool frameRequestInFlight;
        private int frameOkCount;
        private int droppedFrameCount;
        private bool shuttingDown;
        private int reconnectAttempt;
        private string lastDisconnectReason = "none";
        private long lastMessageAtMs = -1;
        private bool reconnectLoopRunning;
        private CancellationTokenSource reconnectCts;

        private readonly Dictionary<long, long> sentAtMs = new Dictionary<long, long>();
        private readonly Queue<long> sentSeqOrder = new Queue<long>();
        private readonly HashSet<long> ttfaObservedSeq = new HashSet<long>();
        private const int MaxSeqHistory = 256;
        private const int SentRecordTtlMs = 30000;
        private const double TtfaEmaAlpha = 0.2;
        private long lastTtfaMs = -1;
        private double ttfaEmaMs = -1;
        private int ttfaSampleCount;
        private bool replayMode;
        private long replayLastSeqSeen = -1;

        private string lastHealthStatus = "UNKNOWN";
        private string lastHealthReason = string.Empty;
        private string lastRiskLevel = "warn";
        private int lastHealthRttMs = -1;
        private long lastHealthOkAtMs = -1;
        private string activeIntent = "none";
        [SerializeField] private string defaultAskQuestion = "What is in front of me?";
        private string currentQuestion = "What is in front of me?";
        private Coroutine healthProbeRoutine;
        private bool healthProbeInFlight;
        private bool readinessProbeInFlight;
        private long lastReadinessProbeAtMs = -1;
        private long lastReadinessOkAtMs = -1;
        private int readyToolsCount = -1;
        private int unavailableToolsCount = -1;
        private bool readinessKnown;
        private readonly Dictionary<string, bool> toolAvailability = new Dictionary<string, bool>();
        private int consecutiveHealthProbeFailures;
        private int consecutiveReadinessProbeFailures;
        private long healthProbeSuccessCount;
        private long healthProbeFailureCount;
        private long readinessProbeSuccessCount;
        private long readinessProbeFailureCount;
        private CapabilityState capabilityState = CapabilityState.OK;
        private long capabilityStateTransitionCount;
        private string capabilityTransitionReason = "init";

        public event Action<JObject> OnGatewayEvent;
        public event Action<JObject> OnUiEventAccepted;
        public event Action<bool, string> OnWebSocketStateChanged;
        public event Action<CapabilityState, string> OnCapabilityStateChanged;
        public event Action<long, string, long> OnTtfaObserved;
        public event Action<string> OnReplayBlockedNetworkAction;

        public string BaseUrl => NormalizeBaseUrl(baseUrl);
        public string WsUrl => string.IsNullOrWhiteSpace(wsUrl) ? "ws://127.0.0.1:8000/ws/events" : wsUrl.Trim();
        public string SessionId => string.IsNullOrWhiteSpace(sessionId) ? "default" : sessionId.Trim();
        public bool IsFrameBusy => frameRequestInFlight;
        public bool IsConnected => webSocket != null && webSocket.State == WebSocketState.Open;
        public string LastDisconnectReason => lastDisconnectReason;
        public int ReconnectAttempt => reconnectAttempt;
        public long LastMessageAtMs => lastMessageAtMs;
        public bool IsReplayMode => replayMode;
        public long ReplayLastSeqSeen => replayLastSeqSeen;
        public long LastTtfaMs => lastTtfaMs;
        public double TtfaEmaMs => ttfaEmaMs;
        public int TtfaSampleCount => ttfaSampleCount;
        public string LastHealthStatus => lastHealthStatus;
        public string LastHealthReason => lastHealthReason;
        public int LastHealthRttMs => lastHealthRttMs;
        public string ActiveIntent => activeIntent;
        public string CurrentIntentKind => activeIntent;
        public string CurrentQuestion => string.IsNullOrWhiteSpace(currentQuestion) ? ResolveDefaultAskQuestion() : currentQuestion;
        public CapabilityState CurrentCapabilityState => capabilityState;
        public long LastHealthOkAtMs => lastHealthOkAtMs;
        public long LastReadinessOkAtMs => lastReadinessOkAtMs;
        public int ReadyToolsCount => readyToolsCount;
        public int UnavailableToolsCount => unavailableToolsCount;
        public bool ReadinessKnown => readinessKnown;
        public long HealthProbeSuccessCount => healthProbeSuccessCount;
        public long HealthProbeFailureCount => healthProbeFailureCount;
        public long ReadinessProbeSuccessCount => readinessProbeSuccessCount;
        public long ReadinessProbeFailureCount => readinessProbeFailureCount;
        public long CapabilityStateTransitionCount => capabilityStateTransitionCount;
        public string CapabilityTransitionReason => capabilityTransitionReason;
        public bool IsVlmAvailable => IsToolAvailable("real_vlm");
        public long EventAcceptedCount => eventGuard != null ? eventGuard.Accepted : 0;
        public long EventDroppedExpiredCount => eventGuard != null ? eventGuard.DroppedExpired : 0;
        public long EventDroppedOutOfOrderCount => eventGuard != null ? eventGuard.DroppedOutOfOrder : 0;
        public long EventDroppedByFallbackCount => eventGuard != null ? eventGuard.DroppedByFallback : 0;
        public long EventLastSeqSeen => eventGuard != null ? eventGuard.LastSeqSeen : -1;
        public int EventAllowedReorderSeq => eventGuard != null ? eventGuard.AllowedReorderSeq : 0;
        public int EventDefaultTtlMs => eventGuard != null ? eventGuard.DefaultEventTtlMs : 1500;
        public long ActionPlanGateAcceptedCount => localActionPlanGate != null ? localActionPlanGate.AcceptedCount : 0;
        public long ActionPlanGateBlockedCount => localActionPlanGate != null ? localActionPlanGate.BlockedCount : 0;
        public long ActionPlanGatePatchedCount => localActionPlanGate != null ? localActionPlanGate.PatchedCount : 0;
        public string ActionPlanGateLastReason => localActionPlanGate != null ? localActionPlanGate.LastReason : "n/a";

        private void OnEnable()
        {
            shuttingDown = false;
            eventGuard?.ResetRuntime();
            localActionPlanGate?.ResetRuntime();
            ResetCapabilityRuntime();
            if (connectOnEnable && !replayMode)
            {
                ConnectWebSocket();
            }
            StartHealthProbeLoop();
        }

        private async void OnDisable()
        {
            shuttingDown = true;
            StopHealthProbeLoop();
            StopReconnectLoop();
            await CloseWebSocketInternal(notifyState: true, reasonOverride: "disabled");
        }

        private async void OnDestroy()
        {
            shuttingDown = true;
            StopHealthProbeLoop();
            StopReconnectLoop();
            await CloseWebSocketInternal(notifyState: true, reasonOverride: "destroyed");
        }

        private void Update()
        {
#if !UNITY_WEBGL || UNITY_EDITOR
            webSocket?.DispatchMessageQueue();
#endif
        }

        public void SetSessionId(string value)
        {
            sessionId = string.IsNullOrWhiteSpace(value) ? "default" : value.Trim();
        }

        public void SetGatewayEndpoints(string newBaseUrl, string newWsUrl, bool reconnect = true)
        {
            if (!string.IsNullOrWhiteSpace(newBaseUrl))
            {
                baseUrl = NormalizeBaseUrl(newBaseUrl);
            }

            if (!string.IsNullOrWhiteSpace(newWsUrl))
            {
                wsUrl = newWsUrl.Trim();
            }

            if (reconnect)
            {
                ConnectWebSocket();
            }
        }

        public async void ConnectWebSocket()
        {
            if (shuttingDown || wsConnecting || replayMode)
            {
                return;
            }

            StopReconnectLoop();
            var connected = await ConnectWebSocketInternal();
            if (!connected)
            {
                EnsureReconnectLoop();
            }
        }

        public bool TrySendFrame(byte[] jpg, string metaJson)
        {
            return TrySendFrameDetailed(jpg, metaJson) == FrameSendResult.Accepted;
        }

        public bool TrySendFrame(byte[] jpg, string metaJson, long seq, long timestampMs)
        {
            return TrySendFrameDetailed(jpg, metaJson, seq, timestampMs) == FrameSendResult.Accepted;
        }

        public FrameSendResult TrySendFrameDetailed(byte[] jpg, string metaJson, long seq = -1, long timestampMs = -1)
        {
            if (jpg == null || jpg.Length == 0)
            {
                return FrameSendResult.DroppedInvalid;
            }

            if (replayMode)
            {
                OnReplayBlockedNetworkAction?.Invoke("frame");
                return FrameSendResult.DroppedNoConnection;
            }

            if (!IsConnected)
            {
                return FrameSendResult.DroppedNoConnection;
            }

            if (frameRequestInFlight)
            {
                droppedFrameCount++;
                if (droppedFrameCount % 20 == 1)
                {
                    Debug.Log($"[GatewayClient] frame dropped: busy (dropped={droppedFrameCount})");
                }

                return FrameSendResult.DroppedBusy;
            }

            if (seq > 0)
            {
                RegisterSentFrame(seq, timestampMs > 0 ? timestampMs : DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            }

            StartCoroutine(SendFrameRoutine(jpg, metaJson, seq));
            return FrameSendResult.Accepted;
        }

        public void SendConfirm(string confirmId, string choice, string source = "unity_hud", Action<bool> onDone = null)
        {
            if (replayMode)
            {
                OnReplayBlockedNetworkAction?.Invoke("confirm");
                onDone?.Invoke(false);
                return;
            }

            if (string.IsNullOrWhiteSpace(confirmId))
            {
                Debug.LogWarning("[GatewayClient] confirm skipped: empty confirmId");
                onDone?.Invoke(false);
                return;
            }

            var body = new JObject
            {
                ["confirmId"] = confirmId.Trim(),
                ["answer"] = NormalizeConfirmChoice(choice),
                ["source"] = string.IsNullOrWhiteSpace(source) ? "unity_hud" : source.Trim(),
            };
            StartCoroutine(PostJsonRoutine(
                BuildApiUrl("/api/confirm"),
                body.ToString(Formatting.None),
                success =>
                {
                    Debug.Log(success
                        ? $"[GatewayClient] confirm posted: id={confirmId}"
                        : $"[GatewayClient] confirm failed: id={confirmId}");
                    onDone?.Invoke(success);
                }
            ));
        }

        public void SendDevIntent(string intent, string question, Action<bool, string> onDone = null)
        {
            if (replayMode)
            {
                OnReplayBlockedNetworkAction?.Invoke("intent");
                onDone?.Invoke(false, "replay_mode");
                return;
            }

            var normalized = NormalizeIntent(intent);
            var resolvedQuestion = string.IsNullOrWhiteSpace(question) ? ResolveDefaultAskQuestion() : question.Trim();
            var payload = new JObject
            {
                ["intent"] = normalized,
            };

            if ((normalized == "ask" || normalized == "qa") && !string.IsNullOrWhiteSpace(resolvedQuestion))
            {
                payload["question"] = resolvedQuestion;
            }

            StartCoroutine(PostJsonRoutine(
                BuildApiUrl("/api/dev/intent"),
                payload.ToString(Formatting.None),
                success =>
                {
                    if (success)
                    {
                        activeIntent = normalized;
                        if ((normalized == "ask" || normalized == "qa") && !string.IsNullOrWhiteSpace(resolvedQuestion))
                        {
                            currentQuestion = resolvedQuestion;
                        }
                    }
                    var message = success ? "ok" : "error";
                    onDone?.Invoke(success, message);
                }
            ));
        }

        public void SetIntentScanText(bool enabled, Action<bool, string> onDone = null)
        {
            var target = enabled ? "scan_text" : "none";
            SendDevIntent(target, string.Empty, onDone);
        }

        public void TriggerAskOnce(string question, Action<bool, string> onDone = null)
        {
            var resolvedQuestion = string.IsNullOrWhiteSpace(question) ? ResolveDefaultAskQuestion() : question.Trim();
            SendDevIntent("ask", resolvedQuestion, onDone);
        }

        public bool IsToolAvailable(string toolName)
        {
            if (string.IsNullOrWhiteSpace(toolName))
            {
                return false;
            }

            if (!readinessKnown)
            {
                return false;
            }

            return toolAvailability.TryGetValue(toolName.Trim().ToLowerInvariant(), out var ready) && ready;
        }

        public void FetchPendingConfirm(Action<bool, JObject> onDone)
        {
            if (replayMode)
            {
                OnReplayBlockedNetworkAction?.Invoke("confirm_poll");
                onDone?.Invoke(false, null);
                return;
            }

            var url = BuildApiUrl($"/api/confirm/pending?sessionId={UnityWebRequest.EscapeURL(SessionId)}");
            StartCoroutine(GetJsonRoutine(url, onDone));
        }

        public async void EnterReplayMode()
        {
            if (replayMode)
            {
                return;
            }

            replayMode = true;
            replayLastSeqSeen = -1;
            StopReconnectLoop();
            StopHealthProbeLoop();
            await CloseWebSocketInternal(notifyState: true, reasonOverride: "replay_mode");
        }

        public void ExitReplayMode(bool reconnect = false)
        {
            if (!replayMode)
            {
                if (reconnect)
                {
                    ConnectWebSocket();
                }
                return;
            }

            replayMode = false;
            replayLastSeqSeen = -1;
            eventGuard?.ResetRuntime();
            localActionPlanGate?.ResetRuntime();
            StartHealthProbeLoop();
            if (reconnect && connectOnEnable)
            {
                ConnectWebSocket();
            }
        }

        private IEnumerator SendFrameRoutine(byte[] jpg, string metaJson, long seq)
        {
            frameRequestInFlight = true;
            try
            {
                var runIdForTelemetry = SessionId;
                var frameSeqForTelemetry = seq > 0 ? seq : -1;
                var captureTsForTelemetry = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var deviceIdForTelemetry = ByesFrameTelemetry.DeviceId;
                var deviceTimeBaseForTelemetry = ByesFrameTelemetry.DeviceTimeBase;
                if (!string.IsNullOrWhiteSpace(metaJson))
                {
                    try
                    {
                        var metaObj = JObject.Parse(metaJson);
                        var metaRunId = ReadString(metaObj, "runId");
                        if (string.IsNullOrWhiteSpace(metaRunId))
                        {
                            metaRunId = ReadString(metaObj, "sessionId");
                        }
                        if (string.IsNullOrWhiteSpace(metaRunId))
                        {
                            metaRunId = ReadString(metaObj, "session_id");
                        }
                        if (!string.IsNullOrWhiteSpace(metaRunId))
                        {
                            runIdForTelemetry = metaRunId;
                        }
                        if (frameSeqForTelemetry <= 0 && TryReadLong(metaObj, "seq", out var parsedSeq) && parsedSeq > 0)
                        {
                            frameSeqForTelemetry = parsedSeq;
                        }
                        if (TryReadLong(metaObj, "captureTsMs", out var parsedCaptureTs) && parsedCaptureTs > 0)
                        {
                            captureTsForTelemetry = parsedCaptureTs;
                        }
                        else if (TryReadLong(metaObj, "tsCaptureMs", out var parsedTsCaptureMs) && parsedTsCaptureMs > 0)
                        {
                            captureTsForTelemetry = parsedTsCaptureMs;
                        }
                        var metaDeviceId = ReadString(metaObj, "deviceId");
                        if (!string.IsNullOrWhiteSpace(metaDeviceId))
                        {
                            deviceIdForTelemetry = metaDeviceId;
                        }
                        var metaTimeBase = ReadString(metaObj, "deviceTimeBase");
                        if (!string.IsNullOrWhiteSpace(metaTimeBase))
                        {
                            deviceTimeBaseForTelemetry = metaTimeBase;
                        }
                    }
                    catch
                    {
                    }
                }

                var form = new WWWForm();
                form.AddBinaryData("image", jpg, "frame.jpg", "image/jpeg");
                if (!string.IsNullOrWhiteSpace(metaJson))
                {
                    form.AddField("meta", metaJson);
                }
                form.AddField("captureTsMs", Math.Max(0, captureTsForTelemetry).ToString());
                form.AddField("deviceId", string.IsNullOrWhiteSpace(deviceIdForTelemetry) ? "unity-device" : deviceIdForTelemetry);
                form.AddField("deviceTimeBase", string.IsNullOrWhiteSpace(deviceTimeBaseForTelemetry) ? "unix_ms" : deviceTimeBaseForTelemetry);

                using (var req = UnityWebRequest.Post(BuildApiUrl("/api/frame"), form))
                {
                    yield return req.SendWebRequest();
                    if (req.result == UnityWebRequest.Result.Success)
                    {
                        frameOkCount++;
                        ByesFrameTelemetry.OnFrameSentToGateway(
                            runIdForTelemetry,
                            frameSeqForTelemetry > 0 ? frameSeqForTelemetry : 1,
                            captureTsForTelemetry
                        );
                        if (verboseLogs && frameOkCount % Math.Max(1, frameOkLogEvery) == 0)
                        {
                            Debug.Log($"[GatewayClient] frame POST 200 x{frameOkCount}");
                        }
                    }
                    else
                    {
                        Debug.LogWarning($"[GatewayClient] frame POST failed: {req.error}");
                        if (seq > 0)
                        {
                            RemoveSentFrame(seq);
                        }
                    }
                }
            }
            finally
            {
                frameRequestInFlight = false;
            }
        }

        private IEnumerator PostJsonRoutine(string url, string jsonBody, Action<bool> onDone)
        {
            var bodyBytes = Encoding.UTF8.GetBytes(string.IsNullOrWhiteSpace(jsonBody) ? "{}" : jsonBody);
            using (var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
            {
                req.uploadHandler = new UploadHandlerRaw(bodyBytes);
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                yield return req.SendWebRequest();

                var success = req.result == UnityWebRequest.Result.Success;
                if (!success)
                {
                    Debug.LogWarning($"[GatewayClient] POST {url} failed: {req.error}");
                }

                onDone?.Invoke(success);
            }
        }

        private IEnumerator GetJsonRoutine(string url, Action<bool, JObject> onDone)
        {
            using (var req = UnityWebRequest.Get(url))
            {
                req.downloadHandler = new DownloadHandlerBuffer();
                yield return req.SendWebRequest();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning($"[GatewayClient] GET {url} failed: {req.error}");
                    onDone?.Invoke(false, null);
                    yield break;
                }

                try
                {
                    var body = string.IsNullOrWhiteSpace(req.downloadHandler.text) ? "{}" : req.downloadHandler.text;
                    var json = JObject.Parse(body);
                    onDone?.Invoke(true, json);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[GatewayClient] GET {url} parse failed: {ex.Message}");
                    onDone?.Invoke(false, null);
                }
            }
        }

        private async Task<bool> ConnectWebSocketInternal()
        {
            if (shuttingDown || wsConnecting)
            {
                return false;
            }

            wsConnecting = true;
            try
            {
                await CloseWebSocketInternal(notifyState: false, reasonOverride: "reconnecting");

                webSocket = new WebSocket(WsUrl);
                webSocket.OnOpen += HandleWsOpen;
                webSocket.OnClose += HandleWsClose;
                webSocket.OnError += HandleWsError;
                webSocket.OnMessage += HandleWsMessage;
                await webSocket.Connect();
                return true;
            }
            catch (Exception ex)
            {
                lastDisconnectReason = SanitizeReason(ex.Message, "connect_failed");
                OnWebSocketStateChanged?.Invoke(false, lastDisconnectReason);
                Debug.LogWarning($"[GatewayClient] WS connect failed: {lastDisconnectReason}");
                return false;
            }
            finally
            {
                wsConnecting = false;
            }
        }

        private async Task CloseWebSocketInternal(bool notifyState, string reasonOverride)
        {
            if (webSocket == null)
            {
                if (notifyState)
                {
                    OnWebSocketStateChanged?.Invoke(false, string.IsNullOrWhiteSpace(reasonOverride) ? lastDisconnectReason : reasonOverride);
                }
                return;
            }

            var socket = webSocket;
            webSocket = null;
            try
            {
                socket.OnOpen -= HandleWsOpen;
                socket.OnClose -= HandleWsClose;
                socket.OnError -= HandleWsError;
                socket.OnMessage -= HandleWsMessage;
                if (socket.State == WebSocketState.Open || socket.State == WebSocketState.Connecting)
                {
                    await socket.Close();
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[GatewayClient] WS close error: {ex.Message}");
            }
            finally
            {
                if (!string.IsNullOrWhiteSpace(reasonOverride))
                {
                    lastDisconnectReason = reasonOverride;
                }
                if (notifyState)
                {
                    OnWebSocketStateChanged?.Invoke(false, lastDisconnectReason);
                }
            }
        }

        private void HandleWsOpen()
        {
            reconnectAttempt = 0;
            lastDisconnectReason = "none";
            Debug.Log("[GatewayClient] WS connected");
            OnWebSocketStateChanged?.Invoke(true, "connected");
        }

        private void HandleWsClose(WebSocketCloseCode code)
        {
            if (shuttingDown)
            {
                return;
            }

            lastDisconnectReason = $"closed:{code}";
            Debug.Log($"[GatewayClient] WS closed: {lastDisconnectReason}");
            OnWebSocketStateChanged?.Invoke(false, lastDisconnectReason);
            EnsureReconnectLoop();
        }

        private void HandleWsError(string error)
        {
            if (shuttingDown)
            {
                return;
            }

            lastDisconnectReason = SanitizeReason(error, "socket_error");
            Debug.LogWarning($"[GatewayClient] WS error: {lastDisconnectReason}");
            OnWebSocketStateChanged?.Invoke(false, lastDisconnectReason);
            EnsureReconnectLoop();
        }

        private void HandleWsMessage(byte[] bytes)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            lastMessageAtMs = nowMs;
            PurgeOldSentFrames(nowMs);

            var text = Encoding.UTF8.GetString(bytes);
            JObject evt;
            try
            {
                evt = JObject.Parse(text);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[GatewayClient] WS payload parse failed: {ex.Message}");
                return;
            }

            if (!TryAcceptUiEvent(evt, defaultType: string.Empty, out var receivedAtMs, out var ttlMs, out _))
            {
                return;
            }

            var type = ReadString(evt, "type");
            var summary = ReadString(evt, "summary");
            if (string.IsNullOrEmpty(summary))
            {
                summary = ReadString(evt, "riskText");
            }

            var healthStatus = ReadString(evt, "healthStatus");
            if (string.IsNullOrWhiteSpace(healthStatus))
            {
                healthStatus = ParseHealthStatusFromSummary(summary);
            }
            if (!string.IsNullOrWhiteSpace(healthStatus))
            {
                lastHealthStatus = healthStatus;
            }

            var healthReason = ReadString(evt, "healthReason");
            if (string.IsNullOrWhiteSpace(healthReason))
            {
                healthReason = ParseHealthReasonFromSummary(summary);
            }
            if (!string.IsNullOrWhiteSpace(healthReason))
            {
                lastHealthReason = healthReason;
            }

            var riskLevel = ReadString(evt, "riskLevel");
            if (!string.IsNullOrWhiteSpace(riskLevel))
            {
                lastRiskLevel = riskLevel;
            }
            var confirmId = ReadString(evt, "confirmId");
            var stage = ReadString(evt, "stage");
            Debug.Log(
                $"[GatewayClient] WS event type={type} summary={summary} healthStatus={healthStatus} riskLevel={riskLevel} stage={stage} confirmId={confirmId}"
            );

            evt["_receivedAtMs"] = receivedAtMs;
            evt["_eventTtlMs"] = ttlMs;

            MaybeRecordTtfa(evt, nowMs);
            UpdateCapabilityState("ws_event");
            PublishAcceptedUiEvent(evt);
        }

        private string BuildApiUrl(string path)
        {
            return $"{BaseUrl.TrimEnd('/')}{path}";
        }

        public bool TryAcceptUiEvent(JObject evt, string defaultType, out long receivedAtMs, out int ttlMs, out string rejectReason, bool isReplay = false)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            receivedAtMs = nowMs;
            ttlMs = EventDefaultTtlMs;
            rejectReason = string.Empty;

            if (evt == null)
            {
                rejectReason = "null_event";
                return false;
            }

            if (!string.IsNullOrWhiteSpace(defaultType) && string.IsNullOrWhiteSpace(ReadString(evt, "type")))
            {
                evt["type"] = defaultType;
            }

            if (isReplay)
            {
                ttlMs = eventGuard != null ? eventGuard.ResolveEventTtlMs(evt) : EventDefaultTtlMs;
                receivedAtMs = nowMs;
                evt["_receivedAtMs"] = receivedAtMs;
                evt["_eventTtlMs"] = ttlMs;
                if (TryReadLong(evt, "seq", out var replaySeq) && replaySeq > replayLastSeqSeen)
                {
                    replayLastSeqSeen = replaySeq;
                }

                rejectReason = string.Empty;
                return true;
            }

            var eventType = ReadString(evt, "type");
            if (string.Equals(eventType, "action_plan", StringComparison.OrdinalIgnoreCase))
            {
                var fallbackNonOk = IsFallbackBlockingEvent(evt);
                var healthStatus = ResolveHealthStatusForEvent(evt);
                var riskLevel = ResolveRiskLevelForEvent(evt);
                if (localActionPlanGate != null)
                {
                    if (!localActionPlanGate.TryProcess(evt, fallbackNonOk, healthStatus, riskLevel, out var gateReason))
                    {
                        rejectReason = gateReason;
                        if (string.Equals(gateReason, LocalActionPlanGate.ReasonFallbackNonOk, StringComparison.Ordinal))
                        {
                            eventGuard?.MarkFallbackDrop();
                        }
                        return false;
                    }
                }
                else if (fallbackNonOk)
                {
                    eventGuard?.MarkFallbackDrop();
                    rejectReason = LocalActionPlanGate.ReasonFallbackNonOk;
                    return false;
                }
            }
            else if (IsFallbackBlockingEvent(evt))
            {
                eventGuard?.MarkFallbackDrop();
                rejectReason = "fallback_non_ok";
                return false;
            }

            if (eventGuard == null)
            {
                if (!TryReadLong(evt, "_receivedAtMs", out var existingReceivedAt) || existingReceivedAt <= 0)
                {
                    evt["_receivedAtMs"] = receivedAtMs;
                }
                else
                {
                    receivedAtMs = existingReceivedAt;
                }
                evt["_eventTtlMs"] = ttlMs;
                return true;
            }

            ttlMs = eventGuard.ResolveEventTtlMs(evt);
            if (!TryReadLong(evt, "_receivedAtMs", out var preservedReceivedAt) || preservedReceivedAt <= 0)
            {
                evt["_receivedAtMs"] = receivedAtMs;
            }
            else
            {
                receivedAtMs = preservedReceivedAt;
            }
            evt["_eventTtlMs"] = ttlMs;

            if (!eventGuard.ShouldAccept(evt, nowMs))
            {
                rejectReason = eventGuard.LastRejectReason;
                return false;
            }

            rejectReason = string.Empty;
            return true;
        }

        public void PublishAcceptedUiEvent(JObject evt)
        {
            if (evt == null)
            {
                return;
            }

            OnUiEventAccepted?.Invoke(evt);
            OnGatewayEvent?.Invoke(evt);
        }

        private string ResolveHealthStatusForEvent(JObject evt)
        {
            var healthStatus = ReadString(evt, "healthStatus");
            if (string.IsNullOrWhiteSpace(healthStatus))
            {
                healthStatus = lastHealthStatus;
            }

            if (string.IsNullOrWhiteSpace(healthStatus))
            {
                var summary = ReadString(evt, "summary");
                if (string.IsNullOrWhiteSpace(summary))
                {
                    summary = ReadString(evt, "riskText");
                }
                healthStatus = ParseHealthStatusFromSummary(summary);
            }

            return healthStatus;
        }

        private string ResolveRiskLevelForEvent(JObject evt)
        {
            var riskLevel = ReadString(evt, "riskLevel");
            if (string.IsNullOrWhiteSpace(riskLevel))
            {
                riskLevel = lastRiskLevel;
            }

            return riskLevel;
        }

        private bool IsFallbackBlockingEvent(JObject evt)
        {
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<BeYourEyes.Unity.Interaction.LocalSafetyFallback>();
            }

            if (localSafetyFallback == null || localSafetyFallback.IsOk)
            {
                return false;
            }

            var type = ReadString(evt, "type");
            return !string.Equals(type, "health", StringComparison.OrdinalIgnoreCase);
        }

        private void StartHealthProbeLoop()
        {
            if (!enableHealthProbe || healthProbeRoutine != null || replayMode)
            {
                return;
            }

            healthProbeRoutine = StartCoroutine(HealthProbeLoop());
        }

        private void StopHealthProbeLoop()
        {
            if (healthProbeRoutine != null)
            {
                StopCoroutine(healthProbeRoutine);
                healthProbeRoutine = null;
            }
            healthProbeInFlight = false;
            readinessProbeInFlight = false;
        }

        private IEnumerator HealthProbeLoop()
        {
            while (true)
            {
                if (!healthProbeInFlight)
                {
                    yield return StartCoroutine(ProbeHealthOnce());
                }

                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (enableExternalReadinessProbe &&
                    !readinessProbeInFlight &&
                    (lastReadinessProbeAtMs <= 0 || nowMs - lastReadinessProbeAtMs >= Mathf.Max(0.5f, readinessProbeIntervalSec) * 1000f))
                {
                    yield return StartCoroutine(ProbeReadinessOnce());
                }

                UpdateCapabilityState("probe_tick");
                yield return new WaitForSecondsRealtime(Mathf.Max(0.5f, healthProbeIntervalSec));
            }
        }

        private IEnumerator ProbeHealthOnce()
        {
            healthProbeInFlight = true;
            var startedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            using (var req = UnityWebRequest.Get(BuildApiUrl("/api/health")))
            {
                req.downloadHandler = new DownloadHandlerBuffer();
                yield return req.SendWebRequest();
                var finishedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                lastHealthRttMs = (int)Mathf.Clamp((float)(finishedAtMs - startedAtMs), 0f, 60000f);

                if (req.result != UnityWebRequest.Result.Success)
                {
                    consecutiveHealthProbeFailures++;
                    healthProbeFailureCount++;
                    healthProbeInFlight = false;
                    yield break;
                }

                try
                {
                    var body = string.IsNullOrWhiteSpace(req.downloadHandler.text) ? "{}" : req.downloadHandler.text;
                    var json = JObject.Parse(body);
                    var status = ReadString(json, "healthStatus");
                    if (string.IsNullOrWhiteSpace(status))
                    {
                        status = ReadString(json, "state");
                    }
                    if (!string.IsNullOrWhiteSpace(status))
                    {
                        lastHealthStatus = status;
                    }

                    var reason = ReadString(json, "healthReason");
                    if (!string.IsNullOrWhiteSpace(reason))
                    {
                        lastHealthReason = reason;
                    }

                    var intent = ReadString(json, "intent");
                    if (!string.IsNullOrWhiteSpace(intent))
                    {
                        activeIntent = NormalizeIntent(intent);
                    }
                }
                catch
                {
                }

                lastHealthOkAtMs = finishedAtMs;
                consecutiveHealthProbeFailures = 0;
                healthProbeSuccessCount++;
            }

            healthProbeInFlight = false;
        }

        private IEnumerator ProbeReadinessOnce()
        {
            readinessProbeInFlight = true;
            lastReadinessProbeAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            using (var req = UnityWebRequest.Get(BuildApiUrl("/api/external_readiness")))
            {
                req.downloadHandler = new DownloadHandlerBuffer();
                yield return req.SendWebRequest();
                var finishedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    consecutiveReadinessProbeFailures++;
                    readinessProbeFailureCount++;
                    readinessProbeInFlight = false;
                    yield break;
                }

                var parseSuccess = false;
                try
                {
                    var body = string.IsNullOrWhiteSpace(req.downloadHandler.text) ? "{}" : req.downloadHandler.text;
                    var json = JObject.Parse(body);
                    parseSuccess = ParseReadinessPayload(json);
                }
                catch
                {
                    parseSuccess = false;
                }

                if (parseSuccess)
                {
                    lastReadinessOkAtMs = finishedAtMs;
                    consecutiveReadinessProbeFailures = 0;
                    readinessProbeSuccessCount++;
                }
                else
                {
                    consecutiveReadinessProbeFailures++;
                    readinessProbeFailureCount++;
                }
            }

            readinessProbeInFlight = false;
        }

        private bool ParseReadinessPayload(JObject json)
        {
            if (json == null)
            {
                return false;
            }

            var parsedAny = false;
            var readyCount = 0;
            var unavailableCount = 0;
            toolAvailability.Clear();

            var toolsToken = json["tools"];
            if (toolsToken is JArray arr)
            {
                foreach (var item in arr)
                {
                    if (!(item is JObject toolObj))
                    {
                        continue;
                    }

                    var name = ReadString(toolObj, "name");
                    if (string.IsNullOrWhiteSpace(name))
                    {
                        name = ReadString(toolObj, "tool");
                    }
                    if (string.IsNullOrWhiteSpace(name))
                    {
                        name = ReadString(toolObj, "id");
                    }
                    if (string.IsNullOrWhiteSpace(name))
                    {
                        continue;
                    }

                    var ready = ReadBool(toolObj, "ready", defaultValue: false);
                    toolAvailability[name.Trim().ToLowerInvariant()] = ready;
                    if (ready)
                    {
                        readyCount++;
                    }
                    else
                    {
                        unavailableCount++;
                    }
                    parsedAny = true;
                }
            }
            else if (toolsToken is JObject dictObj)
            {
                foreach (var prop in dictObj.Properties())
                {
                    var key = prop.Name?.Trim().ToLowerInvariant();
                    if (string.IsNullOrWhiteSpace(key))
                    {
                        continue;
                    }

                    var ready = false;
                    if (prop.Value is JObject nestedObj)
                    {
                        ready = ReadBool(nestedObj, "ready", defaultValue: false);
                    }
                    else if (prop.Value != null)
                    {
                        ready = ReadBoolToken(prop.Value, defaultValue: false);
                    }

                    toolAvailability[key] = ready;
                    if (ready)
                    {
                        readyCount++;
                    }
                    else
                    {
                        unavailableCount++;
                    }
                    parsedAny = true;
                }
            }

            if (!parsedAny)
            {
                var readyFromRoot = ReadInt(json, "readyToolsCount", -1);
                var unavailableFromRoot = ReadInt(json, "unavailableToolsCount", -1);
                if (readyFromRoot >= 0 || unavailableFromRoot >= 0)
                {
                    readyCount = Math.Max(0, readyFromRoot);
                    unavailableCount = Math.Max(0, unavailableFromRoot);
                    parsedAny = true;
                }
            }

            readinessKnown = parsedAny;
            readyToolsCount = parsedAny ? readyCount : -1;
            unavailableToolsCount = parsedAny ? unavailableCount : -1;
            return parsedAny;
        }

        private void UpdateCapabilityState(string reason)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var next = EvaluateCapabilityState(nowMs, out var nextReason);
            if (next == capabilityState && string.Equals(nextReason, capabilityTransitionReason, StringComparison.Ordinal))
            {
                return;
            }

            if (next != capabilityState)
            {
                capabilityStateTransitionCount++;
                capabilityState = next;
                capabilityTransitionReason = string.IsNullOrWhiteSpace(nextReason) ? reason : nextReason;
                OnCapabilityStateChanged?.Invoke(capabilityState, capabilityTransitionReason);
            }
            else
            {
                capabilityTransitionReason = string.IsNullOrWhiteSpace(nextReason) ? reason : nextReason;
            }
        }

        private CapabilityState EvaluateCapabilityState(long nowMs, out string reason)
        {
            reason = "ok";
            var failureThreshold = Math.Max(1, probeFailureThreshold);
            if (consecutiveHealthProbeFailures >= failureThreshold)
            {
                reason = "health_probe_failed";
                return CapabilityState.OFFLINE;
            }

            var staleMs = Math.Max(500, healthProbeStaleThresholdMs);
            var stale = lastMessageAtMs <= 0 || (nowMs - lastMessageAtMs) > staleMs || !IsConnected;
            if (stale)
            {
                reason = "ws_stale";
                return CapabilityState.REMOTE_STALE;
            }

            var normalizedHealth = (lastHealthStatus ?? string.Empty).Trim().ToUpperInvariant();
            if (normalizedHealth == "SAFE_MODE")
            {
                reason = "remote_safe_mode";
                return CapabilityState.REMOTE_SAFE_MODE;
            }
            if (normalizedHealth == "THROTTLED")
            {
                reason = "remote_throttled";
                return CapabilityState.REMOTE_THROTTLED;
            }
            if (normalizedHealth == "DEGRADED")
            {
                reason = "remote_degraded";
                return CapabilityState.REMOTE_DEGRADED;
            }

            if (enableExternalReadinessProbe)
            {
                if (consecutiveReadinessProbeFailures >= failureThreshold)
                {
                    reason = "readiness_probe_failed";
                    return CapabilityState.LIMITED_NOT_READY;
                }

                if (readinessKnown && readyToolsCount == 0 && unavailableToolsCount > 0)
                {
                    reason = "tools_unavailable";
                    return CapabilityState.LIMITED_NOT_READY;
                }
            }

            return CapabilityState.OK;
        }

        private void EnsureReconnectLoop()
        {
            if (!autoReconnect || shuttingDown || replayMode || reconnectLoopRunning || IsConnected)
            {
                return;
            }

            reconnectCts?.Cancel();
            reconnectCts?.Dispose();
            reconnectCts = new CancellationTokenSource();
            _ = ReconnectLoopAsync(reconnectCts.Token);
        }

        private void StopReconnectLoop()
        {
            reconnectCts?.Cancel();
            reconnectCts?.Dispose();
            reconnectCts = null;
            reconnectLoopRunning = false;
        }

        private async Task ReconnectLoopAsync(CancellationToken token)
        {
            reconnectLoopRunning = true;
            try
            {
                while (!token.IsCancellationRequested && !shuttingDown && !IsConnected)
                {
                    reconnectAttempt++;
                    var delay = ComputeReconnectDelaySec(reconnectAttempt);
                    OnWebSocketStateChanged?.Invoke(false, $"reconnect_attempt_{reconnectAttempt}");
                    await Task.Delay(TimeSpan.FromSeconds(delay), token);
                    if (token.IsCancellationRequested || shuttingDown || IsConnected)
                    {
                        break;
                    }

                    var connected = await ConnectWebSocketInternal();
                    if (connected && IsConnected)
                    {
                        break;
                    }
                }
            }
            catch (OperationCanceledException)
            {
            }
            finally
            {
                reconnectLoopRunning = false;
            }
        }

        private float ComputeReconnectDelaySec(int attempt)
        {
            var minDelay = Mathf.Max(0.1f, reconnectMinDelaySec);
            var maxDelay = Mathf.Max(minDelay, reconnectMaxDelaySec);
            var exponent = Mathf.Max(0, attempt - 1);
            var delay = minDelay * Mathf.Pow(2f, exponent);
            return Mathf.Clamp(delay, minDelay, maxDelay);
        }

        private void RegisterSentFrame(long seq, long sentMs)
        {
            if (seq <= 0)
            {
                return;
            }

            sentAtMs[seq] = sentMs;
            sentSeqOrder.Enqueue(seq);
            while (sentSeqOrder.Count > MaxSeqHistory)
            {
                var oldestSeq = sentSeqOrder.Dequeue();
                sentAtMs.Remove(oldestSeq);
                ttfaObservedSeq.Remove(oldestSeq);
            }
        }

        private void RemoveSentFrame(long seq)
        {
            if (seq <= 0)
            {
                return;
            }

            sentAtMs.Remove(seq);
            ttfaObservedSeq.Remove(seq);
        }

        private void PurgeOldSentFrames(long nowMs)
        {
            while (sentSeqOrder.Count > 0)
            {
                var seq = sentSeqOrder.Peek();
                if (!sentAtMs.TryGetValue(seq, out var sentMs))
                {
                    sentSeqOrder.Dequeue();
                    continue;
                }

                if (nowMs - sentMs <= SentRecordTtlMs)
                {
                    break;
                }

                sentSeqOrder.Dequeue();
                sentAtMs.Remove(seq);
                ttfaObservedSeq.Remove(seq);
            }
        }

        private void MaybeRecordTtfa(JObject evt, long nowMs)
        {
            if (!TryReadLong(evt, "seq", out var seq) || seq <= 0)
            {
                return;
            }

            if (!TryReadInt(evt, "stage", out var stage) || stage != 1)
            {
                return;
            }

            var type = ReadString(evt, "type").ToLowerInvariant();
            if (type != "risk" && type != "action_plan")
            {
                return;
            }

            if (ttfaObservedSeq.Contains(seq))
            {
                return;
            }

            if (!sentAtMs.TryGetValue(seq, out var sentMs))
            {
                return;
            }

            var ttfaMs = Math.Max(0, nowMs - sentMs);
            ttfaObservedSeq.Add(seq);
            lastTtfaMs = ttfaMs;
            if (ttfaEmaMs < 0)
            {
                ttfaEmaMs = ttfaMs;
            }
            else
            {
                ttfaEmaMs = (TtfaEmaAlpha * ttfaMs) + ((1d - TtfaEmaAlpha) * ttfaEmaMs);
            }

            ttfaSampleCount++;
            OnTtfaObserved?.Invoke(seq, type, ttfaMs);
        }

        private static string NormalizeBaseUrl(string value)
        {
            return string.IsNullOrWhiteSpace(value) ? "http://127.0.0.1:8000" : value.Trim();
        }

        private static string SanitizeReason(string value, string fallback)
        {
            var text = string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
            return text.Length > 200 ? text.Substring(0, 200) : text;
        }

        private static bool TryReadLong(JObject obj, string key, out long value)
        {
            value = -1;
            var token = obj[key];
            if (token == null)
            {
                return false;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                value = token.Value<long>();
                return true;
            }

            return long.TryParse(token.ToString(), out value);
        }

        private static bool TryReadInt(JObject obj, string key, out int value)
        {
            value = -1;
            var token = obj[key];
            if (token == null)
            {
                return false;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                value = token.Value<int>();
                return true;
            }

            return int.TryParse(token.ToString(), out value);
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
            if (text.StartsWith("gateway_waiting_client"))
            {
                return "WAITING_CLIENT";
            }
            if (text.StartsWith("gateway_normal"))
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

        private static string NormalizeConfirmChoice(string choice)
        {
            var normalized = string.IsNullOrWhiteSpace(choice) ? "unknown" : choice.Trim().ToLowerInvariant();
            if (normalized == "yes" || normalized == "no" || normalized == "unknown")
            {
                return normalized;
            }

            return "unknown";
        }

        private static string NormalizeIntent(string intent)
        {
            if (string.IsNullOrWhiteSpace(intent))
            {
                return "none";
            }

            var normalized = intent.Trim().ToLowerInvariant();
            switch (normalized)
            {
                case "normal":
                    return "none";
                case "scan_text":
                case "ask":
                case "qa":
                case "none":
                    return normalized;
                default:
                    return "none";
            }
        }

        private string ResolveDefaultAskQuestion()
        {
            var panel = FindFirstObjectByType<DevIntentPanel>();
            if (panel != null && !string.IsNullOrWhiteSpace(panel.CurrentQuestion))
            {
                return panel.CurrentQuestion.Trim();
            }

            return string.IsNullOrWhiteSpace(defaultAskQuestion) ? "What is in front of me?" : defaultAskQuestion.Trim();
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }

        private static bool ReadBool(JObject obj, string key, bool defaultValue)
        {
            var token = obj[key];
            return ReadBoolToken(token, defaultValue);
        }

        private static bool ReadBoolToken(JToken token, bool defaultValue)
        {
            if (token == null)
            {
                return defaultValue;
            }

            if (token.Type == JTokenType.Boolean)
            {
                return token.Value<bool>();
            }
            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<double>() > 0.5d;
            }

            return bool.TryParse(token.ToString(), out var parsed) ? parsed : defaultValue;
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

        private void ResetCapabilityRuntime()
        {
            readinessKnown = false;
            readyToolsCount = -1;
            unavailableToolsCount = -1;
            toolAvailability.Clear();

            consecutiveHealthProbeFailures = 0;
            consecutiveReadinessProbeFailures = 0;
            healthProbeSuccessCount = 0;
            healthProbeFailureCount = 0;
            readinessProbeSuccessCount = 0;
            readinessProbeFailureCount = 0;

            lastHealthOkAtMs = -1;
            lastReadinessOkAtMs = -1;
            lastReadinessProbeAtMs = -1;

            capabilityState = CapabilityState.OK;
            capabilityStateTransitionCount = 0;
            capabilityTransitionReason = "init";
        }
    }
}
