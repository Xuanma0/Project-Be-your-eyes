using System;
using System.IO;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEngine;
using BeYourEyes.Unity.Capture;
using BeYourEyes.Unity.Interaction;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class RunRecorder : MonoBehaviour
    {
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private FrameCapture frameCapture;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;
        [SerializeField] private bool recordFrames;
        [SerializeField] private float telemetrySnapshotIntervalSec = 1.0f;
        [SerializeField] private int maxMetaPreviewChars = 240;
        [SerializeField] private string scenarioTag = string.Empty;

        private readonly object writeLock = new object();
        private StreamWriter uiEventsWriter;
        private StreamWriter telemetryWriter;
        private Coroutine snapshotRoutine;
        private float nextLookupAt;
        private string runsRootPath;
        private string framesDirectory;
        private string manifestPath;

        public bool IsRecording { get; private set; }
        public string CurrentRunId { get; private set; } = string.Empty;
        public string CurrentRunDirectory { get; private set; } = string.Empty;
        public bool RecordFrames => recordFrames;
        public string ScenarioTag => scenarioTag ?? string.Empty;

        private void OnEnable()
        {
            EnsureDependencies();
            BindEvents();
        }

        private void Update()
        {
            if (Time.unscaledTime < nextLookupAt)
            {
                return;
            }

            nextLookupAt = Time.unscaledTime + 1f;
            EnsureDependencies();
            BindEvents();
        }

        private void OnDisable()
        {
            UnbindEvents();
            StopRecording();
        }

        public void SetRecordFrames(bool enabled)
        {
            recordFrames = enabled;
        }

        public void SetScenarioTag(string tag)
        {
            scenarioTag = string.IsNullOrWhiteSpace(tag) ? string.Empty : tag.Trim();
            if (IsRecording)
            {
                WriteManifest();
            }
        }

        public bool StartRecording(out string message)
        {
            if (IsRecording)
            {
                message = "already_recording";
                return false;
            }

            try
            {
                runsRootPath = Path.Combine(Application.persistentDataPath, "BeYourEyesRuns");
                Directory.CreateDirectory(runsRootPath);

                CurrentRunId = DateTime.Now.ToString("yyyyMMdd_HHmmss");
                CurrentRunDirectory = Path.Combine(runsRootPath, CurrentRunId);
                Directory.CreateDirectory(CurrentRunDirectory);
                manifestPath = Path.Combine(CurrentRunDirectory, "run_manifest.json");

                framesDirectory = Path.Combine(CurrentRunDirectory, "frames");
                if (recordFrames)
                {
                    Directory.CreateDirectory(framesDirectory);
                }

                uiEventsWriter = CreateWriter(Path.Combine(CurrentRunDirectory, "ui_events.jsonl"));
                telemetryWriter = CreateWriter(Path.Combine(CurrentRunDirectory, "telemetry.jsonl"));

                WriteManifest();
                IsRecording = true;
                snapshotRoutine = StartCoroutine(TelemetrySnapshotLoop());
                WriteTelemetry(new JObject
                {
                    ["kind"] = "run_start",
                    ["recordedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    ["runId"] = CurrentRunId,
                    ["recordFrames"] = recordFrames,
                });

                message = CurrentRunDirectory;
                return true;
            }
            catch (Exception ex)
            {
                StopRecording();
                message = ex.Message;
                return false;
            }
        }

        public void StopRecording()
        {
            if (!IsRecording && uiEventsWriter == null && telemetryWriter == null)
            {
                return;
            }

            if (IsRecording)
            {
                WriteTelemetry(new JObject
                {
                    ["kind"] = "run_stop",
                    ["recordedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    ["runId"] = CurrentRunId,
                });
            }

            IsRecording = false;
            if (snapshotRoutine != null)
            {
                StopCoroutine(snapshotRoutine);
                snapshotRoutine = null;
            }

            manifestPath = string.Empty;

            lock (writeLock)
            {
                uiEventsWriter?.Flush();
                uiEventsWriter?.Dispose();
                uiEventsWriter = null;

                telemetryWriter?.Flush();
                telemetryWriter?.Dispose();
                telemetryWriter = null;
            }
        }

        public static string GetLatestRunDirectory()
        {
            var root = Path.Combine(Application.persistentDataPath, "BeYourEyesRuns");
            if (!Directory.Exists(root))
            {
                return string.Empty;
            }

            var dirs = Directory.GetDirectories(root);
            if (dirs == null || dirs.Length == 0)
            {
                return string.Empty;
            }

            Array.Sort(dirs, StringComparer.Ordinal);
            return dirs[dirs.Length - 1];
        }

        private static StreamWriter CreateWriter(string path)
        {
            var writer = new StreamWriter(path, false, new UTF8Encoding(false));
            writer.AutoFlush = true;
            return writer;
        }

        private void EnsureDependencies()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }
            if (frameCapture == null)
            {
                frameCapture = FindFirstObjectByType<FrameCapture>();
            }
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
            }
        }

        private void BindEvents()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnUiEventAccepted -= HandleUiEventAccepted;
                gatewayClient.OnUiEventAccepted += HandleUiEventAccepted;
                gatewayClient.OnCapabilityStateChanged -= HandleCapabilityStateChanged;
                gatewayClient.OnCapabilityStateChanged += HandleCapabilityStateChanged;
                gatewayClient.OnTtfaObserved -= HandleTtfaObserved;
                gatewayClient.OnTtfaObserved += HandleTtfaObserved;
            }

            if (frameCapture != null)
            {
                frameCapture.OnFrameAccepted -= HandleFrameAccepted;
                frameCapture.OnFrameAccepted += HandleFrameAccepted;
            }

            if (localSafetyFallback != null)
            {
                localSafetyFallback.OnStateChanged -= HandleLocalSafetyStateChanged;
                localSafetyFallback.OnStateChanged += HandleLocalSafetyStateChanged;
            }
        }

        private void UnbindEvents()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnUiEventAccepted -= HandleUiEventAccepted;
                gatewayClient.OnCapabilityStateChanged -= HandleCapabilityStateChanged;
                gatewayClient.OnTtfaObserved -= HandleTtfaObserved;
            }

            if (frameCapture != null)
            {
                frameCapture.OnFrameAccepted -= HandleFrameAccepted;
            }

            if (localSafetyFallback != null)
            {
                localSafetyFallback.OnStateChanged -= HandleLocalSafetyStateChanged;
            }
        }

        private void HandleUiEventAccepted(JObject evt)
        {
            if (!IsRecording || evt == null)
            {
                return;
            }

            var recordedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var evtClone = evt.DeepClone() as JObject ?? new JObject();
            var row = new JObject
            {
                ["recordedAtMs"] = recordedAtMs,
                ["type"] = ReadString(evtClone, "type"),
                ["seq"] = ReadLong(evtClone, "seq"),
                ["stage"] = ReadInt(evtClone, "stage", -1),
                ["healthStatus"] = ReadString(evtClone, "healthStatus"),
                ["healthReason"] = ReadString(evtClone, "healthReason"),
                ["riskLevel"] = ReadString(evtClone, "riskLevel"),
                ["summary"] = ResolveSummary(evtClone),
                ["azimuthDeg"] = ReadFloat(evtClone, "azimuthDeg", float.NaN),
                ["distanceM"] = ReadFloat(evtClone, "distanceM", float.NaN),
                ["confirmId"] = ReadString(evtClone, "confirmId"),
                ["confirmKind"] = ReadString(evtClone, "confirmKind"),
                ["confirmPrompt"] = ReadString(evtClone, "confirmPrompt"),
                ["confirmOptions"] = evtClone["confirmOptions"] is JArray options ? options.DeepClone() : new JArray(),
                ["receivedAtMs"] = ReadLong(evtClone, "_receivedAtMs", recordedAtMs),
                ["ttlMs"] = ReadInt(evtClone, "_eventTtlMs", 1500),
                ["sessionId"] = ReadString(evtClone, "sessionId"),
                ["event"] = evtClone,
            };

            WriteUiEvent(row);
        }

        private void HandleCapabilityStateChanged(CapabilityState state, string reason)
        {
            if (!IsRecording)
            {
                return;
            }

            WriteTelemetry(new JObject
            {
                ["kind"] = "capability_transition",
                ["recordedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["state"] = state.ToString(),
                ["reason"] = string.IsNullOrWhiteSpace(reason) ? "-" : reason,
            });
        }

        private void HandleLocalSafetyStateChanged(LocalSafetyState previous, LocalSafetyState next, string reason, long atMs)
        {
            if (!IsRecording)
            {
                return;
            }

            WriteTelemetry(new JObject
            {
                ["kind"] = "local_safety_transition",
                ["recordedAtMs"] = atMs,
                ["from"] = previous.ToString(),
                ["to"] = next.ToString(),
                ["reason"] = string.IsNullOrWhiteSpace(reason) ? "-" : reason,
            });
        }

        private void HandleTtfaObserved(long seq, string kind, long ttfaMs)
        {
            if (!IsRecording)
            {
                return;
            }

            WriteTelemetry(new JObject
            {
                ["kind"] = "ttfa",
                ["recordedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["seq"] = seq,
                ["ttfaKind"] = string.IsNullOrWhiteSpace(kind) ? "-" : kind,
                ["ttfaMs"] = ttfaMs,
            });
        }

        private void HandleFrameAccepted(FrameCapture.FrameAcceptedInfo info)
        {
            if (!IsRecording)
            {
                return;
            }

            if (recordFrames && info.JpgBytes != null && info.JpgBytes.Length > 0)
            {
                try
                {
                    Directory.CreateDirectory(framesDirectory);
                    var framePath = Path.Combine(framesDirectory, $"{info.Seq}.jpg");
                    File.WriteAllBytes(framePath, info.JpgBytes);
                }
                catch (Exception ex)
                {
                    WriteTelemetry(new JObject
                    {
                        ["kind"] = "frame_dump_error",
                        ["recordedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                        ["seq"] = info.Seq,
                        ["error"] = ex.Message,
                    });
                }
            }

            WriteTelemetry(new JObject
            {
                ["kind"] = "frame_sent",
                ["recordedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["seq"] = info.Seq,
                ["timestampMs"] = info.TimestampMs,
                ["bytes"] = info.JpgBytes != null ? info.JpgBytes.Length : 0,
                ["width"] = info.Width,
                ["height"] = info.Height,
                ["roiApplied"] = info.RoiApplied,
                ["keyframeReason"] = string.IsNullOrWhiteSpace(info.KeyframeReason) ? "-" : info.KeyframeReason,
                ["meta"] = Truncate(info.MetaJson, maxMetaPreviewChars),
            });
        }

        private System.Collections.IEnumerator TelemetrySnapshotLoop()
        {
            while (IsRecording)
            {
                WriteSnapshot();
                yield return new WaitForSecondsRealtime(Mathf.Max(0.2f, telemetrySnapshotIntervalSec));
            }
        }

        private void WriteSnapshot()
        {
            if (!IsRecording)
            {
                return;
            }

            var row = new JObject
            {
                ["kind"] = "frame_snapshot",
                ["recordedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };

            if (frameCapture != null)
            {
                row["captured"] = frameCapture.FramesCaptured;
                row["sent"] = frameCapture.FramesSent;
                row["dropBusy"] = frameCapture.FramesDroppedBusy;
                row["dropNoConn"] = frameCapture.FramesDroppedNoConn;
                row["bytesEma"] = frameCapture.BytesEma >= 0 ? frameCapture.BytesEma : -1;
                row["keyframeReason"] = frameCapture.LastKeyframeReason ?? "-";
            }

            if (gatewayClient != null)
            {
                row["isConnected"] = gatewayClient.IsConnected;
                row["capabilityState"] = gatewayClient.CurrentCapabilityState.ToString();
                row["healthStatus"] = gatewayClient.LastHealthStatus ?? string.Empty;
                row["healthReason"] = gatewayClient.LastHealthReason ?? string.Empty;
            }

            WriteTelemetry(row);
        }

        private void WriteManifest()
        {
            var manifest = new JObject
            {
                ["runId"] = CurrentRunId,
                ["createdAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["persistentDataPath"] = Application.persistentDataPath,
                ["platform"] = Application.platform.ToString(),
                ["unityVersion"] = Application.unityVersion,
                ["appVersion"] = Application.version,
                ["deviceModel"] = SystemInfo.deviceModel,
                ["deviceName"] = SystemInfo.deviceName,
                ["baseUrl"] = gatewayClient != null ? gatewayClient.BaseUrl : string.Empty,
                ["wsUrl"] = gatewayClient != null ? gatewayClient.WsUrl : string.Empty,
                ["sessionId"] = gatewayClient != null ? gatewayClient.SessionId : string.Empty,
                ["recordFrames"] = recordFrames,
                ["isOnlineAtStart"] = gatewayClient != null && gatewayClient.IsConnected,
                ["scenarioTag"] = string.IsNullOrWhiteSpace(scenarioTag) ? string.Empty : scenarioTag,
            };

            try
            {
                if (string.IsNullOrWhiteSpace(manifestPath))
                {
                    manifestPath = Path.Combine(CurrentRunDirectory, "run_manifest.json");
                }
                File.WriteAllText(manifestPath, manifest.ToString(), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[RunRecorder] manifest write failed: {ex.Message}");
            }
        }

        private void WriteUiEvent(JObject row)
        {
            if (row == null || uiEventsWriter == null)
            {
                return;
            }

            try
            {
                lock (writeLock)
                {
                    uiEventsWriter.WriteLine(row.ToString(Newtonsoft.Json.Formatting.None));
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[RunRecorder] ui_events write failed: {ex.Message}");
            }
        }

        private void WriteTelemetry(JObject row)
        {
            if (row == null || telemetryWriter == null)
            {
                return;
            }

            try
            {
                lock (writeLock)
                {
                    telemetryWriter.WriteLine(row.ToString(Newtonsoft.Json.Formatting.None));
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[RunRecorder] telemetry write failed: {ex.Message}");
            }
        }

        private static string ResolveSummary(JObject evt)
        {
            var summary = ReadString(evt, "summary");
            if (!string.IsNullOrWhiteSpace(summary))
            {
                return summary;
            }

            summary = ReadString(evt, "riskText");
            if (!string.IsNullOrWhiteSpace(summary))
            {
                return summary;
            }

            summary = ReadString(evt, "instruction");
            return string.IsNullOrWhiteSpace(summary) ? string.Empty : summary;
        }

        private static string Truncate(string value, int maxChars)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return string.Empty;
            }

            var limit = Math.Max(16, maxChars);
            var trimmed = value.Trim();
            if (trimmed.Length <= limit)
            {
                return trimmed;
            }

            return trimmed.Substring(0, limit) + "...";
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj?[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }

        private static long ReadLong(JObject obj, string key, long defaultValue = -1)
        {
            var token = obj?[key];
            if (token == null)
            {
                return defaultValue;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<long>();
            }

            return long.TryParse(token.ToString(), out var parsed) ? parsed : defaultValue;
        }

        private static int ReadInt(JObject obj, string key, int defaultValue = -1)
        {
            var token = obj?[key];
            if (token == null)
            {
                return defaultValue;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<int>();
            }

            return int.TryParse(token.ToString(), out var parsed) ? parsed : defaultValue;
        }

        private static float ReadFloat(JObject obj, string key, float defaultValue)
        {
            var token = obj?[key];
            if (token == null)
            {
                return defaultValue;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<float>();
            }

            return float.TryParse(token.ToString(), out var parsed) ? parsed : defaultValue;
        }
    }
}
