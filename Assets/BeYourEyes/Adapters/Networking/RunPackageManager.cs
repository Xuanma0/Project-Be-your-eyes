using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
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

        [Header("Upload")]
        [SerializeField] private bool autoUploadAfterExport = false;
        [SerializeField] private int uploadTimeoutSec = 10;
        [SerializeField] private bool recordFramesForReplay = false;

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
        private readonly object wsWriteLock = new object();
        private readonly object frameWriteLock = new object();
        private StreamWriter wsEventsWriter;
        private StreamWriter framesMetaWriter;
        private StreamWriter framesIndexWriter;
        private EventV1Recorder eventV1Recorder;
        private string lastFinishReason = "not_started";
        private string lastExportZipPath = string.Empty;
        private string lastExportSha256 = string.Empty;
        private long lastExportedAtMs = -1;
        private readonly List<string> lastExportErrors = new List<string>();
        private readonly List<ExportFileStat> lastExportFiles = new List<ExportFileStat>();
        private string lastUploadStatus = "idle";
        private string lastUploadError = string.Empty;
        private string lastUploadReportPath = string.Empty;
        private string lastUploadSummary = string.Empty;
        private string lastUploadRunId = string.Empty;
        private string lastUploadRunUrl = string.Empty;
        private string lastUploadReportUrl = string.Empty;
        private string lastUploadSummaryUrl = string.Empty;
        private string lastUploadZipUrl = string.Empty;
        private long lastUploadAtMs = -1;
        private bool uploadInFlight;

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
        private string framesDirectoryPath = string.Empty;
        private string framesMetaPath = string.Empty;
        private string framesIndexPath = string.Empty;
        private int framesCount;
        private readonly List<JObject> pendingScenarioApiCalls = new List<JObject>();
        private readonly List<JObject> scenarioApiCalls = new List<JObject>();

        private const string WsJsonlFileName = "ws_events.jsonl";
        private const string MetricsBeforeFileName = "metrics_before.txt";
        private const string MetricsAfterFileName = "metrics_after.txt";
        private const string FramesDirName = "frames";
        private const string FramesMetaFileName = "frames_meta.jsonl";
        private const string FramesIndexFileName = "frames_index.jsonl";
        private const string EventsDirName = "events";
        private const string EventsV1FileName = "events_v1.jsonl";
        private const string EventsV1RelativePath = EventsDirName + "/" + EventsV1FileName;

        public bool IsRunActive => runActive || runFinishing;
        public string CurrentScenarioTag => currentScenarioTag ?? string.Empty;
        public string CurrentRunDirectory => currentRunDirectory ?? string.Empty;
        public string CurrentManifestPath => currentManifestPath ?? string.Empty;
        public string CurrentRunSummary => currentRunSummary ?? string.Empty;
        public long CurrentEventCountAccepted => eventCountAccepted;
        public string LastExportZipPath => lastExportZipPath ?? string.Empty;
        public string LastExportError => lastExportErrors.Count == 0 ? string.Empty : lastExportErrors[lastExportErrors.Count - 1];
        public long LastExportedAtMs => lastExportedAtMs;
        public bool AutoUploadAfterExport
        {
            get => autoUploadAfterExport;
            set => autoUploadAfterExport = value;
        }
        public bool IsUploadInFlight => uploadInFlight;
        public string LastUploadStatus => lastUploadStatus ?? "idle";
        public string LastUploadError => lastUploadError ?? string.Empty;
        public string LastUploadReportPath => lastUploadReportPath ?? string.Empty;
        public string LastUploadSummary => lastUploadSummary ?? string.Empty;
        public string LastUploadRunId => lastUploadRunId ?? string.Empty;
        public string LastUploadRunUrl => lastUploadRunUrl ?? string.Empty;
        public string LastUploadReportUrl => lastUploadReportUrl ?? string.Empty;
        public string LastUploadSummaryUrl => lastUploadSummaryUrl ?? string.Empty;
        public string LastUploadZipUrl => lastUploadZipUrl ?? string.Empty;
        public long LastUploadAtMs => lastUploadAtMs;
        public bool RecordFramesForReplay
        {
            get => recordFramesForReplay;
            set => recordFramesForReplay = value;
        }
        public int CurrentFramesCount => framesCount;

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
            lastFinishReason = "running";
            lastExportZipPath = string.Empty;
            lastExportSha256 = string.Empty;
            lastExportedAtMs = -1;
            lastExportErrors.Clear();
            lastExportFiles.Clear();
            lastUploadStatus = "idle";
            lastUploadError = string.Empty;
            lastUploadReportPath = string.Empty;
            lastUploadSummary = string.Empty;
            lastUploadRunId = string.Empty;
            lastUploadRunUrl = string.Empty;
            lastUploadReportUrl = string.Empty;
            lastUploadSummaryUrl = string.Empty;
            lastUploadZipUrl = string.Empty;
            lastUploadAtMs = -1;
            startFramesCaptured = frameCapture.FramesCaptured;
            startFramesSent = frameCapture.FramesSent;
            startFramesDroppedBusy = frameCapture.FramesDroppedBusy;
            startFramesDroppedNoConn = frameCapture.FramesDroppedNoConn;
            framesDirectoryPath = string.Empty;
            framesMetaPath = string.Empty;
            framesIndexPath = string.Empty;
            framesCount = 0;
            scenarioApiCalls.Clear();
            for (var i = 0; i < pendingScenarioApiCalls.Count; i++)
            {
                scenarioApiCalls.Add((pendingScenarioApiCalls[i].DeepClone() as JObject) ?? new JObject());
            }
            pendingScenarioApiCalls.Clear();

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
            OpenWsEventsWriter();
            OpenEventsV1Recorder();
            OpenFrameInputWriters();

            if (saveMetricsSnapshot)
            {
                yield return CaptureMetricsSnapshot(MetricsBeforeFileName, path => metricsBeforePath = path);
            }

            runRecorder.SetScenarioTag(currentScenarioTag);
            runRecorder.SetRecordFrames(recordFramesForReplay);
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
                yield return CaptureMetricsSnapshot(MetricsAfterFileName, path => metricsAfterPath = path);
            }

            endMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            CloseWsEventsWriter();
            CloseEventsV1Recorder();
            CloseFrameInputWriters();
            lastFinishReason = reason;
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
                ["wsJsonl"] = WsJsonlFileName,
                ["eventsV1Jsonl"] = EventsV1RelativePath,
                ["metricsBefore"] = MetricsBeforeFileName,
                ["metricsAfter"] = MetricsAfterFileName,
                ["framesDir"] = FramesDirName,
                ["framesMetaJsonl"] = FramesMetaFileName,
                ["framesIndexJsonl"] = FramesIndexFileName,
                ["framesCount"] = framesCount,
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
                ["scenarioApiCalls"] = BuildScenarioApiCallsArray(),
                ["errors"] = new JArray(runErrors),
                ["export"] = BuildExportObject(),
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

        private JObject BuildExportObject()
        {
            var files = new JArray();
            for (var i = 0; i < lastExportFiles.Count; i++)
            {
                var stat = lastExportFiles[i];
                files.Add(new JObject
                {
                    ["path"] = stat.RelativePath,
                    ["bytes"] = stat.Bytes,
                    ["sha256"] = stat.Sha256,
                });
            }

            var errors = new JArray();
            for (var i = 0; i < lastExportErrors.Count; i++)
            {
                errors.Add(lastExportErrors[i]);
            }

            return new JObject
            {
                ["zipPath"] = lastExportZipPath ?? string.Empty,
                ["zipSha256"] = lastExportSha256 ?? string.Empty,
                ["exportedAtMs"] = lastExportedAtMs,
                ["files"] = files,
                ["errors"] = errors,
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

        private void UnbindRuntimeEvents()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnUiEventAccepted -= HandleUiEventAccepted;
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
            if (!runActive || evt == null)
            {
                return;
            }

            eventCountAccepted++;
            WriteWsEventRow(evt);
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var receivedAtMs = ReadLong(evt, "_receivedAtMs", nowMs);
            var ttlMs = ReadInt(evt, "_eventTtlMs", ReadInt(evt, "ttlMs", 1500));
            if (eventV1Recorder != null && !eventV1Recorder.RecordAcceptedEvent(evt, receivedAtMs, ttlMs, out var normalizeError))
            {
                runErrors.Add($"events_v1_write_failed:{normalizeError}");
            }
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

        private void HandleFrameAccepted(FrameCapture.FrameAcceptedInfo info)
        {
            if (!runActive || runFinishing)
            {
                return;
            }

            var metaObj = ParseMetaObject(info.MetaJson);
            var seq = info.Seq > 0 ? info.Seq : ReadLong(metaObj, "seq", framesCount + 1);
            var frameFileRelative = $"{FramesDirName}/frame_{seq}.jpg";
            var frameFileAbsolute = string.Empty;
            var fileSha = string.Empty;
            var bytes = info.JpgBytes != null ? info.JpgBytes.Length : 0;

            if (recordFramesForReplay && info.JpgBytes != null && info.JpgBytes.Length > 0 && !string.IsNullOrWhiteSpace(framesDirectoryPath))
            {
                try
                {
                    Directory.CreateDirectory(framesDirectoryPath);
                    frameFileAbsolute = Path.Combine(framesDirectoryPath, $"frame_{seq}.jpg");
                    File.WriteAllBytes(frameFileAbsolute, info.JpgBytes);
                    fileSha = ComputeBytesSha256(info.JpgBytes);
                }
                catch (Exception ex)
                {
                    runErrors.Add($"frame_write_failed:{seq}:{ex.Message}");
                    frameFileAbsolute = string.Empty;
                    fileSha = string.Empty;
                }
            }

            var row = new JObject
            {
                ["seq"] = seq,
                ["timestampMs"] = info.TimestampMs,
                ["receivedAtMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["framePath"] = recordFramesForReplay ? frameFileRelative : string.Empty,
                ["bytes"] = bytes,
                ["width"] = info.Width,
                ["height"] = info.Height,
                ["roiApplied"] = info.RoiApplied,
                ["meta"] = metaObj,
            };

            WriteFrameMetaRow(row);
            if (!string.IsNullOrWhiteSpace(frameFileAbsolute))
            {
                var indexRow = new JObject
                {
                    ["seq"] = seq,
                    ["path"] = frameFileRelative,
                    ["bytes"] = bytes,
                    ["sha256"] = fileSha,
                };
                WriteFrameIndexRow(indexRow);
            }

            framesCount++;
        }

        public void ClearScenarioApiCalls()
        {
            pendingScenarioApiCalls.Clear();
            if (!runActive)
            {
                scenarioApiCalls.Clear();
            }
        }

        public void RecordScenarioApiCall(string method, string path, JObject body)
        {
            var row = new JObject
            {
                ["atMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["method"] = string.IsNullOrWhiteSpace(method) ? "GET" : method.Trim().ToUpperInvariant(),
                ["path"] = string.IsNullOrWhiteSpace(path) ? "/" : path.Trim(),
                ["body"] = body != null ? body.DeepClone() : null,
            };

            pendingScenarioApiCalls.Add(row);
            if (runActive && !runFinishing)
            {
                scenarioApiCalls.Add((row.DeepClone() as JObject) ?? new JObject());
            }
        }

        public bool ExportLastRunZip(out string zipPath, out string error)
        {
            zipPath = string.Empty;
            error = string.Empty;
            EnsureDependencies();

            if (runActive || runFinishing)
            {
                error = "run_active";
                return false;
            }

            if (string.IsNullOrWhiteSpace(currentRunDirectory) || !Directory.Exists(currentRunDirectory))
            {
                error = "no_last_run";
                return false;
            }

            if (string.IsNullOrWhiteSpace(currentManifestPath) || !File.Exists(currentManifestPath))
            {
                error = "manifest_missing";
                return false;
            }

            var success = TryExportRunZip(currentRunDirectory, currentManifestPath, out zipPath, out error);
            if (success)
            {
                WriteManifest(string.IsNullOrWhiteSpace(lastFinishReason) ? "exported" : lastFinishReason);
                if (autoUploadAfterExport)
                {
                    UploadLastRunZip(gatewayClient != null ? gatewayClient.BaseUrl : "http://127.0.0.1:8000");
                }
            }

            return success;
        }

        public bool UploadLastRunZip(string baseUrl)
        {
            if (uploadInFlight)
            {
                lastUploadStatus = "busy";
                lastUploadError = "upload_in_flight";
                return false;
            }

            var zipPath = ResolveLastExportAbsolutePath();
            if (string.IsNullOrWhiteSpace(zipPath) || !File.Exists(zipPath))
            {
                lastUploadStatus = "error";
                lastUploadError = "zip_not_found";
                return false;
            }

            var targetBase = string.IsNullOrWhiteSpace(baseUrl)
                ? "http://127.0.0.1:8000"
                : baseUrl.TrimEnd('/');
            StartCoroutine(UploadZipCoroutine(zipPath, targetBase));
            return true;
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

        private void OpenFrameInputWriters()
        {
            CloseFrameInputWriters();
            try
            {
                if (recordFramesForReplay)
                {
                    framesDirectoryPath = Path.Combine(currentRunDirectory, FramesDirName);
                    Directory.CreateDirectory(framesDirectoryPath);
                }
                else
                {
                    framesDirectoryPath = string.Empty;
                }

                framesMetaPath = Path.Combine(currentRunDirectory, FramesMetaFileName);
                framesMetaWriter = new StreamWriter(framesMetaPath, false, new UTF8Encoding(false))
                {
                    AutoFlush = true,
                };

                framesIndexPath = Path.Combine(currentRunDirectory, FramesIndexFileName);
                framesIndexWriter = new StreamWriter(framesIndexPath, false, new UTF8Encoding(false))
                {
                    AutoFlush = true,
                };
            }
            catch (Exception ex)
            {
                runErrors.Add($"frame_writer_open_failed:{ex.Message}");
                CloseFrameInputWriters();
            }
        }

        private void CloseFrameInputWriters()
        {
            try
            {
                lock (frameWriteLock)
                {
                    framesMetaWriter?.Flush();
                    framesMetaWriter?.Dispose();
                    framesMetaWriter = null;

                    framesIndexWriter?.Flush();
                    framesIndexWriter?.Dispose();
                    framesIndexWriter = null;
                }
            }
            catch (Exception ex)
            {
                runErrors.Add($"frame_writer_close_failed:{ex.Message}");
            }
        }

        private void WriteFrameMetaRow(JObject row)
        {
            if (row == null || framesMetaWriter == null)
            {
                return;
            }

            try
            {
                lock (frameWriteLock)
                {
                    framesMetaWriter.WriteLine(row.ToString(Formatting.None));
                }
            }
            catch (Exception ex)
            {
                runErrors.Add($"frame_meta_write_failed:{ex.Message}");
            }
        }

        private void WriteFrameIndexRow(JObject row)
        {
            if (row == null || framesIndexWriter == null)
            {
                return;
            }

            try
            {
                lock (frameWriteLock)
                {
                    framesIndexWriter.WriteLine(row.ToString(Formatting.None));
                }
            }
            catch (Exception ex)
            {
                runErrors.Add($"frame_index_write_failed:{ex.Message}");
            }
        }

        private JArray BuildScenarioApiCallsArray()
        {
            var rows = new JArray();
            for (var i = 0; i < scenarioApiCalls.Count; i++)
            {
                rows.Add((scenarioApiCalls[i].DeepClone() as JObject) ?? new JObject());
            }
            return rows;
        }

        private static JObject ParseMetaObject(string metaJson)
        {
            if (string.IsNullOrWhiteSpace(metaJson))
            {
                return new JObject();
            }

            try
            {
                return JObject.Parse(metaJson);
            }
            catch
            {
                return new JObject
                {
                    ["raw"] = metaJson,
                };
            }
        }

        private bool TryExportRunZip(string runDirectory, string manifestPath, out string zipPath, out string error)
        {
            zipPath = string.Empty;
            error = string.Empty;
            lastExportErrors.Clear();
            lastExportFiles.Clear();
            lastExportZipPath = string.Empty;
            lastExportSha256 = string.Empty;
            lastExportedAtMs = -1;

            try
            {
                if (!Directory.Exists(runDirectory))
                {
                    error = "run_dir_missing";
                    lastExportErrors.Add(error);
                    return false;
                }

                if (!File.Exists(manifestPath))
                {
                    error = "manifest_missing";
                    lastExportErrors.Add(error);
                    return false;
                }

                var runRoot = Path.GetDirectoryName(runDirectory) ?? runDirectory;
                var exportsRoot = Path.Combine(runRoot, "exports");
                Directory.CreateDirectory(exportsRoot);

                var runName = Path.GetFileName(runDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar));
                var zipAbsPath = Path.Combine(exportsRoot, $"{runName}.zip");
                if (File.Exists(zipAbsPath))
                {
                    File.Delete(zipAbsPath);
                }

                var filesToZip = CollectExportFiles(runDirectory, manifestPath);
                using (var fs = new FileStream(zipAbsPath, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var archive = new ZipArchive(fs, ZipArchiveMode.Create))
                {
                    for (var i = 0; i < filesToZip.Count; i++)
                    {
                        var item = filesToZip[i];
                        if (!File.Exists(item.SourcePath))
                        {
                            lastExportErrors.Add($"missing_file:{item.RelativePath}");
                            continue;
                        }

                        var entry = archive.CreateEntry(item.RelativePath, System.IO.Compression.CompressionLevel.Optimal);
                        using (var inStream = new FileStream(item.SourcePath, FileMode.Open, FileAccess.Read, FileShare.Read))
                        using (var outStream = entry.Open())
                        {
                            inStream.CopyTo(outStream);
                        }

                        var bytes = new FileInfo(item.SourcePath).Length;
                        var fileSha = ComputeFileSha256(item.SourcePath);
                        lastExportFiles.Add(new ExportFileStat(item.RelativePath, bytes, fileSha));
                    }
                }

                lastExportSha256 = ComputeFileSha256(zipAbsPath);
                lastExportedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                lastExportZipPath = MakeStableExportPath(runRoot, zipAbsPath);
                zipPath = zipAbsPath;
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                lastExportErrors.Add($"zip_export_failed:{ex.Message}");
                return false;
            }
        }

        private IEnumerator UploadZipCoroutine(string zipAbsolutePath, string baseUrl)
        {
            uploadInFlight = true;
            lastUploadStatus = "uploading";
            lastUploadError = string.Empty;
            lastUploadReportPath = string.Empty;
            lastUploadSummary = string.Empty;
            lastUploadRunId = string.Empty;
            lastUploadRunUrl = string.Empty;
            lastUploadReportUrl = string.Empty;
            lastUploadSummaryUrl = string.Empty;
            lastUploadZipUrl = string.Empty;
            lastUploadAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            var endpoint = $"{baseUrl}/api/run_package/upload";
            byte[] bytes;
            try
            {
                bytes = File.ReadAllBytes(zipAbsolutePath);
            }
            catch (Exception ex)
            {
                uploadInFlight = false;
                lastUploadStatus = "error";
                lastUploadError = $"zip_read_failed:{ex.Message}";
                yield break;
            }

            var scenario = currentScenarioTag;
            if (string.IsNullOrWhiteSpace(scenario))
            {
                scenario = "run";
            }

            var form = new WWWForm();
            form.AddBinaryData("file", bytes, Path.GetFileName(zipAbsolutePath), "application/zip");
            form.AddField("scenarioTag", scenario);
            using (var req = UnityWebRequest.Post(endpoint, form))
            {
                req.timeout = Mathf.Clamp(uploadTimeoutSec, 1, 60);
                yield return req.SendWebRequest();
                uploadInFlight = false;
                lastUploadAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    lastUploadStatus = "error";
                    lastUploadError = req.error ?? "upload_failed";
                    yield break;
                }

                var body = req.downloadHandler != null ? req.downloadHandler.text : string.Empty;
                try
                {
                    var payload = string.IsNullOrWhiteSpace(body) ? new JObject() : JObject.Parse(body);
                    if (payload.Value<bool?>("ok") != true)
                    {
                        lastUploadStatus = "error";
                        lastUploadError = ReadString(payload, "detail");
                        if (string.IsNullOrWhiteSpace(lastUploadError))
                        {
                            lastUploadError = "upload_response_not_ok";
                        }
                        yield break;
                    }

                    lastUploadStatus = "ok";
                    lastUploadError = string.Empty;
                    lastUploadRunId = ReadString(payload, "runId");
                    lastUploadReportPath = ReadString(payload, "reportMdPath");
                    lastUploadRunUrl = ReadString(payload, "runUrl");
                    lastUploadReportUrl = ReadString(payload, "reportUrl");
                    lastUploadSummaryUrl = ReadString(payload, "summaryUrl");
                    lastUploadZipUrl = ReadString(payload, "zipUrl");
                    lastUploadSummary = BuildUploadSummary(payload["summary"] as JObject);
                    UpdateManifestServerLinks();
                }
                catch (Exception ex)
                {
                    lastUploadStatus = "error";
                    lastUploadError = $"upload_parse_failed:{ex.Message}";
                    lastUploadRunId = string.Empty;
                    lastUploadRunUrl = string.Empty;
                    lastUploadReportUrl = string.Empty;
                    lastUploadSummaryUrl = string.Empty;
                    lastUploadZipUrl = string.Empty;
                }
            }
        }

        private void UpdateManifestServerLinks()
        {
            if (string.IsNullOrWhiteSpace(currentManifestPath) || !File.Exists(currentManifestPath))
            {
                return;
            }

            try
            {
                var raw = File.ReadAllText(currentManifestPath, Encoding.UTF8);
                var manifest = string.IsNullOrWhiteSpace(raw) ? new JObject() : JObject.Parse(raw);
                var server = manifest["server"] as JObject ?? new JObject();
                server["runId"] = lastUploadRunId ?? string.Empty;
                server["runUrl"] = lastUploadRunUrl ?? string.Empty;
                server["reportUrl"] = lastUploadReportUrl ?? string.Empty;
                server["summaryUrl"] = lastUploadSummaryUrl ?? string.Empty;
                server["zipUrl"] = lastUploadZipUrl ?? string.Empty;
                server["uploadedAtMs"] = lastUploadAtMs;
                server["uploadStatus"] = lastUploadStatus ?? string.Empty;
                manifest["server"] = server;
                File.WriteAllText(currentManifestPath, manifest.ToString(Formatting.Indented), new UTF8Encoding(false));
            }
            catch (Exception ex)
            {
                runErrors.Add($"manifest_server_update_failed:{ex.Message}");
            }
        }

        private string ResolveLastExportAbsolutePath()
        {
            if (string.IsNullOrWhiteSpace(lastExportZipPath))
            {
                return string.Empty;
            }

            if (Path.IsPathRooted(lastExportZipPath))
            {
                return lastExportZipPath;
            }

            if (string.IsNullOrWhiteSpace(currentRunDirectory))
            {
                return string.Empty;
            }
            var runRoot = Path.GetDirectoryName(currentRunDirectory) ?? currentRunDirectory;
            return Path.Combine(runRoot, lastExportZipPath.Replace('/', Path.DirectorySeparatorChar));
        }

        private static string BuildUploadSummary(JObject summary)
        {
            if (summary == null)
            {
                return string.Empty;
            }

            var frameReceived = ReadLong(summary, "frame_received", -1);
            var frameCompleted = ReadLong(summary, "frame_completed", -1);
            var e2eCount = ReadLong(summary, "e2e_count", -1);
            var ttfaCount = ReadLong(summary, "ttfa_count", -1);
            var safe = ReadLong(summary, "safemode_enter", -1);
            var throttle = ReadLong(summary, "throttle_enter", -1);
            var preempt = ReadLong(summary, "preempt_enter", -1);
            var confirmReq = ReadLong(summary, "confirm_request", -1);
            return $"frame={frameReceived}/{frameCompleted} e2e={e2eCount} ttfa={ttfaCount} safe={safe} throttle={throttle} preempt={preempt} confirm={confirmReq}";
        }

        private List<ExportFilePath> CollectExportFiles(string runDirectory, string manifestPath)
        {
            var results = new List<ExportFilePath>();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            AddDirectoryFiles(runDirectory, string.Empty, results, seen);
            if (!seen.Contains(Path.GetFullPath(manifestPath)))
            {
                var rel = Path.GetFileName(manifestPath);
                results.Add(new ExportFilePath(Path.GetFullPath(manifestPath), NormalizeArchivePath(rel)));
                seen.Add(Path.GetFullPath(manifestPath));
            }

            try
            {
                var manifest = JObject.Parse(File.ReadAllText(manifestPath, Encoding.UTF8));
                var recorderDir = ReadString(manifest["runRecorder"] as JObject, "runDirectory");
                if (!string.IsNullOrWhiteSpace(recorderDir) && Directory.Exists(recorderDir))
                {
                    var runDirFull = Path.GetFullPath(runDirectory)
                        .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    var recorderFull = Path.GetFullPath(recorderDir)
                        .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    if (!string.Equals(runDirFull, recorderFull, StringComparison.OrdinalIgnoreCase))
                    {
                        AddDirectoryFiles(recorderDir, "recorder", results, seen);
                    }
                }
            }
            catch (Exception ex)
            {
                lastExportErrors.Add($"recorder_files_scan_failed:{ex.Message}");
            }

            results.Sort((a, b) => string.CompareOrdinal(a.RelativePath, b.RelativePath));
            return results;
        }

        private static void AddDirectoryFiles(
            string directory,
            string archivePrefix,
            List<ExportFilePath> output,
            HashSet<string> seen)
        {
            var baseDir = Path.GetFullPath(directory)
                .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var prefix = string.IsNullOrWhiteSpace(archivePrefix) ? string.Empty : NormalizeArchivePath(archivePrefix).TrimEnd('/');
            var files = Directory.GetFiles(baseDir, "*", SearchOption.AllDirectories);
            for (var i = 0; i < files.Length; i++)
            {
                var fullPath = Path.GetFullPath(files[i]);
                if (seen.Contains(fullPath))
                {
                    continue;
                }

                var relative = fullPath.Substring(baseDir.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                relative = NormalizeArchivePath(relative);
                if (!string.IsNullOrWhiteSpace(prefix))
                {
                    relative = $"{prefix}/{relative}";
                }

                output.Add(new ExportFilePath(fullPath, relative));
                seen.Add(fullPath);
            }
        }

        private static string MakeStableExportPath(string rootDir, string absolutePath)
        {
            try
            {
                var root = Path.GetFullPath(rootDir)
                    .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                var full = Path.GetFullPath(absolutePath);
                if (full.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                {
                    var relative = full.Substring(root.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                    return NormalizeArchivePath(relative);
                }
            }
            catch
            {
            }

            return absolutePath;
        }

        private static string NormalizeArchivePath(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                return string.Empty;
            }
            return path.Replace('\\', '/');
        }

        private static string ComputeFileSha256(string path)
        {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var sha = SHA256.Create())
            {
                var hash = sha.ComputeHash(stream);
                return string.Concat(hash.Select(b => b.ToString("x2")));
            }
        }

        private static string ComputeBytesSha256(byte[] bytes)
        {
            if (bytes == null || bytes.Length == 0)
            {
                return string.Empty;
            }

            using (var sha = SHA256.Create())
            {
                var hash = sha.ComputeHash(bytes);
                return string.Concat(hash.Select(b => b.ToString("x2")));
            }
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

        private void OpenEventsV1Recorder()
        {
            CloseEventsV1Recorder();
            try
            {
                eventV1Recorder = new EventV1Recorder();
                if (!eventV1Recorder.Start(currentRunDirectory, EventsDirName, EventsV1FileName, out var error))
                {
                    runErrors.Add($"events_v1_open_failed:{error}");
                    eventV1Recorder = null;
                }
            }
            catch (Exception ex)
            {
                runErrors.Add($"events_v1_open_failed:{ex.Message}");
                eventV1Recorder = null;
            }
        }

        private void CloseEventsV1Recorder()
        {
            if (eventV1Recorder == null)
            {
                return;
            }

            try
            {
                eventV1Recorder.Stop();
            }
            catch (Exception ex)
            {
                runErrors.Add($"events_v1_close_failed:{ex.Message}");
            }
            finally
            {
                eventV1Recorder = null;
            }
        }

        private void OpenWsEventsWriter()
        {
            CloseWsEventsWriter();
            var wsEventsPath = Path.Combine(currentRunDirectory, WsJsonlFileName);
            try
            {
                wsEventsWriter = new StreamWriter(wsEventsPath, false, new UTF8Encoding(false))
                {
                    AutoFlush = true,
                };
            }
            catch (Exception ex)
            {
                wsEventsWriter = null;
                runErrors.Add($"ws_events_open_failed:{ex.Message}");
            }
        }

        private void CloseWsEventsWriter()
        {
            try
            {
                lock (wsWriteLock)
                {
                    wsEventsWriter?.Flush();
                    wsEventsWriter?.Dispose();
                    wsEventsWriter = null;
                }
            }
            catch (Exception ex)
            {
                runErrors.Add($"ws_events_close_failed:{ex.Message}");
            }
        }

        private void WriteWsEventRow(JObject evt)
        {
            if (wsEventsWriter == null || evt == null)
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var receivedAtMs = ReadLong(evt, "_receivedAtMs", nowMs);
            var ttlMs = ReadInt(evt, "_eventTtlMs", ReadInt(evt, "ttlMs", 1500));
            var row = new JObject
            {
                ["receivedAtMs"] = receivedAtMs,
                ["ttlMs"] = ttlMs,
                ["event"] = evt.DeepClone(),
            };

            try
            {
                lock (wsWriteLock)
                {
                    wsEventsWriter.WriteLine(row.ToString(Formatting.None));
                }
            }
            catch (Exception ex)
            {
                runErrors.Add($"ws_events_write_failed:{ex.Message}");
            }
        }

        private static long ReadLong(JObject obj, string key, long defaultValue)
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

        private static int ReadInt(JObject obj, string key, int defaultValue)
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

        private readonly struct ExportFilePath
        {
            public ExportFilePath(string sourcePath, string relativePath)
            {
                SourcePath = sourcePath;
                RelativePath = relativePath;
            }

            public string SourcePath { get; }
            public string RelativePath { get; }
        }

        private readonly struct ExportFileStat
        {
            public ExportFileStat(string relativePath, long bytes, string sha256)
            {
                RelativePath = relativePath;
                Bytes = bytes;
                Sha256 = sha256;
            }

            public string RelativePath { get; }
            public long Bytes { get; }
            public string Sha256 { get; }
        }
    }
}
