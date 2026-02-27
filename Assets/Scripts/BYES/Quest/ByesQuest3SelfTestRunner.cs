using System;
using System.Collections;
using System.Collections.Generic;
using BYES.Telemetry;
using BYES.UI;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Unity.Interaction;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;

namespace BYES.Quest
{
    public sealed class ByesQuest3SelfTestRunner : MonoBehaviour
    {
        private const string PrefHost = "byes.connection.host";
        private const string PrefPort = "byes.connection.port";
        private const string PrefUseHttps = "byes.connection.https";
        private const string PrefApiKey = "byes.connection.api_key";

        [SerializeField] private bool autoRunOnStart = true;
        [SerializeField] private float startupDelaySec = 1.5f;
        [SerializeField] private int pingSamples = 5;
        [SerializeField] private float liveDurationSec = 12f;
        [SerializeField] private bool verifyModeWrite = true;
        [SerializeField] private bool verboseLogs = true;

        private GatewayClient _gatewayClient;
        private GatewayWsClient _gatewayWsClient;
        private ScanController _scanController;
        private ByesConnectionPanel _connectionPanel;
        private Coroutine _selfTestRoutine;
        private string _status = "IDLE";
        private string _summary = "-";

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AutoInstallOnQuestSmokeScene()
        {
            var scene = SceneManager.GetActiveScene();
            if (!string.Equals(scene.name, "Quest3SmokeScene", StringComparison.Ordinal))
            {
                return;
            }

            if (FindFirstObjectByType<ByesQuest3SelfTestRunner>() != null)
            {
                return;
            }

            var host = new GameObject("BYES_Quest3SelfTestRunner");
            host.AddComponent<ByesQuest3SelfTestRunner>();
        }

        private void Awake()
        {
            ResolveRefs();
            PushPanelStatus();
        }

        private void Start()
        {
            if (autoRunOnStart)
            {
                StartSelfTest();
            }
        }

        public void StartSelfTest()
        {
            if (_selfTestRoutine != null)
            {
                return;
            }

            _selfTestRoutine = StartCoroutine(RunSelfTestRoutine());
        }

        private IEnumerator RunSelfTestRoutine()
        {
            SetStatus("RUNNING", "initializing");
            ResolveRefs();
            ApplyPreferredConnection();
            yield return new WaitForSeconds(Mathf.Max(0.1f, startupDelaySec));

            ResolveRefs();
            var failures = new List<string>();

            if (_gatewayClient == null)
            {
                failures.Add("GatewayClient missing");
                FinalizeResult(pass: false, failures, "gateway client missing");
                _selfTestRoutine = null;
                yield break;
            }

            if (_scanController == null)
            {
                failures.Add("ScanController missing");
                FinalizeResult(pass: false, failures, "scan controller missing");
                _selfTestRoutine = null;
                yield break;
            }

            var pingRtts = new List<long>();
            for (var i = 0; i < Math.Max(1, pingSamples); i += 1)
            {
                var done = false;
                var ok = false;
                long rttMs = -1;
                string error = string.Empty;
                yield return PingOnce(i + 1, (pingOk, pingRtt, pingError) =>
                {
                    ok = pingOk;
                    rttMs = pingRtt;
                    error = pingError;
                    done = true;
                });
                if (!done || !ok || rttMs < 0)
                {
                    if (!string.IsNullOrWhiteSpace(error))
                    {
                        failures.Add($"ping[{i + 1}] {error}");
                    }
                    continue;
                }

                pingRtts.Add(rttMs);
                yield return new WaitForSeconds(0.1f);
            }

            long medianPingMs = -1;
            if (pingRtts.Count > 0)
            {
                pingRtts.Sort();
                medianPingMs = pingRtts[pingRtts.Count / 2];
            }
            else
            {
                failures.Add("no successful ping");
            }

            var versionOk = false;
            string versionText = string.Empty;
            var versionDone = false;
            yield return GetJson("/api/version", (ok, obj, error) =>
            {
                if (ok && obj != null)
                {
                    versionText = (obj.Value<string>("version") ?? string.Empty).Trim();
                    versionOk = !string.IsNullOrWhiteSpace(versionText);
                }
                else
                {
                    failures.Add($"version {error}");
                }
                versionDone = true;
            });
            if (!versionDone || !versionOk)
            {
                failures.Add("version parse failed");
            }
            else if (!string.Equals(versionText, "v4.94", StringComparison.Ordinal))
            {
                failures.Add($"version mismatch ({versionText})");
            }

            string currentMode = string.Empty;
            var modeReadOk = false;
            yield return GetJson($"/api/mode?deviceId={UnityWebRequest.EscapeURL(ByesFrameTelemetry.DeviceId)}", (ok, obj, error) =>
            {
                if (!ok || obj == null)
                {
                    failures.Add($"read_mode {error}");
                    return;
                }

                currentMode = (obj.Value<string>("mode") ?? string.Empty).Trim();
                modeReadOk = !string.IsNullOrWhiteSpace(currentMode);
            });
            if (!modeReadOk)
            {
                failures.Add("mode read failed");
            }

            if (verifyModeWrite && modeReadOk)
            {
                var targetMode = string.Equals(currentMode, "walk", StringComparison.OrdinalIgnoreCase)
                    ? "read_text"
                    : "walk";
                var writeDone = false;
                yield return PostJson("/api/mode", new JObject
                {
                    ["runId"] = "quest3-selftest",
                    ["frameSeq"] = 1,
                    ["mode"] = targetMode,
                    ["source"] = "system",
                    ["tsMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    ["deviceId"] = ByesFrameTelemetry.DeviceId,
                }, (ok, _, error) =>
                {
                    if (!ok)
                    {
                        failures.Add($"mode write {error}");
                    }
                    writeDone = true;
                });

                if (!writeDone)
                {
                    failures.Add("mode write timeout");
                }
                else
                {
                    yield return GetJson($"/api/mode?deviceId={UnityWebRequest.EscapeURL(ByesFrameTelemetry.DeviceId)}", (ok, obj, error) =>
                    {
                        if (!ok || obj == null)
                        {
                            failures.Add($"mode verify {error}");
                            return;
                        }

                        var verifiedMode = (obj.Value<string>("mode") ?? string.Empty).Trim();
                        if (!string.Equals(verifiedMode, targetMode, StringComparison.OrdinalIgnoreCase))
                        {
                            failures.Add($"mode verify mismatch ({verifiedMode})");
                        }
                    });
                }
            }

            var startFramesSent = _scanController.FramesSentCount;
            var startUploadOk = _scanController.UploadsOkCount;
            var startDropBusy = _scanController.DropBusyCount;
            var startEvents = _scanController.EventsReceivedCount;

            _scanController.SetLiveEnabled(true);
            yield return new WaitForSeconds(Mathf.Max(5f, liveDurationSec));
            _scanController.SetLiveEnabled(false);
            yield return new WaitForSeconds(0.3f);

            var framesSent = Math.Max(0, _scanController.FramesSentCount - startFramesSent);
            var uploadsOk = Math.Max(0, _scanController.UploadsOkCount - startUploadOk);
            var dropBusy = Math.Max(0, _scanController.DropBusyCount - startDropBusy);
            var eventsReceived = Math.Max(0, _scanController.EventsReceivedCount - startEvents);
            var wsConnected = _gatewayWsClient != null && string.Equals(_gatewayWsClient.ConnectionState, "Connected", StringComparison.Ordinal);

            if (framesSent <= 0)
            {
                failures.Add("live loop produced zero frames");
            }
            if (uploadsOk <= 0)
            {
                failures.Add("no successful frame upload");
            }
            if (!wsConnected)
            {
                failures.Add("ws not connected");
            }
            if (eventsReceived <= 0)
            {
                failures.Add("no ws inference events during live loop");
            }

            var summary =
                $"ping_median_ms={medianPingMs}, version={versionText}, frames_sent={framesSent}, uploads_ok={uploadsOk}, events_received={eventsReceived}, drop_busy={dropBusy}, ws_connected={wsConnected}";
            var pass = failures.Count == 0;
            FinalizeResult(pass, failures, summary);
            _selfTestRoutine = null;
        }

        private void FinalizeResult(bool pass, List<string> failures, string summary)
        {
            var finalSummary = summary;
            if (failures.Count > 0)
            {
                finalSummary = string.IsNullOrWhiteSpace(summary)
                    ? string.Join("; ", failures)
                    : summary + " | failures=" + string.Join("; ", failures);
            }

            SetStatus(pass ? "PASS" : "FAIL", finalSummary);
            if (verboseLogs)
            {
                Debug.Log($"[ByesQuest3SelfTestRunner] {_status} {_summary}");
            }
        }

        private IEnumerator PingOnce(int seq, Action<bool, long, string> onDone)
        {
            var payload = new JObject
            {
                ["deviceId"] = ByesFrameTelemetry.DeviceId,
                ["seq"] = seq,
                ["clientSendTsMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
            var started = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var done = false;
            yield return SendRequest(
                method: UnityWebRequest.kHttpVerbPOST,
                path: "/api/ping",
                payload: payload,
                onDone: (ok, response, error) =>
                {
                    var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    var rtt = Math.Max(0L, now - started);
                    if (!ok || response == null)
                    {
                        onDone?.Invoke(false, -1, error);
                    }
                    else
                    {
                        onDone?.Invoke(true, rtt, string.Empty);
                    }
                    done = true;
                }
            );
            if (!done)
            {
                onDone?.Invoke(false, -1, "ping request canceled");
            }
        }

        private IEnumerator GetJson(string path, Action<bool, JObject, string> onDone)
        {
            yield return SendRequest(UnityWebRequest.kHttpVerbGET, path, null, onDone);
        }

        private IEnumerator PostJson(string path, JObject payload, Action<bool, JObject, string> onDone)
        {
            yield return SendRequest(UnityWebRequest.kHttpVerbPOST, path, payload, onDone);
        }

        private IEnumerator SendRequest(string method, string path, JObject payload, Action<bool, JObject, string> onDone)
        {
            ResolveRefs();
            if (_gatewayClient == null)
            {
                onDone?.Invoke(false, null, "gateway client missing");
                yield break;
            }

            var url = BuildApiUrl(path);
            byte[] body = null;
            if (payload != null)
            {
                body = System.Text.Encoding.UTF8.GetBytes(payload.ToString());
            }

            using (var req = new UnityWebRequest(url, method))
            {
                req.downloadHandler = new DownloadHandlerBuffer();
                if (body != null)
                {
                    req.uploadHandler = new UploadHandlerRaw(body);
                    req.SetRequestHeader("Content-Type", "application/json");
                }

                var apiKey = _gatewayClient.ApiKey;
                if (!string.IsNullOrWhiteSpace(apiKey))
                {
                    req.SetRequestHeader("X-BYES-API-Key", apiKey.Trim());
                }

                req.timeout = 8;
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    onDone?.Invoke(false, null, req.error);
                    yield break;
                }

                try
                {
                    var text = req.downloadHandler != null ? req.downloadHandler.text : "{}";
                    var obj = JObject.Parse(string.IsNullOrWhiteSpace(text) ? "{}" : text);
                    onDone?.Invoke(true, obj, string.Empty);
                }
                catch (Exception ex)
                {
                    onDone?.Invoke(false, null, $"json parse failed: {ex.Message}");
                }
            }
        }

        private void ApplyPreferredConnection()
        {
            ResolveRefs();
            if (_gatewayClient == null)
            {
                return;
            }

            var host = PlayerPrefs.GetString(PrefHost, string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(host))
            {
                host = "127.0.0.1";
            }

            var portText = PlayerPrefs.GetString(PrefPort, "8000").Trim();
            if (!int.TryParse(portText, out var port) || port <= 0 || port > 65535)
            {
                port = 8000;
            }

            var useHttps = PlayerPrefs.GetInt(PrefUseHttps, 0) == 1;
            var apiKey = PlayerPrefs.GetString(PrefApiKey, string.Empty);
            var scheme = useHttps ? "https" : "http";
            var wsScheme = useHttps ? "wss" : "ws";
            var baseUrl = $"{scheme}://{host}:{port}";
            var wsUrl = $"{wsScheme}://{host}:{port}/ws/events";

            _gatewayClient.SetApiKey(apiKey, reconnect: false);
            _gatewayClient.SetGatewayEndpoints(baseUrl, wsUrl, reconnect: true);
            if (_gatewayWsClient != null)
            {
                _gatewayWsClient.SetConnectionConfig(wsUrl, apiKey, reconnect: true);
            }
        }

        private string BuildApiUrl(string path)
        {
            var normalized = string.IsNullOrWhiteSpace(path) ? "/" : path.Trim();
            if (!normalized.StartsWith("/", StringComparison.Ordinal))
            {
                normalized = "/" + normalized;
            }

            return _gatewayClient.BaseUrl.TrimEnd('/') + normalized;
        }

        private void ResolveRefs()
        {
            if (_gatewayClient == null)
            {
                _gatewayClient = FindFirstObjectByType<GatewayClient>();
            }
            if (_gatewayWsClient == null)
            {
                _gatewayWsClient = FindFirstObjectByType<GatewayWsClient>();
            }
            if (_scanController == null)
            {
                _scanController = FindFirstObjectByType<ScanController>();
            }
            if (_connectionPanel == null)
            {
                _connectionPanel = FindFirstObjectByType<ByesConnectionPanel>();
            }
        }

        private void SetStatus(string status, string summary)
        {
            _status = string.IsNullOrWhiteSpace(status) ? "UNKNOWN" : status.Trim().ToUpperInvariant();
            _summary = string.IsNullOrWhiteSpace(summary) ? "-" : summary.Trim();
            PushPanelStatus();
        }

        private void PushPanelStatus()
        {
            if (_connectionPanel == null)
            {
                _connectionPanel = FindFirstObjectByType<ByesConnectionPanel>();
            }

            _connectionPanel?.SetSelfTestStatus(_status, _summary);
        }
    }
}
