using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;
using BeYourEyes.Unity.Capture;
using BeYourEyes.Unity.Interaction;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class RunPackageManager : MonoBehaviour
    {
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private RunRecorder runRecorder;
        [SerializeField] private FrameCapture frameCapture;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;

        [Header("Run Window")]
        [SerializeField] private float forceWindowDurationSec = 12f;
        [SerializeField] private int forceWindowMaxFrames = 50;
        [SerializeField] private int forceWindowMinIntervalMs = 120;

        [Header("Metrics Snapshot")]
        [SerializeField] private bool saveMetricsSnapshot = true;
        [SerializeField] private int metricsTimeoutSec = 3;

        private bool runActive;
        private bool runFinishing;
        private bool recorderStartedByManager;
        private float nextLookupAt;

        private string currentScenarioTag = string.Empty;
        private string currentRunDirectory = string.Empty;
        private string currentManifestPath = string.Empty;
        private string currentRunSummary = string.Empty;
        private JObject currentScenarioPayload;
        private readonly List<string> runErrors = new List<string>();
        private readonly Dictionary<string, int> healthStatusCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

        private long startMs;
        private long endMs;
        private long eventCountAccepted;
        private int localSafetyEnterCount;
        private long startFramesCaptured;
        private long startFramesSent;
        private long startFramesDroppedBusy;
        private long startFramesDroppedNoConn;
        private string metricsBeforePath = string.Empty;
        private string metricsAfterPath = string.Empty;

        public bool IsRunActive => runActive || runFinishing;
        public string CurrentScenarioTag => currentScenarioTag ?? string.Empty;
        public string CurrentRunDirectory => currentRunDirectory ?? string.Empty;
        public string CurrentManifestPath => currentManifestPath ?? string.Empty;
        public string CurrentRunSummary => currentRunSummary ?? string.Empty;
        public long CurrentEventCountAccepted => eventCountAccepted;

        public event Action<string, string> OnRunCompleted;

        private void OnEnable()
        {
            EnsureDependencies();
        }

        private void Update()
        {
            if (Time.unscaledTime < nextLookupAt)
            {
                return;
            }

            nextLookupAt = Time.unscaledTime + 1f;
            EnsureDependencies();
        }

        private void OnDisable()
        {
            if (runActive || runFinishing)
            {
                StartCoroutine(FinalizeRunCoroutine("disabled"));
            }
        }

        public bool StartRun(string scenarioTag, JObject scenarioPayload, out string message)
        {
            EnsureDependencies();
            if (runActive || runFinishing)
            {
                message = "run_already_active";
                return false;
            }

            if (gatewayClient == null || frameCapture == null || runRecorder == null)
            {
                message = "missing_dependency";
                return false;
            }

            runActive = true;
            runFinishing = false;
            recorderStartedByManager = false;

            currentScenarioTag = SanitizeTag(scenarioTag);
            currentScenarioPayload = scenarioPayload != null ? (scenarioPayload.DeepClone() as JObject) : null;
            currentRunSummary = string.Empty;
            runErrors.Clear();
            healthStatusCounts.Clear();
            eventCountAccepted = 0;
            localSafetyEnterCount = 0;
            startMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            endMs = -1;
            metricsBeforePath = string.Empty;
            metricsAfterPath = string.Empty;
            startFramesCaptured = frameCapture.FramesCaptured;
            startFramesSent = frameCapture.FramesSent;
            startFramesDroppedBusy = frameCapture.FramesDroppedBusy;
            startFramesDroppedNoConn = frameCapture.FramesDroppedNoConn;

            currentRunDirectory = BuildRunDirectory(currentScenarioTag);
            currentManifestPath = Path.Combine(currentRunDirectory, "manifest.json");

            BindRuntimeEvents();
            StartCoroutine(RunLifecycleCoroutine());
            message = currentRunDirectory;
            return true;
        }

        public void StopRun()
        {
            if (!runActive || runFinishing)
            {
                return;
            }

            StartCoroutine(FinalizeRunCoroutine("manual_stop"));
        }

        public bool StartRun(string scenarioTag, out string message)
        {
            return StartRun(scenarioTag, null, out message);
        }

        private IEnumerator RunLifecycleCoroutine()
        {
            Directory.CreateDirectory(currentRunDirectory);

            if (saveMetricsSnapshot)
            {
                yield return CaptureMetricsSnapshot("metrics_before.txt", path => metricsBeforePath = path);
            }

            runRecorder.SetScenarioTag(currentScenarioTag);
            if (!runRecorder.IsRecording)
            {
                if (runRecorder.StartRecording(out var recorderMessage))
                {
                    recorderStartedByManager = true;
                }
                else
                {
                    runErrors.Add($"recorder_start_failed:{recorderMessage}");
                }
            }

            if (!frameCapture.ForceCaptureWindow(forceWindowDurationSec, forceWindowMaxFrames, forceWindowMinIntervalMs, out var forceReason))
            {
                runErrors.Add($"force_window_start_failed:{forceReason}");
            }

            var hardDeadlineMs = startMs + (long)(Mathf.Max(0.1f, forceWindowDurationSec) * 1000f) + 3000;
            while (runActive && !runFinishing)
            {
                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (!frameCapture.IsForceWindowActive)
                {
                    break;
                }
                if (nowMs >= hardDeadlineMs)
                {
                    runErrors.Add("force_window_deadline_reached");
                    break;
                }

                yield return null;
            }

            if (runActive && !runFinishing)
            {
                yield return FinalizeRunCoroutine("auto_complete");
            }
        }

        private IEnumerator FinalizeRunCoroutine(string reason)
        {
            if (runFinishing)
            {
                yield break;
            }

            runFinishing = true;

            if (frameCapture != null && frameCapture.IsForceWindowActive)
            {
                frameCapture.CancelForceCaptureWindow($"run_finalize:{reason}");
            }

            if (recorderStartedByManager && runRecorder != null && runRecorder.IsRecording)
            {
                runRecorder.StopRecording();
            }
            recorderStartedByManager = false;

            if (saveMetricsSnapshot)
            {
                yield return CaptureMetricsSnapshot("metrics_after.txt", path => metricsAfterPath = path);
            }

            endMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            WriteManifest(reason);
            UnbindRuntimeEvents();

            runActive = false;
            runFinishing = false;

            currentRunSummary = $"scenario={currentScenarioTag} sent={Math.Max(0, frameCapture.FramesSent - startFramesSent)} events={eventCountAccepted} localSafetyEnters={localSafetyEnterCount} manifest={currentManifestPath}";
            OnRunCompleted?.Invoke(currentManifestPath, currentRunSummary);
        }

        private void WriteManifest(string finishReason)
        {
            var frameSentDelta = Math.Max(0, frameCapture != null ? frameCapture.FramesSent - startFramesSent : 0);
            var frameCapturedDelta = Math.Max(0, frameCapture != null ? frameCapture.FramesCaptured - startFramesCaptured : 0);
            var dropBusyDelta = Math.Max(0, frameCapture != null ? frameCapture.FramesDroppedBusy - startFramesDroppedBusy : 0);
            var dropNoConnDelta = Math.Max(0, frameCapture != null ? frameCapture.FramesDroppedNoConn - startFramesDroppedNoConn : 0);

            var manifest = new JObject
            {
                ["scenarioTag"] = currentScenarioTag,
                ["startMs"] = startMs,
                ["endMs"] = endMs > 0 ? endMs : DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["durationMs"] = (endMs > 0 && startMs > 0) ? Math.Max(0, endMs - startMs) : -1,
                ["finishReason"] = finishReason,
                ["baseUrl"] = gatewayClient != null ? gatewayClient.BaseUrl : string.Empty,
                ["wsUrl"] = gatewayClient != null ? gatewayClient.WsUrl : string.Empty,
                ["sessionId"] = gatewayClient != null ? gatewayClient.SessionId : string.Empty,
                ["frameCountSent"] = frameSentDelta,
                ["frameCountCaptured"] = frameCapturedDelta,
                ["frameDroppedBusy"] = dropBusyDelta,
                ["frameDroppedNoConn"] = dropNoConnDelta,
                ["eventCountAccepted"] = eventCountAccepted,
                ["localSafetyFallbackEnterCount"] = localSafetyEnterCount,
                ["healthStatusCounts"] = JObject.FromObject(healthStatusCounts),
                ["parameters"] = BuildParameterSnapshot(),
                ["runRecorder"] = new JObject
                {
                    ["runDirectory"] = runRecorder != null ? runRecorder.CurrentRunDirectory : string.Empty,
                    ["manifestPath"] = runRecorder != null ? runRecorder.LastManifestPath : string.Empty,
                    ["scenarioTag"] = runRecorder != null ? runRecorder.ScenarioTag : string.Empty,
                },
                ["metrics"] = new JObject
                {
                    ["beforePath"] = metricsBeforePath,
                    ["afterPath"] = metricsAfterPath,
                },
                ["scenarioPayload"] = currentScenarioPayload ?? new JObject(),
                ["errors"] = new JArray(runErrors),
            };

            try
            {
                File.WriteAllText(currentManifestPath, manifest.ToString(Formatting.Indented), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                runErrors.Add($"manifest_write_failed:{ex.Message}");
            }
        }

        private JObject BuildParameterSnapshot()
        {
            var frameParams = frameCapture != null ? frameCapture.BuildParameterSnapshot() : new JObject();
            return new JObject
            {
                ["frameCapture"] = frameParams,
                ["eventGuard"] = new JObject
                {
                    ["allowedReorderSeq"] = gatewayClient != null ? gatewayClient.EventAllowedReorderSeq : 0,
                    ["defaultEventTtlMs"] = gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 0,
                },
                ["forceWindow"] = new JObject
                {
                    ["durationSec"] = forceWindowDurationSec,
                    ["maxFrames"] = forceWindowMaxFrames,
                    ["minIntervalMs"] = forceWindowMinIntervalMs,
                },
            };
        }

        private IEnumerator CaptureMetricsSnapshot(string fileName, Action<string> onPathReady)
        {
            if (gatewayClient == null)
            {
                runErrors.Add($"metrics_{fileName}_skipped:no_gateway_client");
                onPathReady?.Invoke(string.Empty);
                yield break;
            }

            var outputPath = Path.Combine(currentRunDirectory, fileName);
            var url = $"{gatewayClient.BaseUrl.TrimEnd('/')}/metrics";
            using (var req = UnityWebRequest.Get(url))
            {
                req.timeout = Mathf.Clamp(metricsTimeoutSec, 1, 30);
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    runErrors.Add($"metrics_fetch_failed:{fileName}:{req.error}");
                    onPathReady?.Invoke(string.Empty);
                    yield break;
                }

                try
                {
                    File.WriteAllText(outputPath, req.downloadHandler.text ?? string.Empty, new UTF8Encoding(false));
                    onPathReady?.Invoke(outputPath);
                }
                catch (Exception ex)
                {
                    runErrors.Add($"metrics_write_failed:{fileName}:{ex.Message}");
                    onPathReady?.Invoke(string.Empty);
                }
            }
        }

        private void EnsureDependencies()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }
            if (runRecorder == null)
            {
                runRecorder = FindFirstObjectByType<RunRecorder>();
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

        private void BindRuntimeEvents()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnUiEventAccepted -= HandleUiEventAccepted;
                gatewayClient.OnUiEventAccepted += HandleUiEventAccepted;
            }
            if (localSafetyFallback != null)
            {
                localSafetyFallback.OnStateChanged -= HandleLocalSafetyStateChanged;
                localSafetyFallback.OnStateChanged += HandleLocalSafetyStateChanged;
            }
        }

        private void UnbindRuntimeEvents()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnUiEventAccepted -= HandleUiEventAccepted;
            }
            if (localSafetyFallback != null)
            {
                localSafetyFallback.OnStateChanged -= HandleLocalSafetyStateChanged;
            }
        }

        private void HandleUiEventAccepted(JObject evt)
        {
            if (!runActive || evt == null)
            {
                return;
            }

            eventCountAccepted++;
            var type = ReadString(evt, "type");
            if (!string.Equals(type, "health", StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            var status = ReadString(evt, "healthStatus");
            if (string.IsNullOrWhiteSpace(status))
            {
                status = ParseHealthStatusFromSummary(ReadString(evt, "summary"));
            }
            if (string.IsNullOrWhiteSpace(status))
            {
                status = "UNKNOWN";
            }

            if (!healthStatusCounts.TryGetValue(status, out var count))
            {
                count = 0;
            }

            healthStatusCounts[status] = count + 1;
        }

        private void HandleLocalSafetyStateChanged(LocalSafetyState previous, LocalSafetyState next, string reason, long atMs)
        {
            if (!runActive)
            {
                return;
            }

            if (previous == LocalSafetyState.OK && next != LocalSafetyState.OK)
            {
                localSafetyEnterCount++;
            }
        }

        private static string BuildRunDirectory(string scenarioTag)
        {
            var tag = string.IsNullOrWhiteSpace(scenarioTag) ? "scenario" : scenarioTag.Trim();
            tag = tag.Replace(" ", "_").Replace("/", "_").Replace("\\", "_");
            foreach (var invalid in Path.GetInvalidFileNameChars())
            {
                tag = tag.Replace(invalid, '_');
            }
            var root = Path.Combine(Application.persistentDataPath, "BeYourEyesRunPackages");
            Directory.CreateDirectory(root);
            return Path.Combine(root, $"{DateTime.Now:yyyyMMdd_HHmmss}_{tag}");
        }

        private static string SanitizeTag(string tag)
        {
            if (string.IsNullOrWhiteSpace(tag))
            {
                return "scenario";
            }

            return tag.Trim();
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj?[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }

        private static string ParseHealthStatusFromSummary(string summary)
        {
            if (string.IsNullOrWhiteSpace(summary))
            {
                return string.Empty;
            }

            var text = summary.Trim().ToLowerInvariant();
            if (text.StartsWith("gateway_safe_mode"))
            {
                return "SAFE_MODE";
            }
            if (text.StartsWith("gateway_throttled"))
            {
                return "THROTTLED";
            }
            if (text.StartsWith("gateway_degraded"))
            {
                return "DEGRADED";
            }
            if (text.StartsWith("gateway_waiting_client"))
            {
                return "WAITING_CLIENT";
            }
            if (text.StartsWith("gateway_normal"))
            {
                return "NORMAL";
            }

            return string.Empty;
        }
    }
}
