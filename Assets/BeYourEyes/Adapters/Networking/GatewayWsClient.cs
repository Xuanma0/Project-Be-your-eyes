#if UNITY_EDITOR_WIN || UNITY_STANDALONE_WIN
using System;
using System.Collections.Concurrent;
using System.IO;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class GatewayWsClient : MonoBehaviour
    {
        public string wsUrl = "ws://127.0.0.1:8000/ws/events";
        public float reconnectMinDelaySec = 1f;
        public float reconnectMaxDelaySec = 8f;
        public int ReconnectCount { get; private set; }
        public string ConnectionState { get; private set; } = "Disconnected";

        private readonly ConcurrentQueue<string> pendingJson = new ConcurrentQueue<string>();
        private readonly ConcurrentQueue<string> pendingHealthStatus = new ConcurrentQueue<string>();
        private readonly ConcurrentQueue<string> pendingWarnings = new ConcurrentQueue<string>();

        private CancellationTokenSource cts;
        private Task connectTask;
        private bool hasAttemptedConnect;

        private void OnEnable()
        {
            AppServices.Init();
            StartClient();
        }

        private void OnDisable()
        {
            StopClient();
        }

        private void OnDestroy()
        {
            StopClient();
        }

        private void Update()
        {
            while (pendingWarnings.TryDequeue(out var warning))
            {
                Debug.LogWarning(warning);
            }

            while (pendingHealthStatus.TryDequeue(out var status))
            {
                GatewayPoller.PublishSystemHealth(status, -1, "gateway_ws");
            }

            while (pendingJson.TryDequeue(out var json))
            {
                GatewayMockEventDto dto;
                try
                {
                    dto = JsonUtility.FromJson<GatewayMockEventDto>(json);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"Gateway WS payload parse failed: {ex.Message}");
                    GatewayPoller.PublishSystemHealth("gateway_payload_invalid", -1, "gateway_ws");
                    continue;
                }

                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var result = GatewayPoller.PublishFromDto(dto, nowMs, "gateway_ws");
                if (result == GatewayPublishResult.InvalidPayload)
                {
                    GatewayPoller.PublishSystemHealth("gateway_payload_invalid", -1, "gateway_ws");
                    continue;
                }

                if (result == GatewayPublishResult.UnknownType)
                {
                    GatewayPoller.PublishSystemHealth("gateway_event_unknown", -1, "gateway_ws");
                }
            }
        }

        private void StartClient()
        {
            StopClient();
            ReconnectCount = 0;
            hasAttemptedConnect = false;
            ConnectionState = "Connecting";
            cts = new CancellationTokenSource();
            connectTask = Task.Run(() => ConnectLoopAsync(cts.Token));
        }

        private void StopClient()
        {
            if (cts == null)
            {
                return;
            }

            try
            {
                cts.Cancel();
            }
            catch
            {
                // no-op
            }

            cts.Dispose();
            cts = null;
            connectTask = null;
            ConnectionState = "Disconnected";
        }

        private async Task ConnectLoopAsync(CancellationToken token)
        {
            var minDelay = Mathf.Max(0.1f, reconnectMinDelaySec);
            var maxDelay = Mathf.Max(minDelay, reconnectMaxDelaySec);
            var delaySec = minDelay;

            while (!token.IsCancellationRequested)
            {
                if (hasAttemptedConnect)
                {
                    ReconnectCount++;
                }

                hasAttemptedConnect = true;
                ConnectionState = "Connecting";

                using (var socket = new ClientWebSocket())
                {
                    try
                    {
                        await socket.ConnectAsync(BuildUri(), token);
                        ConnectionState = "Connected";
                        pendingHealthStatus.Enqueue("gateway_connected");
                        delaySec = minDelay;

                        await ReceiveLoopAsync(socket, token);
                    }
                    catch (OperationCanceledException)
                    {
                        break;
                    }
                    catch (Exception ex)
                    {
                        pendingWarnings.Enqueue($"Gateway WS error: {ex.Message}");
                    }
                }

                if (token.IsCancellationRequested)
                {
                    break;
                }

                ConnectionState = "Disconnected";
                pendingHealthStatus.Enqueue("gateway_disconnected");

                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(delaySec), token);
                }
                catch (OperationCanceledException)
                {
                    break;
                }

                delaySec = Mathf.Min(delaySec * 2f, maxDelay);
            }
        }

        private async Task ReceiveLoopAsync(ClientWebSocket socket, CancellationToken token)
        {
            var buffer = new byte[4096];
            var segment = new ArraySegment<byte>(buffer);

            while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                using (var stream = new MemoryStream())
                {
                    WebSocketReceiveResult result;
                    do
                    {
                        result = await socket.ReceiveAsync(segment, token);

                        if (result.MessageType == WebSocketMessageType.Close)
                        {
                            try
                            {
                                if (socket.State == WebSocketState.Open || socket.State == WebSocketState.CloseReceived)
                                {
                                    await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "closing", CancellationToken.None);
                                }
                            }
                            catch
                            {
                                // no-op
                            }

                            return;
                        }

                        if (result.Count > 0)
                        {
                            stream.Write(buffer, 0, result.Count);
                        }
                    } while (!result.EndOfMessage);

                    if (result.MessageType != WebSocketMessageType.Text)
                    {
                        continue;
                    }

                    var json = Encoding.UTF8.GetString(stream.ToArray());
                    if (!string.IsNullOrWhiteSpace(json))
                    {
                        pendingJson.Enqueue(json);
                    }
                }
            }
        }

        private Uri BuildUri()
        {
            var url = string.IsNullOrWhiteSpace(wsUrl) ? "ws://127.0.0.1:8000/ws/events" : wsUrl.Trim();
            return new Uri(url);
        }
    }
}
#else
using UnityEngine;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class GatewayWsClient : MonoBehaviour
    {
        public int ReconnectCount { get; private set; }
        public string ConnectionState { get; private set; } = "Disconnected";

        private void OnEnable()
        {
            Debug.LogWarning("GatewayWsClient is only enabled for Windows Editor/Standalone in this version.");
        }
    }
}
#endif
