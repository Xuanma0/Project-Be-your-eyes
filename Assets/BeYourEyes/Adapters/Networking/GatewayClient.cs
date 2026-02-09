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

        private string lastHealthStatus = "UNKNOWN";
        private string lastHealthReason = string.Empty;
        private int lastHealthRttMs = -1;
        private string activeIntent = "none";
        private Coroutine healthProbeRoutine;
        private bool healthProbeInFlight;

        public event Action<JObject> OnGatewayEvent;
        public event Action<bool, string> OnWebSocketStateChanged;

        public string BaseUrl => NormalizeBaseUrl(baseUrl);
        public string WsUrl => string.IsNullOrWhiteSpace(wsUrl) ? "ws://127.0.0.1:8000/ws/events" : wsUrl.Trim();
        public string SessionId => string.IsNullOrWhiteSpace(sessionId) ? "default" : sessionId.Trim();
        public bool IsFrameBusy => frameRequestInFlight;
        public bool IsConnected => webSocket != null && webSocket.State == WebSocketState.Open;
        public string LastDisconnectReason => lastDisconnectReason;
        public int ReconnectAttempt => reconnectAttempt;
        public long LastMessageAtMs => lastMessageAtMs;
        public long LastTtfaMs => lastTtfaMs;
        public double TtfaEmaMs => ttfaEmaMs;
        public int TtfaSampleCount => ttfaSampleCount;
        public string LastHealthStatus => lastHealthStatus;
        public string LastHealthReason => lastHealthReason;
        public int LastHealthRttMs => lastHealthRttMs;
        public string ActiveIntent => activeIntent;

        private void OnEnable()
        {
            shuttingDown = false;
            if (connectOnEnable)
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
            if (shuttingDown || wsConnecting)
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
            var normalized = NormalizeIntent(intent);
            var payload = new JObject
            {
                ["intent"] = normalized,
            };

            if ((normalized == "ask" || normalized == "qa") && !string.IsNullOrWhiteSpace(question))
            {
                payload["question"] = question.Trim();
            }

            StartCoroutine(PostJsonRoutine(
                BuildApiUrl("/api/dev/intent"),
                payload.ToString(Formatting.None),
                success =>
                {
                    if (success)
                    {
                        activeIntent = normalized;
                    }
                    var message = success ? "ok" : "error";
                    onDone?.Invoke(success, message);
                }
            ));
        }

        public void FetchPendingConfirm(Action<bool, JObject> onDone)
        {
            var url = BuildApiUrl($"/api/confirm/pending?sessionId={UnityWebRequest.EscapeURL(SessionId)}");
            StartCoroutine(GetJsonRoutine(url, onDone));
        }

        private IEnumerator SendFrameRoutine(byte[] jpg, string metaJson, long seq)
        {
            frameRequestInFlight = true;
            try
            {
                var form = new WWWForm();
                form.AddBinaryData("image", jpg, "frame.jpg", "image/jpeg");
                if (!string.IsNullOrWhiteSpace(metaJson))
                {
                    form.AddField("meta", metaJson);
                }

                using (var req = UnityWebRequest.Post(BuildApiUrl("/api/frame"), form))
                {
                    yield return req.SendWebRequest();
                    if (req.result == UnityWebRequest.Result.Success)
                    {
                        frameOkCount++;
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
            var confirmId = ReadString(evt, "confirmId");
            var stage = ReadString(evt, "stage");
            Debug.Log(
                $"[GatewayClient] WS event type={type} summary={summary} healthStatus={healthStatus} riskLevel={riskLevel} stage={stage} confirmId={confirmId}"
            );

            MaybeRecordTtfa(evt, nowMs);
            OnGatewayEvent?.Invoke(evt);
        }

        private string BuildApiUrl(string path)
        {
            return $"{BaseUrl.TrimEnd('/')}{path}";
        }

        private void StartHealthProbeLoop()
        {
            if (!enableHealthProbe || healthProbeRoutine != null)
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
        }

        private IEnumerator HealthProbeLoop()
        {
            while (true)
            {
                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var staleMs = Math.Max(500, healthProbeStaleThresholdMs);
                var stale = lastMessageAtMs <= 0 || (nowMs - lastMessageAtMs) > staleMs;
                if ((!IsConnected || stale) && !healthProbeInFlight)
                {
                    yield return StartCoroutine(ProbeHealthOnce());
                }

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
            }

            healthProbeInFlight = false;
        }

        private void EnsureReconnectLoop()
        {
            if (!autoReconnect || shuttingDown || reconnectLoopRunning || IsConnected)
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

        private static string ReadString(JObject obj, string key)
        {
            var token = obj[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }
    }
}
