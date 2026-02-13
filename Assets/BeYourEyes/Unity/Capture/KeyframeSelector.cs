using System;
using UnityEngine;

namespace BeYourEyes.Unity.Capture
{
    [Serializable]
    public sealed class KeyframeSelector
    {
        [Header("Intervals (ms)")]
        [SerializeField] private int normalMinIntervalMs = 200;
        [SerializeField] private int normalMaxIntervalMs = 1000;
        [SerializeField] private int throttledMinIntervalMs = 400;
        [SerializeField] private int throttledMaxIntervalMs = 1500;
        [SerializeField] private int degradedMinIntervalMs = 600;
        [SerializeField] private int degradedMaxIntervalMs = 2000;
        [SerializeField] private int safeModeMinIntervalMs = 1000;
        [SerializeField] private int safeModeMaxIntervalMs = 2500;

        [Header("Pose Threshold")]
        [SerializeField] private float angleThresholdDeg = 6f;
        [SerializeField] private float positionThresholdM = 0.10f;

        [Header("Backpressure")]
        [SerializeField] private int busyDropStreakThreshold = 5;

        private long lastSentAtMs = -1;
        private bool hasLastPose;
        private Vector3 lastSentPosition;
        private Quaternion lastSentRotation = Quaternion.identity;

        public int NormalMinIntervalMs => Math.Max(50, normalMinIntervalMs);
        public int NormalMaxIntervalMs => Math.Max(NormalMinIntervalMs, normalMaxIntervalMs);
        public int ThrottledMinIntervalMs => Math.Max(50, throttledMinIntervalMs);
        public int ThrottledMaxIntervalMs => Math.Max(ThrottledMinIntervalMs, throttledMaxIntervalMs);
        public int DegradedMinIntervalMs => Math.Max(50, degradedMinIntervalMs);
        public int DegradedMaxIntervalMs => Math.Max(DegradedMinIntervalMs, degradedMaxIntervalMs);
        public int SafeModeMinIntervalMs => Math.Max(50, safeModeMinIntervalMs);
        public int SafeModeMaxIntervalMs => Math.Max(SafeModeMinIntervalMs, safeModeMaxIntervalMs);
        public float AngleThresholdDeg => Mathf.Max(0f, angleThresholdDeg);
        public float PositionThresholdM => Mathf.Max(0f, positionThresholdM);
        public int BusyDropStreakThreshold => Mathf.Max(1, busyDropStreakThreshold);

        public KeyframeDecision Evaluate(long nowMs, Vector3 currentPosition, Quaternion currentRotation, string healthStatus, int busyDropStreak)
        {
            var policy = ResolvePolicy(healthStatus);
            var minIntervalMs = policy.minIntervalMs;
            if (busyDropStreak >= Mathf.Max(1, busyDropStreakThreshold))
            {
                minIntervalMs *= 2;
            }

            if (lastSentAtMs < 0 || !hasLastPose)
            {
                return new KeyframeDecision(true, "bootstrap");
            }

            var elapsedMs = Math.Max(0, nowMs - lastSentAtMs);
            if (elapsedMs >= policy.maxIntervalMs)
            {
                return new KeyframeDecision(true, "max_interval");
            }

            if (elapsedMs < minIntervalMs)
            {
                return new KeyframeDecision(false, "min_interval_guard");
            }

            var positionDelta = Vector3.Distance(lastSentPosition, currentPosition);
            if (positionDelta >= positionThresholdM)
            {
                return new KeyframeDecision(true, "pose_pos_delta");
            }

            var deltaEuler = NormalizeEuler((Quaternion.Inverse(lastSentRotation) * currentRotation).eulerAngles);
            if (Mathf.Abs(deltaEuler.x) >= angleThresholdDeg ||
                Mathf.Abs(deltaEuler.y) >= angleThresholdDeg ||
                Mathf.Abs(deltaEuler.z) >= angleThresholdDeg)
            {
                return new KeyframeDecision(true, "pose_rot_delta");
            }

            return new KeyframeDecision(false, "no_key_change");
        }

        public void NotifySendSucceeded(long nowMs, Vector3 sentPosition, Quaternion sentRotation)
        {
            lastSentAtMs = nowMs;
            lastSentPosition = sentPosition;
            lastSentRotation = sentRotation;
            hasLastPose = true;
        }

        public void ResetRuntime()
        {
            lastSentAtMs = -1;
            hasLastPose = false;
            lastSentPosition = Vector3.zero;
            lastSentRotation = Quaternion.identity;
        }

        private IntervalPolicy ResolvePolicy(string healthStatus)
        {
            var normalized = (healthStatus ?? string.Empty).Trim().ToUpperInvariant();
            switch (normalized)
            {
                case "SAFE_MODE":
                    return new IntervalPolicy(safeModeMinIntervalMs, safeModeMaxIntervalMs);
                case "DEGRADED":
                    return new IntervalPolicy(degradedMinIntervalMs, degradedMaxIntervalMs);
                case "THROTTLED":
                    return new IntervalPolicy(throttledMinIntervalMs, throttledMaxIntervalMs);
                default:
                    return new IntervalPolicy(normalMinIntervalMs, normalMaxIntervalMs);
            }
        }

        private static Vector3 NormalizeEuler(Vector3 euler)
        {
            return new Vector3(NormalizeAngle(euler.x), NormalizeAngle(euler.y), NormalizeAngle(euler.z));
        }

        private static float NormalizeAngle(float angle)
        {
            var a = angle;
            while (a > 180f)
            {
                a -= 360f;
            }
            while (a < -180f)
            {
                a += 360f;
            }
            return a;
        }

        private readonly struct IntervalPolicy
        {
            public IntervalPolicy(int minIntervalMs, int maxIntervalMs)
            {
                this.minIntervalMs = Math.Max(50, minIntervalMs);
                this.maxIntervalMs = Math.Max(this.minIntervalMs, maxIntervalMs);
            }

            public readonly int minIntervalMs;
            public readonly int maxIntervalMs;
        }
    }

    public readonly struct KeyframeDecision
    {
        public KeyframeDecision(bool shouldSend, string reason)
        {
            ShouldSend = shouldSend;
            Reason = reason ?? string.Empty;
        }

        public bool ShouldSend { get; }
        public string Reason { get; }
    }
}
