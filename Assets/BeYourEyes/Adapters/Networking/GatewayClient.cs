using System;
using System.Collections;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using NativeWebSocket;
using UnityEngine;
using UnityEngine.Networking;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class GatewayClient : MonoBehaviour
    {
        [Header("Gateway")]
        [SerializeField] private string baseUrl = "http://127.0.0.1:8000";
        [SerializeField] private string wsUrl = "ws://127.0.0.1:8000/ws/events";
        [SerializeField] private string sessionId = "default";
        [SerializeField] private bool connectOnEnable = true;

        [Header("Logging")]
        [SerializeField] private bool verboseLogs = true;
        [SerializeField] private int frameOkLogEvery = 30;

        private WebSocket webSocket;
        private bool wsConnecting;
        private bool frameRequestInFlight;
        private int frameOkCount;
        private int droppedFrameCount;

        public event Action<JObject> OnGatewayEvent;
        public event Action<bool, string> OnWebSocketStateChanged;

        public string BaseUrl => NormalizeBaseUrl(baseUrl);
        public string WsUrl => string.IsNullOrWhiteSpace(wsUrl) ? "ws://127.0.0.1:8000/ws/events" : wsUrl.Trim();
        public string SessionId => string.IsNullOrWhiteSpace(sessionId) ? "default" : sessionId.Trim();
        public bool IsFrameBusy => frameRequestInFlight;
        public bool IsConnected => webSocket != null && webSocket.State == WebSocketState.Open;

        private void OnEnable()
        {
            if (connectOnEnable)
            {
                ConnectWebSocket();
            }
        }

        private async void OnDisable()
        {
            await CloseWebSocketInternal();
        }

        private async void OnDestroy()
        {
            await CloseWebSocketInternal();
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
            if (wsConnecting)
            {
                return;
            }

            wsConnecting = true;
            try
            {
                await CloseWebSocketInternal();

                webSocket = new WebSocket(WsUrl);
                webSocket.OnOpen += HandleWsOpen;
                webSocket.OnClose += HandleWsClose;
                webSocket.OnError += HandleWsError;
                webSocket.OnMessage += HandleWsMessage;

                await webSocket.Connect();
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[GatewayClient] WS connect failed: {ex.Message}");
                OnWebSocketStateChanged?.Invoke(false, ex.Message);
            }
            finally
            {
                wsConnecting = false;
            }
        }

        public bool TrySendFrame(byte[] jpg, string metaJson)
        {
            if (jpg == null || jpg.Length == 0)
            {
                return false;
            }

            if (frameRequestInFlight)
            {
                droppedFrameCount++;
                if (droppedFrameCount % 20 == 1)
                {
                    Debug.Log($"[GatewayClient] frame dropped: busy (dropped={droppedFrameCount})");
                }

                return false;
            }

            StartCoroutine(SendFrameRoutine(jpg, metaJson));
            return true;
        }

        public void SendConfirm(string confirmId, string choice, string source = "unity_hud")
        {
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                Debug.LogWarning("[GatewayClient] confirm skipped: empty confirmId");
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
                success => Debug.Log(success
                    ? $"[GatewayClient] confirm posted: id={confirmId}"
                    : $"[GatewayClient] confirm failed: id={confirmId}")
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
                    var message = success ? "ok" : "error";
                    onDone?.Invoke(success, message);
                }
            ));
        }

        private IEnumerator SendFrameRoutine(byte[] jpg, string metaJson)
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

        private async Task CloseWebSocketInternal()
        {
            if (webSocket == null)
            {
                return;
            }

            try
            {
                webSocket.OnOpen -= HandleWsOpen;
                webSocket.OnClose -= HandleWsClose;
                webSocket.OnError -= HandleWsError;
                webSocket.OnMessage -= HandleWsMessage;
                if (webSocket.State == WebSocketState.Open || webSocket.State == WebSocketState.Connecting)
                {
                    await webSocket.Close();
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[GatewayClient] WS close error: {ex.Message}");
            }
            finally
            {
                webSocket = null;
                OnWebSocketStateChanged?.Invoke(false, "closed");
            }
        }

        private void HandleWsOpen()
        {
            Debug.Log("[GatewayClient] WS connected");
            OnWebSocketStateChanged?.Invoke(true, "connected");
        }

        private void HandleWsClose(WebSocketCloseCode code)
        {
            Debug.Log($"[GatewayClient] WS closed: {code}");
            OnWebSocketStateChanged?.Invoke(false, $"closed:{code}");
        }

        private void HandleWsError(string error)
        {
            Debug.LogWarning($"[GatewayClient] WS error: {error}");
            OnWebSocketStateChanged?.Invoke(false, error);
        }

        private void HandleWsMessage(byte[] bytes)
        {
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
            var riskLevel = ReadString(evt, "riskLevel");
            var confirmId = ReadString(evt, "confirmId");
            Debug.Log(
                $"[GatewayClient] WS event type={type} summary={summary} healthStatus={healthStatus} riskLevel={riskLevel} confirmId={confirmId}"
            );

            OnGatewayEvent?.Invoke(evt);
        }

        private string BuildApiUrl(string path)
        {
            return $"{BaseUrl.TrimEnd('/')}{path}";
        }

        private static string NormalizeBaseUrl(string value)
        {
            return string.IsNullOrWhiteSpace(value) ? "http://127.0.0.1:8000" : value.Trim();
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
