using System;
using System.Collections;
using System.Text;
using BeYourEyes.Adapters.Networking;
using UnityEngine;
using UnityEngine.Networking;

namespace BYES.Telemetry
{
    public sealed class ByesFrameTelemetry : MonoBehaviour
    {
        private const string DeviceIdPrefKey = "byes.telemetry.device_id";
        private static ByesFrameTelemetry _instance;

        private GatewayClient _gatewayClient;
        private string _deviceId = string.Empty;
        private string _lastRunId = string.Empty;
        private int _lastFrameSeq = 1;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            EnsureInstance();
        }

        public static string DeviceId => EnsureInstance()._deviceId;

        public static string DeviceTimeBase => "unix_ms";

        public static long NowUnixMs() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        public static void OnFrameSentToGateway(string runId, long frameSeq, long captureTsMs)
        {
            EnsureInstance().RecordFrameSent(runId, frameSeq, captureTsMs);
        }

        public static void AckFeedback(
            string runId,
            long frameSeq,
            string kind,
            bool accepted,
            long feedbackTsMs,
            string providerBackend = null,
            string providerModel = null,
            string providerDevice = null,
            string providerReason = null,
            bool? providerIsMock = null)
        {
            EnsureInstance().SendFeedbackAck(
                runId,
                frameSeq,
                kind,
                accepted,
                feedbackTsMs,
                providerBackend,
                providerModel,
                providerDevice,
                providerReason,
                providerIsMock);
        }

        public static bool TryGetLatestFrameContext(out string runId, out int frameSeq)
        {
            var instance = EnsureInstance();
            runId = string.IsNullOrWhiteSpace(instance._lastRunId) ? "unknown-run" : instance._lastRunId;
            frameSeq = Mathf.Max(1, instance._lastFrameSeq);
            return !string.IsNullOrWhiteSpace(instance._lastRunId);
        }

        private static ByesFrameTelemetry EnsureInstance()
        {
            if (_instance != null)
            {
                return _instance;
            }

            var existing = FindFirstObjectByType<ByesFrameTelemetry>();
            if (existing != null)
            {
                _instance = existing;
                if (_instance._deviceId == string.Empty)
                {
                    _instance.InitializeDeviceId();
                }
                DontDestroyOnLoad(_instance.gameObject);
                return _instance;
            }

            var go = new GameObject("BYES_FrameTelemetry");
            DontDestroyOnLoad(go);
            _instance = go.AddComponent<ByesFrameTelemetry>();
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
            InitializeDeviceId();
        }

        private void InitializeDeviceId()
        {
            if (!string.IsNullOrWhiteSpace(_deviceId))
            {
                return;
            }

            var fromSystem = (SystemInfo.deviceUniqueIdentifier ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(fromSystem) || string.Equals(fromSystem, "unsupportedidentifier", StringComparison.OrdinalIgnoreCase))
            {
                fromSystem = string.Empty;
            }

            if (!string.IsNullOrWhiteSpace(fromSystem))
            {
                _deviceId = fromSystem;
                return;
            }

            var cached = PlayerPrefs.GetString(DeviceIdPrefKey, string.Empty).Trim();
            if (!string.IsNullOrWhiteSpace(cached))
            {
                _deviceId = cached;
                return;
            }

            _deviceId = Guid.NewGuid().ToString("N");
            PlayerPrefs.SetString(DeviceIdPrefKey, _deviceId);
            PlayerPrefs.Save();
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

        private void RecordFrameSent(string runId, long frameSeq, long captureTsMs)
        {
            var normalizedRunId = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim();
            _lastRunId = normalizedRunId;
            _lastFrameSeq = Mathf.Max(1, (int)Math.Max(1, frameSeq));
        }

        private void SendFeedbackAck(
            string runId,
            long frameSeq,
            string kind,
            bool accepted,
            long feedbackTsMs,
            string providerBackend,
            string providerModel,
            string providerDevice,
            string providerReason,
            bool? providerIsMock)
        {
            var normalizedRunId = string.IsNullOrWhiteSpace(runId) ? _lastRunId : runId.Trim();
            if (string.IsNullOrWhiteSpace(normalizedRunId))
            {
                normalizedRunId = "unknown-run";
            }

            var normalizedFrameSeq = Mathf.Max(1, (int)Math.Max(1, frameSeq));
            _lastRunId = normalizedRunId;
            _lastFrameSeq = normalizedFrameSeq;

            var gatewayClient = ResolveGatewayClient();
            if (gatewayClient == null)
            {
                Debug.LogWarning("[ByesFrameTelemetry] ack skipped: GatewayClient not found");
                return;
            }

            var feedbackMs = Math.Max(0, feedbackTsMs);
            var payload = new FrameAckRequest
            {
                runId = normalizedRunId,
                frameSeq = normalizedFrameSeq,
                feedbackTsMs = feedbackMs,
                kind = NormalizeAckKind(kind),
                accepted = accepted,
                providerBackend = string.IsNullOrWhiteSpace(providerBackend) ? null : providerBackend.Trim(),
                providerModel = string.IsNullOrWhiteSpace(providerModel) ? null : providerModel.Trim(),
                providerDevice = string.IsNullOrWhiteSpace(providerDevice) ? null : providerDevice.Trim(),
                providerReason = string.IsNullOrWhiteSpace(providerReason) ? null : providerReason.Trim(),
                providerIsMock = providerIsMock,
            };

            var endpoint = $"{gatewayClient.BaseUrl.TrimEnd('/')}/api/frame/ack";
            var json = JsonUtility.ToJson(payload);
            StartCoroutine(PostAckRoutine(endpoint, json));
        }

        private static string NormalizeAckKind(string kind)
        {
            var raw = string.IsNullOrWhiteSpace(kind) ? "any" : kind.Trim().ToLowerInvariant();
            if (raw == "tts")
            {
                return "tts";
            }
            if (raw == "ar" || raw == "overlay")
            {
                return "ar";
            }
            if (raw == "haptic")
            {
                return "haptic";
            }
            return "any";
        }

        private static IEnumerator PostAckRoutine(string url, string json)
        {
            var body = Encoding.UTF8.GetBytes(string.IsNullOrWhiteSpace(json) ? "{}" : json);
            using (var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST)
            {
                uploadHandler = new UploadHandlerRaw(body),
                downloadHandler = new DownloadHandlerBuffer(),
            })
            {
                req.SetRequestHeader("Content-Type", "application/json");
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning($"[ByesFrameTelemetry] /api/frame/ack failed: {req.error}");
                }
            }
        }

        [Serializable]
        private sealed class FrameAckRequest
        {
            public string runId = "unknown-run";
            public int frameSeq = 1;
            public long feedbackTsMs;
            public string kind = "any";
            public bool accepted = true;
            public string providerBackend;
            public string providerModel;
            public string providerDevice;
            public string providerReason;
            public bool? providerIsMock;
        }
    }
}
