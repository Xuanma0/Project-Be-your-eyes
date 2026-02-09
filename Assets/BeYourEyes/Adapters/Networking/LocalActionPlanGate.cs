using System;
using Newtonsoft.Json.Linq;

namespace BeYourEyes.Adapters.Networking
{
    [Serializable]
    public sealed class LocalActionPlanGate
    {
        public const string ReasonAccepted = "accepted";
        public const string ReasonFallbackNonOk = "fallback_non_ok";
        public const string ReasonSafeMode = "safe_mode";
        public const string ReasonCriticalRisk = "critical_risk";
        public const string ReasonDegradedPatch = "degraded_patch";
        public const string ReasonThrottledPatch = "throttled_patch";

        public long AcceptedCount { get; private set; }
        public long BlockedCount { get; private set; }
        public long PatchedCount { get; private set; }
        public string LastReason { get; private set; } = ReasonAccepted;

        public void ResetRuntime()
        {
            AcceptedCount = 0;
            BlockedCount = 0;
            PatchedCount = 0;
            LastReason = ReasonAccepted;
        }

        public bool TryProcess(JObject evt, bool fallbackNonOk, string healthStatus, string riskLevel, out string reason)
        {
            reason = ReasonAccepted;
            if (evt == null)
            {
                BlockedCount++;
                LastReason = "invalid_event";
                reason = LastReason;
                return false;
            }

            if (fallbackNonOk)
            {
                BlockedCount++;
                LastReason = ReasonFallbackNonOk;
                reason = LastReason;
                return false;
            }

            var normalizedHealth = Normalize(healthStatus);
            if (normalizedHealth == "SAFE_MODE")
            {
                BlockedCount++;
                LastReason = ReasonSafeMode;
                reason = LastReason;
                return false;
            }

            var normalizedRisk = Normalize(riskLevel);
            if (normalizedRisk == "CRITICAL")
            {
                BlockedCount++;
                LastReason = ReasonCriticalRisk;
                reason = LastReason;
                return false;
            }

            if (normalizedHealth == "DEGRADED" || normalizedHealth == "THROTTLED")
            {
                PatchToConservativePlan(evt, normalizedHealth);
                AcceptedCount++;
                PatchedCount++;
                LastReason = normalizedHealth == "DEGRADED" ? ReasonDegradedPatch : ReasonThrottledPatch;
                reason = LastReason;
                return true;
            }

            AcceptedCount++;
            LastReason = ReasonAccepted;
            reason = LastReason;
            return true;
        }

        private static void PatchToConservativePlan(JObject evt, string normalizedHealth)
        {
            var patchReason = normalizedHealth == "DEGRADED" ? ReasonDegradedPatch : ReasonThrottledPatch;
            var conservativeText = "STOP and scan surroundings.";
            evt["summary"] = conservativeText;
            evt["instruction"] = conservativeText;
            evt["action"] = "stop_scan";
            evt["actions"] = new JArray("stop", "scan");
            evt["gatePatched"] = true;
            evt["gateReason"] = patchReason;
        }

        private static string Normalize(string value)
        {
            return string.IsNullOrWhiteSpace(value) ? string.Empty : value.Trim().ToUpperInvariant();
        }
    }
}
