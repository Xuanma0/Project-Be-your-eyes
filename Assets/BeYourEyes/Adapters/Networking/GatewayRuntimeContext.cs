using System;
using UnityEngine;

namespace BeYourEyes.Adapters.Networking
{
    public static class GatewayRuntimeContext
    {
        private const string DeviceIdPrefKey = "byes.telemetry.device_id";
        private static string _deviceId;

        public static Func<string> DeviceIdProvider { get; set; }

        public static Func<string> ApiModeProvider { get; set; }

        public static Action<string, long, long> FrameSentToTelemetrySink { get; set; }

        public static string DeviceId => ResolveDeviceId();

        public static string DeviceTimeBase => "unix_ms";

        public static long NowUnixMs()
        {
            return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        public static void NotifyFrameSentToTelemetry(string runId, long frameSeq, long captureTsMs)
        {
            try
            {
                FrameSentToTelemetrySink?.Invoke(
                    string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim(),
                    Math.Max(1L, frameSeq),
                    Math.Max(0L, captureTsMs));
            }
            catch
            {
                // Keep networking layer resilient if upper-layer callbacks throw.
            }
        }

        public static string ResolveApiMode(string fallback = "walk")
        {
            var defaultMode = string.IsNullOrWhiteSpace(fallback) ? "walk" : fallback.Trim().ToLowerInvariant();
            try
            {
                var resolved = ApiModeProvider?.Invoke();
                return string.IsNullOrWhiteSpace(resolved) ? defaultMode : resolved.Trim().ToLowerInvariant();
            }
            catch
            {
                return defaultMode;
            }
        }

        private static string ResolveDeviceId()
        {
            if (!string.IsNullOrWhiteSpace(_deviceId))
            {
                return _deviceId;
            }

            var fromProvider = TryGetDeviceIdFromProvider();
            if (!string.IsNullOrWhiteSpace(fromProvider))
            {
                _deviceId = fromProvider;
                return _deviceId;
            }

            var fromSystem = (SystemInfo.deviceUniqueIdentifier ?? string.Empty).Trim();
            if (string.Equals(fromSystem, "unsupportedidentifier", StringComparison.OrdinalIgnoreCase))
            {
                fromSystem = string.Empty;
            }

            if (!string.IsNullOrWhiteSpace(fromSystem))
            {
                _deviceId = fromSystem;
                return _deviceId;
            }

            var cached = PlayerPrefs.GetString(DeviceIdPrefKey, string.Empty).Trim();
            if (!string.IsNullOrWhiteSpace(cached))
            {
                _deviceId = cached;
                return _deviceId;
            }

            _deviceId = Guid.NewGuid().ToString("N");
            PlayerPrefs.SetString(DeviceIdPrefKey, _deviceId);
            PlayerPrefs.Save();
            return _deviceId;
        }

        private static string TryGetDeviceIdFromProvider()
        {
            try
            {
                var value = DeviceIdProvider?.Invoke();
                return string.IsNullOrWhiteSpace(value) ? string.Empty : value.Trim();
            }
            catch
            {
                return string.Empty;
            }
        }
    }
}
