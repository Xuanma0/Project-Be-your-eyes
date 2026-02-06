using System;
using System.Collections;
using BeYourEyes.Core.Events;
using UnityEngine;
using UnityEngine.Networking;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class GatewayPoller : MonoBehaviour
    {
        public string baseUrl = "http://127.0.0.1:8000";
        public float pollIntervalSec = 1.0f;

        private readonly WaitForSeconds defaultTick = new WaitForSeconds(1.0f);
        private bool running;

        private void OnEnable()
        {
            AppServices.Init();
            running = true;
            StartCoroutine(PollLoop());
        }

        private void OnDisable()
        {
            running = false;
        }

        private IEnumerator PollLoop()
        {
            while (running)
            {
                yield return FetchOnce();
                yield return pollIntervalSec > 0f ? new WaitForSeconds(pollIntervalSec) : defaultTick;
            }
        }

        private IEnumerator FetchOnce()
        {
            var requestUrl = BuildRequestUrl();
            using (var request = UnityWebRequest.Get(requestUrl))
            {
                yield return request.SendWebRequest();

                if (request.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning($"Gateway poll failed: {request.error}");
                    PublishGatewayHealth("gateway_unreachable", -1);
                    yield break;
                }

                var rawJson = request.downloadHandler == null ? string.Empty : request.downloadHandler.text;
                if (string.IsNullOrWhiteSpace(rawJson))
                {
                    PublishGatewayHealth("gateway_payload_empty", -1);
                    yield break;
                }

                GatewayMockEventDto dto;
                try
                {
                    dto = JsonUtility.FromJson<GatewayMockEventDto>(rawJson);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"Gateway payload parse failed: {ex.Message}");
                    PublishGatewayHealth("gateway_payload_invalid", -1);
                    yield break;
                }

                if (dto == null)
                {
                    PublishGatewayHealth("gateway_payload_invalid", -1);
                    yield break;
                }

                var envelope = ToEnvelope(dto);
                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (envelope.IsExpired(nowMs))
                {
                    yield break;
                }

                var eventType = dto.type == null ? string.Empty : dto.type.Trim().ToLowerInvariant();
                if (eventType == "risk")
                {
                    AppServices.Bus.Publish(new RiskEvent(envelope, dto.riskText, dto.distanceM, dto.azimuthDeg));
                    yield break;
                }

                if (eventType == "perception")
                {
                    AppServices.Bus.Publish(new PerceptionEvent(envelope, dto.summary));
                    yield break;
                }

                PublishGatewayHealth("gateway_event_unknown", -1);
                yield break;
            }
        }

        private string BuildRequestUrl()
        {
            var normalizedBase = string.IsNullOrWhiteSpace(baseUrl) ? "http://127.0.0.1:8000" : baseUrl.Trim();
            return $"{normalizedBase.TrimEnd('/')}/api/mock_event";
        }

        private static EventEnvelope ToEnvelope(GatewayMockEventDto dto)
        {
            var source = string.IsNullOrWhiteSpace(dto.source) ? "gateway" : dto.source;
            var frame = string.Equals(dto.coordFrame, "World", StringComparison.OrdinalIgnoreCase)
                ? CoordFrame.World
                : CoordFrame.World;

            return new EventEnvelope(dto.timestampMs, frame, dto.confidence, dto.ttlMs, source);
        }

        private static void PublishGatewayHealth(string status, int rttMs)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var envelope = new EventEnvelope(nowMs, CoordFrame.World, 1f, 1000, "gateway");
            AppServices.Bus.Publish(new SystemHealthEvent(envelope, status, rttMs));
        }
    }
}
