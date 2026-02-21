using System;
using System.Collections.Generic;
using BeYourEyes.Core.Events;
using BeYourEyes.Unity.Capture;
using UnityEngine;

namespace BeYourEyes.Adapters.Inference
{
    public interface IOnDeviceInferenceProvider
    {
        bool IsReady { get; }

        bool TryInfer(FrameCapture.FrameAcceptedInfo frame, out OnDeviceInferenceOutput output);
    }

    [Serializable]
    public sealed class OnDeviceInferenceOutput
    {
        public string riskText = string.Empty;
        public float riskConfidence = 1f;
        public float? riskDistanceM;
        public float? riskAzimuthDeg;

        public string perceptionSummary = string.Empty;
        public List<DetectedObject> perceptionObjects = new List<DetectedObject>();
        public float perceptionConfidence = 1f;

        public int ttlMs = 1200;
        public CoordFrame coordFrame = CoordFrame.World;

        public bool HasRisk()
        {
            return !string.IsNullOrWhiteSpace(riskText);
        }

        public bool HasPerception()
        {
            return !string.IsNullOrWhiteSpace(perceptionSummary)
                   || (perceptionObjects != null && perceptionObjects.Count > 0);
        }
    }

    public sealed class OnDeviceInferenceAdapter : MonoBehaviour
    {
        [SerializeField] private FrameCapture frameCapture;
        [SerializeField] private Networking.GatewayClient gatewayClient;
        [SerializeField] private MonoBehaviour inferenceProvider;

        [Header("Policy")]
        [SerializeField] private bool autoDiscoverDependencies = true;
        [SerializeField] private bool publishWhenGatewayDegradedOnly = false;
        [SerializeField] private bool publishRiskEvent = true;
        [SerializeField] private bool publishPerceptionEvent = true;
        [SerializeField] private int fallbackTtlMs = 1200;
        [SerializeField] private int minRiskIntervalMs = 300;
        [SerializeField] private int minPerceptionIntervalMs = 250;
        [SerializeField] private string sourceTag = "on_device_infer";

        private IOnDeviceInferenceProvider resolvedProvider;
        private long lastRiskPublishedAtMs = -1;
        private long lastPerceptionPublishedAtMs = -1;
        private float nextLookupAt;
        private bool warnedProviderInvalid;

        public bool IsProviderReady => resolvedProvider != null && resolvedProvider.IsReady;

        public event Action<OnDeviceInferenceOutput, long, long> OnOutputPublished;

        private void OnEnable()
        {
            AppServices.Init();
            EnsureDependencies();
            ResolveProvider();
            BindFrameCapture();
        }

        private void OnDisable()
        {
            UnbindFrameCapture();
        }

        private void Update()
        {
            if (!autoDiscoverDependencies)
            {
                return;
            }

            if (Time.unscaledTime < nextLookupAt)
            {
                return;
            }

            nextLookupAt = Time.unscaledTime + 1f;
            EnsureDependencies();
            ResolveProvider();
            BindFrameCapture();
        }

        public void SetProvider(IOnDeviceInferenceProvider provider)
        {
            resolvedProvider = provider;
            warnedProviderInvalid = false;
        }

        public void PublishOutput(OnDeviceInferenceOutput output, long timestampMs, long frameSeq)
        {
            PublishToEventBus(output, timestampMs, frameSeq);
        }

        private void EnsureDependencies()
        {
            if (frameCapture == null)
            {
                frameCapture = FindFirstObjectByType<FrameCapture>();
            }

            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<Networking.GatewayClient>();
            }
        }

        private void ResolveProvider()
        {
            if (resolvedProvider != null)
            {
                return;
            }

            if (inferenceProvider == null)
            {
                return;
            }

            resolvedProvider = inferenceProvider as IOnDeviceInferenceProvider;
            if (resolvedProvider == null && !warnedProviderInvalid)
            {
                warnedProviderInvalid = true;
                Debug.LogWarning("[OnDeviceInferenceAdapter] inferenceProvider does not implement IOnDeviceInferenceProvider");
            }
        }

        private void BindFrameCapture()
        {
            if (frameCapture == null)
            {
                return;
            }

            frameCapture.OnFrameAccepted -= HandleFrameAccepted;
            frameCapture.OnFrameAccepted += HandleFrameAccepted;
        }

        private void UnbindFrameCapture()
        {
            if (frameCapture == null)
            {
                return;
            }

            frameCapture.OnFrameAccepted -= HandleFrameAccepted;
        }

        private void HandleFrameAccepted(FrameCapture.FrameAcceptedInfo info)
        {
            if (publishWhenGatewayDegradedOnly && !IsGatewayDegraded())
            {
                return;
            }

            if (resolvedProvider == null || !resolvedProvider.IsReady)
            {
                return;
            }

            if (!resolvedProvider.TryInfer(info, out var output) || output == null)
            {
                return;
            }

            PublishToEventBus(output, info.TimestampMs, info.Seq);
        }

        private void PublishToEventBus(OnDeviceInferenceOutput output, long timestampMs, long frameSeq)
        {
            if (output == null)
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var safeTimestampMs = timestampMs > 0 ? timestampMs : nowMs;
            var safeTtlMs = output.ttlMs > 0 ? output.ttlMs : Mathf.Max(200, fallbackTtlMs);
            var safeSource = string.IsNullOrWhiteSpace(sourceTag) ? "on_device_infer" : sourceTag.Trim();
            var coordFrame = output.coordFrame;

            if (publishRiskEvent && output.HasRisk())
            {
                var elapsed = lastRiskPublishedAtMs > 0 ? nowMs - lastRiskPublishedAtMs : long.MaxValue;
                if (elapsed >= Mathf.Max(0, minRiskIntervalMs))
                {
                    var envelope = new EventEnvelope(
                        safeTimestampMs,
                        coordFrame,
                        Mathf.Clamp01(output.riskConfidence),
                        safeTtlMs,
                        safeSource
                    );
                    AppServices.Bus.Publish(new RiskEvent(
                        envelope,
                        output.riskText,
                        output.riskDistanceM,
                        output.riskAzimuthDeg
                    ));
                    lastRiskPublishedAtMs = nowMs;
                }
            }

            if (publishPerceptionEvent && output.HasPerception())
            {
                var elapsed = lastPerceptionPublishedAtMs > 0 ? nowMs - lastPerceptionPublishedAtMs : long.MaxValue;
                if (elapsed >= Mathf.Max(0, minPerceptionIntervalMs))
                {
                    var envelope = new EventEnvelope(
                        safeTimestampMs,
                        coordFrame,
                        Mathf.Clamp01(output.perceptionConfidence),
                        safeTtlMs,
                        safeSource
                    );
                    var objects = output.perceptionObjects != null
                        ? new List<DetectedObject>(output.perceptionObjects)
                        : null;
                    AppServices.Bus.Publish(new PerceptionEvent(
                        envelope,
                        output.perceptionSummary,
                        objects
                    ));
                    lastPerceptionPublishedAtMs = nowMs;
                }
            }

            OnOutputPublished?.Invoke(output, safeTimestampMs, frameSeq);
        }

        private bool IsGatewayDegraded()
        {
            if (gatewayClient == null)
            {
                return true;
            }

            return gatewayClient.CurrentCapabilityState != Networking.CapabilityState.OK;
        }
    }
}