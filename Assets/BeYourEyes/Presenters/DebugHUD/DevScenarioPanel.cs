using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using BeYourEyes.Adapters.Networking;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class DevScenarioPanel : MonoBehaviour
    {
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private GatewayDevApi gatewayDevApi;
        [SerializeField] private RunRecorder runRecorder;
        [SerializeField] private RunReplayer runReplayer;
        [SerializeField] private RunPackageManager runPackageManager;
        [SerializeField] private bool visible = true;
        [SerializeField] private int maxHistory = 30;
        [SerializeField] private int maxBodyChars = 800;

        private string baseUrlInput = "http://127.0.0.1:8000";
        private int intentIndex;
        private string intentQuestion = "What is in front of me?";

        private string faultTool = "mock_risk";
        private string faultMode = "timeout";
        private string faultValue = string.Empty;
        private string faultDurationMs = "10000";

        private string crosscheckKind = "transparent_obstacle";
        private string performancePayload = "{\"mode\":\"queue_pressure\"}";

        private bool scenarioRunning;
        private string currentScenario = "-";
        private long lastStatusCode = -1;
        private long lastLatencyMs = -1;
        private string lastResponseBody = string.Empty;
        private string lastError = string.Empty;
        private string lastMethodPath = "-";
        private string lastRunManifestPath = string.Empty;
        private string lastRunSummary = string.Empty;
        private Vector2 historyScroll;
        private float nextLookupAt;

        private readonly List<HistoryRow> history = new List<HistoryRow>();

        private static readonly string[] IntentOptions = { "normal", "scan_text", "ask", "qa" };
        private static readonly string[] FaultToolPresets = { "mock_risk", "mock_ocr", "real_det", "real_ocr", "real_depth", "real_vlm" };
        private static readonly string[] FaultModePresets = { "timeout", "slow", "low_conf", "disconnect", "critical" };

        private struct HistoryRow
        {
            public string at;
            public string method;
            public string path;
            public long status;
            public long latencyMs;
            public bool ok;
            public string error;
        }

        private void OnEnable()
        {
            EnsureDependencies();
            BindRunManager();
            if (gatewayClient != null)
            {
                baseUrlInput = gatewayClient.BaseUrl;
            }
        }

        private void OnDisable()
        {
            UnbindRunManager();
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

        private void OnGUI()
        {
            if (!visible)
            {
                if (GUI.Button(new Rect(Screen.width - 120f, 8f, 110f, 30f), "Dev Panel"))
                {
                    visible = true;
                }
                return;
            }

            GUILayout.BeginArea(new Rect(Screen.width - 430f, 8f, 420f, Mathf.Min(Screen.height - 16f, 860f)), "Dev Scenarios", GUI.skin.window);
            DrawHeader();
            DrawBaseUrlRow();
            DrawSingleOps();
            DrawIntentOps();
            DrawFaultOps();
            DrawScenarioOps();
            DrawResult();
            DrawHistory();
            GUILayout.EndArea();
        }

        private void DrawHeader()
        {
            GUILayout.BeginHorizontal();
            var runState = runPackageManager != null && runPackageManager.IsRunActive ? "RUNNING" : "IDLE";
            GUILayout.Label($"Replay: {(IsReplayBlocked() ? "ON" : "OFF")}  Scenario: {(scenarioRunning ? currentScenario : "idle")}  Run: {runState}");
            if (GUILayout.Button("Hide", GUILayout.Width(80f)))
            {
                visible = false;
            }
            GUILayout.EndHorizontal();
        }

        private void DrawBaseUrlRow()
        {
            GUILayout.Label("BaseUrl");
            baseUrlInput = GUILayout.TextField(baseUrlInput ?? string.Empty);
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Use From GatewayClient"))
            {
                EnsureDependencies();
                if (gatewayClient != null)
                {
                    baseUrlInput = gatewayClient.BaseUrl;
                }
                else
                {
                    PushUiError("GatewayClient missing");
                }
            }
            if (GUILayout.Button("Apply"))
            {
                EnsureDependencies();
                if (gatewayDevApi != null)
                {
                    gatewayDevApi.SetBaseUrl(baseUrlInput);
                }
            }
            GUILayout.EndHorizontal();
        }

        private void DrawSingleOps()
        {
            GUILayout.Space(4f);
            GUILayout.Label("Single Ops");
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Reset Runtime"))
            {
                StartCoroutine(RunSinglePost("/api/dev/reset", new JObject()));
            }
            if (GUILayout.Button("Fault Clear"))
            {
                StartCoroutine(RunSinglePost("/api/fault/clear", new JObject()));
            }
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Readiness"))
            {
                StartCoroutine(RunSingleGet("/api/external_readiness"));
            }
            if (GUILayout.Button("Metrics Reachability"))
            {
                StartCoroutine(RunSingleGet("/metrics"));
            }
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Crosscheck Once"))
            {
                StartCoroutine(RunSinglePost("/api/dev/crosscheck", new JObject { ["kind"] = crosscheckKind }));
            }
            if (GUILayout.Button("Performance Once"))
            {
                JObject perfPayload;
                try
                {
                    perfPayload = string.IsNullOrWhiteSpace(performancePayload)
                        ? new JObject { ["mode"] = "queue_pressure" }
                        : JObject.Parse(performancePayload);
                }
                catch
                {
                    perfPayload = new JObject { ["mode"] = "queue_pressure" };
                }
                StartCoroutine(RunSinglePost("/api/dev/performance", perfPayload));
            }
            GUILayout.EndHorizontal();
        }

        private void DrawIntentOps()
        {
            GUILayout.Space(4f);
            GUILayout.Label("Intent");
            intentIndex = Mathf.Clamp(GUILayout.SelectionGrid(intentIndex, IntentOptions, 4), 0, IntentOptions.Length - 1);
            intentQuestion = GUILayout.TextField(intentQuestion ?? string.Empty);
            if (GUILayout.Button("Send Intent"))
            {
                StartCoroutine(SendIntentRoutine());
            }
        }

        private void DrawFaultOps()
        {
            GUILayout.Space(4f);
            GUILayout.Label("Fault Set");

            GUILayout.BeginHorizontal();
            GUILayout.Label("Tool", GUILayout.Width(44f));
            faultTool = GUILayout.TextField(faultTool ?? string.Empty);
            if (GUILayout.Button("Preset", GUILayout.Width(60f)))
            {
                faultTool = NextPreset(faultTool, FaultToolPresets);
            }
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            GUILayout.Label("Mode", GUILayout.Width(44f));
            faultMode = GUILayout.TextField(faultMode ?? string.Empty);
            if (GUILayout.Button("Preset", GUILayout.Width(60f)))
            {
                faultMode = NextPreset(faultMode, FaultModePresets);
            }
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            GUILayout.Label("Value", GUILayout.Width(44f));
            faultValue = GUILayout.TextField(faultValue ?? string.Empty);
            GUILayout.Label("durationMs", GUILayout.Width(74f));
            faultDurationMs = GUILayout.TextField(faultDurationMs ?? "10000");
            GUILayout.EndHorizontal();

            if (GUILayout.Button("Set Fault"))
            {
                StartCoroutine(SendFaultSetRoutine());
            }
        }

        private void DrawScenarioOps()
        {
            GUILayout.Space(4f);
            GUILayout.Label("One-click Scenarios");
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("TimeoutScenario"))
            {
                StartCoroutine(RunTimeoutScenario());
            }
            if (GUILayout.Button("CriticalRiskScenario"))
            {
                StartCoroutine(RunCriticalRiskScenario());
            }
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("ActiveConfirmScenario"))
            {
                StartCoroutine(RunActiveConfirmScenario());
            }
            if (GUILayout.Button("QueuePressureScenario"))
            {
                StartCoroutine(RunQueuePressureScenario());
            }
            GUILayout.EndHorizontal();

            if (GUILayout.Button("EvidenceCriticalScenario"))
            {
                StartCoroutine(RunEvidenceCriticalScenario());
            }
        }

        private void DrawResult()
        {
            GUILayout.Space(4f);
            GUILayout.Label($"Last: {lastMethodPath}");
            GUILayout.Label($"status={lastStatusCode} latency={lastLatencyMs}ms error={lastError}");
            GUILayout.Label($"RunManifest: {Truncate(lastRunManifestPath, 100)}");
            GUILayout.Label($"RunSummary: {Truncate(lastRunSummary, 120)}");
            GUILayout.Label("Response:");
            GUILayout.TextArea(Truncate(lastResponseBody, maxBodyChars), GUILayout.Height(80f));
        }

        private void DrawHistory()
        {
            GUILayout.Space(4f);
            GUILayout.BeginHorizontal();
            GUILayout.Label("History");
            if (GUILayout.Button("Clear", GUILayout.Width(60f)))
            {
                history.Clear();
            }
            GUILayout.EndHorizontal();

            historyScroll = GUILayout.BeginScrollView(historyScroll, GUILayout.Height(190f));
            for (var i = history.Count - 1; i >= 0; i--)
            {
                var row = history[i];
                GUILayout.Label($"{row.at} {row.method} {row.path} status={row.status} lat={row.latencyMs} ok={row.ok} err={row.error}");
            }
            GUILayout.EndScrollView();
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
            if (runReplayer == null)
            {
                runReplayer = FindFirstObjectByType<RunReplayer>();
            }
            if (runPackageManager == null)
            {
                runPackageManager = FindFirstObjectByType<RunPackageManager>();
                if (runPackageManager == null)
                {
                    runPackageManager = GetComponent<RunPackageManager>();
                    if (runPackageManager == null)
                    {
                        runPackageManager = gameObject.AddComponent<RunPackageManager>();
                    }
                }
            }
            if (gatewayDevApi == null)
            {
                gatewayDevApi = GetComponent<GatewayDevApi>();
                if (gatewayDevApi == null)
                {
                    gatewayDevApi = gameObject.AddComponent<GatewayDevApi>();
                }
            }

            if (gatewayDevApi != null)
            {
                gatewayDevApi.SetBaseUrl(baseUrlInput);
            }

            BindRunManager();
        }

        private void BindRunManager()
        {
            if (runPackageManager == null)
            {
                return;
            }

            runPackageManager.OnRunCompleted -= HandleRunCompleted;
            runPackageManager.OnRunCompleted += HandleRunCompleted;
        }

        private void UnbindRunManager()
        {
            if (runPackageManager == null)
            {
                return;
            }

            runPackageManager.OnRunCompleted -= HandleRunCompleted;
        }

        private void HandleRunCompleted(string manifestPath, string summary)
        {
            lastRunManifestPath = manifestPath ?? string.Empty;
            lastRunSummary = summary ?? string.Empty;
            lastMethodPath = "RUN COMPLETE";
            lastStatusCode = 0;
            lastLatencyMs = 0;
            lastError = "-";
            lastResponseBody = summary ?? string.Empty;
            RecordHistory("RUN", "package", 0, 0, true, "-");
        }

        private IEnumerator RunSingleGet(string path)
        {
            yield return SendRequest("GET", path, null);
        }

        private IEnumerator RunSinglePost(string path, JObject payload)
        {
            yield return SendRequest("POST", path, payload);
        }

        private IEnumerator SendIntentRoutine()
        {
            var intent = IntentOptions[Mathf.Clamp(intentIndex, 0, IntentOptions.Length - 1)];
            var normalized = string.Equals(intent, "normal", StringComparison.OrdinalIgnoreCase) ? "none" : intent;
            if ((normalized == "ask" || normalized == "qa") && string.IsNullOrWhiteSpace(intentQuestion))
            {
                PushUiError("question_required");
                yield break;
            }

            var payload = new JObject
            {
                ["intent"] = normalized,
            };
            if (normalized == "ask" || normalized == "qa")
            {
                payload["question"] = intentQuestion.Trim();
            }

            yield return SendRequest("POST", "/api/dev/intent", payload);
        }

        private IEnumerator SendFaultSetRoutine()
        {
            var payload = new JObject
            {
                ["tool"] = string.IsNullOrWhiteSpace(faultTool) ? "mock_risk" : faultTool.Trim(),
                ["mode"] = string.IsNullOrWhiteSpace(faultMode) ? "timeout" : faultMode.Trim(),
            };

            if (int.TryParse(faultDurationMs, out var durationMs) && durationMs > 0)
            {
                payload["durationMs"] = durationMs;
            }

            if (!string.IsNullOrWhiteSpace(faultValue))
            {
                payload["value"] = ParseValueToken(faultValue.Trim());
            }

            yield return SendRequest("POST", "/api/fault/set", payload);
        }

        private IEnumerator RunTimeoutScenario()
        {
            yield return ExecuteScenario("TimeoutScenario", new[]
            {
                Step.Post("/api/dev/reset", new JObject()),
                Step.Post("/api/fault/set", BuildFaultPayload("mock_risk", "timeout", null, 30000)),
            });
        }

        private IEnumerator RunCriticalRiskScenario()
        {
            yield return ExecuteScenario("CriticalRiskScenario", new[]
            {
                Step.Post("/api/dev/reset", new JObject()),
                Step.Post("/api/fault/set", BuildFaultPayload("mock_risk", "critical", null, 10000)),
            });
        }

        private IEnumerator RunActiveConfirmScenario()
        {
            yield return ExecuteScenario("ActiveConfirmScenario", new[]
            {
                Step.Post("/api/dev/reset", new JObject()),
                Step.Post("/api/dev/intent", new JObject { ["intent"] = "none" }),
                Step.Post("/api/dev/crosscheck", new JObject { ["kind"] = "transparent_obstacle" }),
            });
        }

        private IEnumerator RunQueuePressureScenario()
        {
            JObject perfPayload;
            try
            {
                perfPayload = string.IsNullOrWhiteSpace(performancePayload)
                    ? new JObject { ["mode"] = "queue_pressure" }
                    : JObject.Parse(performancePayload);
            }
            catch
            {
                perfPayload = new JObject { ["mode"] = "queue_pressure" };
            }

            yield return ExecuteScenario("QueuePressureScenario", new[]
            {
                Step.Post("/api/dev/reset", new JObject()),
                Step.Post("/api/dev/performance", perfPayload),
            });
        }

        private IEnumerator RunEvidenceCriticalScenario()
        {
            yield return ExecuteScenario("EvidenceCriticalScenario", new[]
            {
                Step.Post("/api/dev/reset", new JObject()),
                Step.Post("/api/dev/crosscheck", new JObject { ["kind"] = crosscheckKind }),
                Step.Post("/api/fault/set", BuildFaultPayload("real_depth", "slow", 3000, 800)),
            });
        }

        private IEnumerator ExecuteScenario(string scenarioName, IReadOnlyList<Step> steps)
        {
            if (scenarioRunning)
            {
                PushUiError($"scenario_running:{currentScenario}");
                yield break;
            }

            if (IsReplayBlocked())
            {
                PushUiError("Replay mode: disabled");
                yield break;
            }

            scenarioRunning = true;
            currentScenario = scenarioName;
            if (runRecorder != null)
            {
                runRecorder.SetScenarioTag(scenarioName);
            }
            if (runPackageManager != null)
            {
                runPackageManager.StopRun();
            }

            for (var i = 0; i < steps.Count; i++)
            {
                var step = steps[i];
                yield return SendRequest(step.method, step.path, step.payload);
                yield return new WaitForSecondsRealtime(0.05f);
            }

            var scenarioPayload = BuildScenarioPayload(steps);
            if (runPackageManager == null)
            {
                PushUiError("run_package_manager_missing");
            }
            else if (runPackageManager.StartRun(scenarioName, scenarioPayload, out var runMessage))
            {
                lastMethodPath = $"RUN {scenarioName}";
                lastResponseBody = runMessage;
                while (runPackageManager.IsRunActive)
                {
                    yield return new WaitForSecondsRealtime(0.1f);
                }

                lastRunManifestPath = runPackageManager.CurrentManifestPath;
                lastRunSummary = runPackageManager.CurrentRunSummary;
                if (string.IsNullOrWhiteSpace(lastResponseBody))
                {
                    lastResponseBody = runPackageManager.CurrentRunSummary;
                }
            }
            else
            {
                PushUiError($"run_start_failed:{runMessage}");
            }

            scenarioRunning = false;
            currentScenario = "-";
        }

        private IEnumerator SendRequest(string method, string path, JObject payload)
        {
            EnsureDependencies();
            if (gatewayDevApi != null)
            {
                gatewayDevApi.SetBaseUrl(baseUrlInput);
            }

            if (IsReplayBlocked())
            {
                PushUiError("Replay mode: disabled");
                yield break;
            }

            if (gatewayDevApi == null)
            {
                PushUiError("GatewayDevApi missing");
                yield break;
            }

            DevApiResult result = default;
            var done = false;
            if (string.Equals(method, "GET", StringComparison.OrdinalIgnoreCase))
            {
                yield return StartCoroutine(gatewayDevApi.SendGet(path, r =>
                {
                    result = r;
                    done = true;
                }));
            }
            else
            {
                var json = payload == null ? "{}" : payload.ToString(Newtonsoft.Json.Formatting.None);
                yield return StartCoroutine(gatewayDevApi.SendPostJson(path, json, r =>
                {
                    result = r;
                    done = true;
                }));
            }

            if (!done)
            {
                PushUiError("request_not_finished");
                yield break;
            }

            RecordResult(method, path, result);
        }

        private void RecordResult(string method, string path, DevApiResult result)
        {
            lastStatusCode = result.statusCode;
            lastLatencyMs = result.latencyMs;
            lastResponseBody = result.body ?? string.Empty;
            lastError = string.IsNullOrWhiteSpace(result.error) ? "-" : result.error;
            lastMethodPath = $"{method} {path}";
            RecordHistory(method, path, result.statusCode, result.latencyMs, result.ok, string.IsNullOrWhiteSpace(result.error) ? "-" : result.error);
        }

        private void RecordHistory(string method, string path, long statusCode, long latencyMs, bool ok, string error)
        {
            history.Add(new HistoryRow
            {
                at = DateTime.Now.ToString("HH:mm:ss"),
                method = method,
                path = path,
                status = statusCode,
                latencyMs = latencyMs,
                ok = ok,
                error = string.IsNullOrWhiteSpace(error) ? "-" : error,
            });

            while (history.Count > Mathf.Max(5, maxHistory))
            {
                history.RemoveAt(0);
            }
        }

        private void PushUiError(string message)
        {
            var result = new DevApiResult
            {
                ok = false,
                statusCode = -1,
                latencyMs = 0,
                body = string.Empty,
                error = message,
            };
            RecordResult("LOCAL", "-", result);
        }

        private bool IsReplayBlocked()
        {
            if (runReplayer != null && runReplayer.IsReplaying)
            {
                return true;
            }

            return gatewayClient != null && gatewayClient.IsReplayMode;
        }

        private static string Truncate(string value, int maxChars)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return string.Empty;
            }

            var trimmed = value.Trim();
            var limit = Math.Max(64, maxChars);
            if (trimmed.Length <= limit)
            {
                return trimmed;
            }

            return trimmed.Substring(0, limit) + "...";
        }

        private static string NextPreset(string current, IReadOnlyList<string> options)
        {
            if (options == null || options.Count == 0)
            {
                return current;
            }

            var idx = 0;
            for (var i = 0; i < options.Count; i++)
            {
                if (string.Equals(current, options[i], StringComparison.OrdinalIgnoreCase))
                {
                    idx = i;
                    break;
                }
            }

            return options[(idx + 1) % options.Count];
        }

        private static JToken ParseValueToken(string raw)
        {
            if (bool.TryParse(raw, out var boolValue))
            {
                return boolValue;
            }
            if (long.TryParse(raw, out var longValue))
            {
                return longValue;
            }
            if (double.TryParse(raw, out var doubleValue))
            {
                return doubleValue;
            }

            return raw;
        }

        private static JObject BuildFaultPayload(string tool, string mode, JToken value, int durationMs)
        {
            var payload = new JObject
            {
                ["tool"] = tool,
                ["mode"] = mode,
                ["durationMs"] = durationMs,
            };
            if (value != null)
            {
                payload["value"] = value;
            }

            return payload;
        }

        private JObject BuildScenarioPayload(IReadOnlyList<Step> steps)
        {
            var stepArray = new JArray();
            if (steps != null)
            {
                for (var i = 0; i < steps.Count; i++)
                {
                    var step = steps[i];
                    stepArray.Add(new JObject
                    {
                        ["index"] = i,
                        ["method"] = step.method,
                        ["path"] = step.path,
                        ["payload"] = step.payload != null ? step.payload.DeepClone() : null,
                    });
                }
            }

            var payload = new JObject
            {
                ["intent"] = IntentOptions[Mathf.Clamp(intentIndex, 0, IntentOptions.Length - 1)],
                ["question"] = intentQuestion,
                ["faultPreset"] = new JObject
                {
                    ["tool"] = faultTool,
                    ["mode"] = faultMode,
                    ["value"] = faultValue,
                    ["durationMs"] = faultDurationMs,
                },
                ["steps"] = stepArray,
            };
            return payload;
        }

        private readonly struct Step
        {
            public Step(string method, string path, JObject payload)
            {
                this.method = method;
                this.path = path;
                this.payload = payload;
            }

            public readonly string method;
            public readonly string path;
            public readonly JObject payload;

            public static Step Post(string path, JObject payload)
            {
                return new Step("POST", path, payload);
            }

            public static Step Get(string path)
            {
                return new Step("GET", path, null);
            }
        }
    }
}
