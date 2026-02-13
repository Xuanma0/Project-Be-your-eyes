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
                    PublishSystemHealth("gateway_unreachable", -1, "gateway");
                    yield break;
                }

                var rawJson = request.downloadHandler == null ? string.Empty : request.downloadHandler.text;
                if (string.IsNullOrWhiteSpace(rawJson))
                {
                    PublishSystemHealth("gateway_payload_empty", -1, "gateway");
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
                    PublishSystemHealth("gateway_payload_invalid", -1, "gateway");
                    yield break;
                }

                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var result = PublishFromDto(dto, nowMs, "gateway");
                if (result == GatewayPublishResult.UnknownType || result == GatewayPublishResult.InvalidPayload)
                {
                    PublishSystemHealth("gateway_event_unknown", -1, "gateway");
                }
            }
        }

        private string BuildRequestUrl()
        {
            var normalizedBase = string.IsNullOrWhiteSpace(baseUrl) ? "http://127.0.0.1:8000" : baseUrl.Trim();
            return $"{normalizedBase.TrimEnd('/')}/api/mock_event";
        }

        internal static GatewayPublishResult PublishFromDto(GatewayMockEventDto dto, long nowMs, string defaultSource)
        {
            if (dto == null)
            {
                return GatewayPublishResult.InvalidPayload;
            }

            var envelope = ToEnvelope(dto, defaultSource);
            if (envelope.IsExpired(nowMs))
            {
                return GatewayPublishResult.Expired;
            }

            var eventType = dto.type == null ? string.Empty : dto.type.Trim().ToLowerInvariant();
            if (eventType == "risk")
            {
                AppServices.Bus.Publish(new RiskEvent(envelope, dto.riskText, dto.distanceM, dto.azimuthDeg));
                return GatewayPublishResult.Published;
            }

            if (eventType == "perception")
            {
                AppServices.Bus.Publish(new PerceptionEvent(envelope, dto.summary));
                return GatewayPublishResult.Published;
            }

            return GatewayPublishResult.UnknownType;
        }

        internal static void PublishSystemHealth(string status, int rttMs, string source)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var envelope = new EventEnvelope(nowMs, CoordFrame.World, 1f, 1000, NormalizeSource(source));
            AppServices.Bus.Publish(new SystemHealthEvent(envelope, status, rttMs));
        }

        private static EventEnvelope ToEnvelope(GatewayMockEventDto dto, string defaultSource)
        {
            var source = string.IsNullOrWhiteSpace(dto.source) ? NormalizeSource(defaultSource) : dto.source;
            var frame = string.Equals(dto.coordFrame, "World", StringComparison.OrdinalIgnoreCase)
                ? CoordFrame.World
                : CoordFrame.World;
            return new EventEnvelope(dto.timestampMs, frame, dto.confidence, dto.ttlMs, source);
        }

        private static string NormalizeSource(string source)
        {
            return string.IsNullOrWhiteSpace(source) ? "gateway" : source;
        }
    }

    internal enum GatewayPublishResult
    {
        Published,
        Expired,
        UnknownType,
        InvalidPayload
    }
}
