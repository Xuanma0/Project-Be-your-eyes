using System;
using BYES.Telemetry;
using BeYourEyes.Adapters.Networking;
using UnityEngine;

namespace BYES.Core
{
    public sealed class ByesModeManager : MonoBehaviour
    {
        private static ByesModeManager _instance;

        [SerializeField] private ByesMode currentMode = ByesMode.Walk;
        private GatewayClient _gatewayClient;

        public static ByesModeManager Instance => EnsureExists();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            _ = EnsureExists();
        }

        public static ByesModeManager EnsureExists()
        {
            if (_instance != null)
            {
                return _instance;
            }

            var existing = FindFirstObjectByType<ByesModeManager>();
            if (existing != null)
            {
                _instance = existing;
                DontDestroyOnLoad(_instance.gameObject);
                return _instance;
            }

            var root = new GameObject("BYES_ModeManager");
            DontDestroyOnLoad(root);
            _instance = root.AddComponent<ByesModeManager>();
            return _instance;
        }

        private void Awake()
        {
            if (_instance != null && _instance != this)
            {
                Destroy(gameObject);
                return;
            }

            _instance = this;
            DontDestroyOnLoad(gameObject);
            var state = ByesSystemState.EnsureExists();
            currentMode = state != null ? state.CurrentMode : ByesMode.Walk;
            state?.SetMode(currentMode);
        }

        public ByesMode GetMode()
        {
            return currentMode;
        }

        public static string ToApiMode(ByesMode mode)
        {
            switch (mode)
            {
                case ByesMode.ReadText:
                    return "read_text";
                case ByesMode.Inspect:
                    return "inspect";
                default:
                    return "walk";
            }
        }

        public void SetMode(ByesMode mode, string source)
        {
            var normalizedSource = string.IsNullOrWhiteSpace(source) ? "system" : source.Trim().ToLowerInvariant();
            if (normalizedSource != "hotkey" && normalizedSource != "xr" && normalizedSource != "system")
            {
                normalizedSource = "system";
            }

            if (currentMode == mode)
            {
                return;
            }

            currentMode = mode;
            var state = ByesSystemState.Instance;
            state?.SetMode(mode);
            PostModeChange(normalizedSource);
        }

        private GatewayClient ResolveGatewayClient()
        {
            if (_gatewayClient != null)
            {
                return _gatewayClient;
            }

            _gatewayClient = FindFirstObjectByType<GatewayClient>();
            return _gatewayClient;
        }

        private void PostModeChange(string source)
        {
            var runId = "unknown-run";
            var frameSeq = 1;
            var state = ByesSystemState.Instance;
            if (state != null)
            {
                runId = string.IsNullOrWhiteSpace(state.RunId) ? "unknown-run" : state.RunId.Trim();
                frameSeq = Mathf.Max(1, state.FrameSeq);
            }

            if (ByesFrameTelemetry.TryGetLatestFrameContext(out var telemetryRunId, out var telemetryFrameSeq))
            {
                if (!string.IsNullOrWhiteSpace(telemetryRunId))
                {
                    runId = telemetryRunId.Trim();
                }
                frameSeq = Mathf.Max(1, telemetryFrameSeq);
            }

            var gatewayClient = ResolveGatewayClient();
            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.PostModeChange(
                runId: runId,
                frameSeq: frameSeq,
                mode: ToApiMode(currentMode),
                source: source,
                tsMs: DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                deviceId: ByesFrameTelemetry.DeviceId
            );
        }
    }
}

