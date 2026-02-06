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
        private const string PingMsg = "__ping__";
        private const string PongMsg = "__pong__";
        private const float PingIntervalSec = 2f;

        public string wsUrl = "ws://127.0.0.1:8000/ws/events";
        public float reconnectMinDelaySec = 1f;
        public float reconnectMaxDelaySec = 8f;
        public int ReconnectCount { get; private set; }
        public string ConnectionState { get; private set; } = "Disconnected";
        public int LastRttMs { get; private set; } = -1;
        public long LastRttUpdatedMs { get; private set; } = -1;

        private readonly ConcurrentQueue<string> pendingJson = new ConcurrentQueue<string>();
        private readonly ConcurrentQueue<(string status, int rttMs)> pendingHealthStatus = new ConcurrentQueue<(string status, int rttMs)>();
        private readonly ConcurrentQueue<string> pendingWarnings = new ConcurrentQueue<string>();

        private CancellationTokenSource cts;
        private Task connectTask;
        private bool hasAttemptedConnect;
        private long _lastPingSentMs = -1;

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

            while (pendingHealthStatus.TryDequeue(out var health))
            {
                GatewayPoller.PublishSystemHealth(health.status, health.rttMs, "gateway_ws");
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
            SetConnectionState("Connecting");
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
            SetConnectionState("Disconnected");
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
                SetConnectionState("Connecting");

                using (var socket = new ClientWebSocket())
                {
                    try
                    {
                        await socket.ConnectAsync(BuildUri(), token);
                        SetConnectionState("Connected");
                        Interlocked.Exchange(ref _lastPingSentMs, -1);
                        pendingHealthStatus.Enqueue(("gateway_connected", -1));
                        delaySec = minDelay;

                        using (var connectionCts = CancellationTokenSource.CreateLinkedTokenSource(token))
                        {
                            var connectionToken = connectionCts.Token;
                            var receiveTask = ReceiveLoopAsync(socket, connectionToken);
                            var pingTask = PingLoopAsync(socket, connectionToken);

                            await Task.WhenAny(receiveTask, pingTask);
                            connectionCts.Cancel();

                            try
                            {
                                await Task.WhenAll(receiveTask, pingTask);
                            }
                            catch (OperationCanceledException)
                            {
                                // no-op
                            }
                        }
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

                SetConnectionState("Disconnected");
                pendingHealthStatus.Enqueue(("gateway_disconnected", -1));

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

                    var payload = Encoding.UTF8.GetString(stream.ToArray());
                    if (string.Equals(payload, PongMsg, StringComparison.Ordinal))
                    {
                        var pingSentMs = Interlocked.Read(ref _lastPingSentMs);
                        if (pingSentMs > 0)
                        {
                            var nowMs = UtcNowMs();
                            var rttMsLong = nowMs - pingSentMs;
                            if (rttMsLong < 0)
                            {
                                rttMsLong = 0;
                            }

                            LastRttMs = (int)Math.Min(int.MaxValue, rttMsLong);
                            LastRttUpdatedMs = nowMs;
                            pendingHealthStatus.Enqueue(("gateway_rtt", LastRttMs));
                        }

                        continue;
                    }

                    if (!string.IsNullOrWhiteSpace(payload))
                    {
                        pendingJson.Enqueue(payload);
                    }
                }
            }
        }

        private async Task PingLoopAsync(ClientWebSocket socket, CancellationToken token)
        {
            var pingBytes = Encoding.UTF8.GetBytes(PingMsg);
            var segment = new ArraySegment<byte>(pingBytes);

            while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                await Task.Delay(TimeSpan.FromSeconds(PingIntervalSec), token);
                if (token.IsCancellationRequested || socket.State != WebSocketState.Open)
                {
                    return;
                }

                Interlocked.Exchange(ref _lastPingSentMs, UtcNowMs());
                await socket.SendAsync(segment, WebSocketMessageType.Text, true, token);
            }
        }

        private static long UtcNowMs()
        {
            return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private void SetConnectionState(string state)
        {
            ConnectionState = state;
            if (!string.Equals(state, "Connected", StringComparison.Ordinal))
            {
                LastRttMs = -1;
                LastRttUpdatedMs = -1;
                Interlocked.Exchange(ref _lastPingSentMs, -1);
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
        public int LastRttMs { get; private set; } = -1;
        public long LastRttUpdatedMs { get; private set; } = -1;

        private void OnEnable()
        {
            Debug.LogWarning("GatewayWsClient is only enabled for Windows Editor/Standalone in this version.");
        }
    }
}
#endif
