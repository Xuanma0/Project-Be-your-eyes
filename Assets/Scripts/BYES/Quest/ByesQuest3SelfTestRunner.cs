using System;
using System.Collections;
using System.Collections.Generic;
using BYES.Telemetry;
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
        [SerializeField] private bool autoRunOnStart = true;
        [SerializeField] private float startupDelaySec = 1.2f;
        [SerializeField] private float scanWaitTimeoutSec = 5f;
        [SerializeField] private bool verboseLogs = true;

        private GatewayClient _gatewayClient;
        private ScanController _scanController;
        private ByesQuest3ConnectionPanelMinimal _panel;
        private Coroutine _selfTestRoutine;
        private readonly Dictionary<string, long> _stepDurationsMs = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        private string _status = "IDLE";
        private string _summary = "-";

        public string CurrentStatus => _status;
        public string CurrentSummary => _summary;

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

        private void Start()
        {
            if (autoRunOnStart)
            {
                StartCoroutine(DelayedAutoRun());
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

        private IEnumerator DelayedAutoRun()
        {
            yield return new WaitForSecondsRealtime(Mathf.Max(0.1f, startupDelaySec));
            StartSelfTest();
        }

        private IEnumerator RunSelfTestRoutine()
        {
            _stepDurationsMs.Clear();
            var restoreLiveAfterTest = false;
            try
            {
                SetStatus("RUNNING", "step1 ping");
                ResolveRefs();
                if (_gatewayClient == null)
                {
                    Fail("gateway-client missing");
                    yield break;
                }

                if (_scanController == null)
                {
                    Fail("scan-controller missing");
                    yield break;
                }

                if (_scanController.IsLiveEnabled)
                {
                    _scanController.SetLiveEnabled(false);
                    restoreLiveAfterTest = true;
                    yield return new WaitForSecondsRealtime(0.2f);
                }

                var pingOk = false;
                long pingRttMs = -1;
                string pingError = string.Empty;
                var pingStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return PingOnce((ok, rttMs, error) =>
                {
                    pingOk = ok;
                    pingRttMs = rttMs;
                    pingError = error;
                });
                _stepDurationsMs["ping"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - pingStepStartedMs);
                if (!pingOk)
                {
                    Fail($"/api/ping failed: {pingError}");
                    yield break;
                }

                SetStatus("RUNNING", "step2 version");
                var versionOk = false;
                var versionText = string.Empty;
                var versionStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return GetJson("/api/version", (ok, obj, error) =>
                {
                    if (!ok || obj == null)
                    {
                        versionOk = false;
                        versionText = string.IsNullOrWhiteSpace(error) ? "request failed" : error;
                        return;
                    }

                    versionText = (obj.Value<string>("version") ?? string.Empty).Trim();
                    versionOk = !string.IsNullOrWhiteSpace(versionText);
                    if (!versionOk)
                    {
                        versionText = "missing version field";
                    }
                });
                _stepDurationsMs["version"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - versionStepStartedMs);
                if (!versionOk)
                {
                    Fail($"/api/version failed: {versionText}");
                    yield break;
                }

                SetStatus("RUNNING", "step3 capabilities");
                var capabilitiesOk = false;
                var capabilitiesText = string.Empty;
                var capabilitiesStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return GetJson("/api/capabilities", (ok, obj, error) =>
                {
                    if (!ok || obj == null)
                    {
                        var normalizedError = string.IsNullOrWhiteSpace(error) ? "request failed" : error;
                        // Backward compatibility: older gateway builds may not expose /api/capabilities.
                        // Treat 404 as non-fatal and continue with the remaining functional checks.
                        if (normalizedError.IndexOf("404", StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            capabilitiesOk = true;
                            capabilitiesText = "legacy gateway (no /api/capabilities)";
                            return;
                        }

                        capabilitiesOk = false;
                        capabilitiesText = normalizedError;
                        return;
                    }

                    var providers = obj["available_providers"] as JObject;
                    capabilitiesText = providers != null ? providers.ToString(Newtonsoft.Json.Formatting.None) : "available_providers missing";
                    capabilitiesOk = providers != null;
                });
                _stepDurationsMs["capabilities"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - capabilitiesStepStartedMs);
                if (!capabilitiesOk)
                {
                    Fail($"/api/capabilities failed: {capabilitiesText}");
                    yield break;
                }

                SetStatus("RUNNING", "step4 ws connect");
                var wsConnected = false;
                var wsStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var wsDeadline = Time.realtimeSinceStartup + 5f;
                while (Time.realtimeSinceStartup < wsDeadline)
                {
                    if (_gatewayClient != null && _gatewayClient.IsConnected)
                    {
                        wsConnected = true;
                        break;
                    }
                    yield return null;
                }
                _stepDurationsMs["ws"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - wsStepStartedMs);
                if (!wsConnected)
                {
                    Fail("WS not connected");
                    yield break;
                }

                SetStatus("RUNNING", "step5 mode roundtrip");
                var modeRoundtripOk = false;
                var roundtripError = string.Empty;
                var modeStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return VerifyModeRoundtrip((ok, error) =>
                {
                    modeRoundtripOk = ok;
                    roundtripError = error;
                });
                _stepDurationsMs["mode"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - modeStepStartedMs);
                if (!modeRoundtripOk)
                {
                    Fail($"mode roundtrip failed: {roundtripError}");
                    yield break;
                }

                SetStatus("RUNNING", "step6 depth+risk");
                var depthRiskOk = false;
                var depthRiskError = string.Empty;
                var depthRiskStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return RunScanStep(
                    () => _scanController.DepthRiskOnceFromUi(),
                    expectedEventNames: new[] {"risk.fused", "risk.hazards", "depth.estimate"},
                    timeoutSec: Mathf.Max(3f, scanWaitTimeoutSec),
                    onDone: (ok, error) =>
                    {
                        depthRiskOk = ok;
                        depthRiskError = error;
                    });
                _stepDurationsMs["depth_risk"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - depthRiskStepStartedMs);
                if (!depthRiskOk)
                {
                    Fail($"depth/risk failed: {depthRiskError}");
                    yield break;
                }

                SetStatus("RUNNING", "step7 ocr");
                var ocrOk = false;
                var ocrError = string.Empty;
                var ocrStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return RunScanStep(
                    () => _scanController.ReadTextOnceFromUi(),
                    expectedEventNames: new[] {"ocr.read", "ocr"},
                    timeoutSec: Mathf.Max(5f, scanWaitTimeoutSec + 3f),
                    onDone: (ok, error) =>
                    {
                        ocrOk = ok;
                        ocrError = error;
                    });
                _stepDurationsMs["ocr"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - ocrStepStartedMs);
                if (!ocrOk)
                {
                    Fail($"ocr failed: {ocrError}");
                    yield break;
                }

                SetStatus("RUNNING", "step8 det");
                var detOk = false;
                var detError = string.Empty;
                var detStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return RunScanStep(
                    () => _scanController.DetectObjectsOnceFromUi(),
                    expectedEventNames: new[] {"det.objects", "det"},
                    timeoutSec: Mathf.Max(5f, scanWaitTimeoutSec + 3f),
                    onDone: (ok, error) =>
                    {
                        detOk = ok;
                        detError = error;
                    });
                _stepDurationsMs["det"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - detStepStartedMs);
                if (!detOk)
                {
                    Fail($"det failed: {detError}");
                    yield break;
                }

                SetStatus(
                    "PASS",
                    $"ping={pingRttMs}ms " +
                    $"stepMs(ping={GetStepMs("ping")},version={GetStepMs("version")},cap={GetStepMs("capabilities")},ws={GetStepMs("ws")},mode={GetStepMs("mode")},depthRisk={GetStepMs("depth_risk")},ocr={GetStepMs("ocr")},det={GetStepMs("det")}) " +
                    $"version={versionText} ws=ok mode=ok depthRisk=ok ocr=ok det=ok");
                if (verboseLogs)
                {
                    Debug.Log($"[ByesQuest3SelfTestRunner] PASS {_summary}");
                }
            }
            finally
            {
                if (restoreLiveAfterTest && _scanController != null)
                {
                    _scanController.SetLiveEnabled(true);
                }
                _selfTestRoutine = null;
            }
        }

        private IEnumerator RunScanStep(Action trigger, string[] expectedEventNames, float timeoutSec, Action<bool, string> onDone)
        {
            var uploadCompleted = false;
            var uploadSucceeded = false;
            var uploadError = string.Empty;
            var matchedEventObserved = false;
            var stepStartedAt = Time.realtimeSinceStartup;

            var expected = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (expectedEventNames != null)
            {
                for (var i = 0; i < expectedEventNames.Length; i += 1)
                {
                    var token = (expectedEventNames[i] ?? string.Empty).Trim();
                    if (!string.IsNullOrWhiteSpace(token))
                    {
                        expected.Add(token);
                    }
                }
            }

            void UploadHandler(ScanController.UploadMetrics metrics)
            {
                uploadCompleted = true;
                uploadSucceeded = metrics.Ok;
                uploadError = string.IsNullOrWhiteSpace(metrics.Error) ? string.Empty : metrics.Error.Trim();
            }

            void WsEventHandler(JObject evt)
            {
                if (evt == null)
                {
                    return;
                }

                var name = (evt.Value<string>("name") ?? evt.Value<string>("type") ?? string.Empty).Trim();
                if (string.IsNullOrWhiteSpace(name))
                {
                    return;
                }

                if (expected.Count == 0 || expected.Contains(name))
                {
                    matchedEventObserved = true;
                }
            }

            _scanController.OnUploadFinished += UploadHandler;
            _gatewayClient.OnGatewayEvent += WsEventHandler;
            trigger?.Invoke();

            var resolvedTimeout = Mathf.Max(1f, timeoutSec);
            while (Time.realtimeSinceStartup - stepStartedAt < resolvedTimeout)
            {
                if (uploadCompleted && uploadSucceeded && matchedEventObserved)
                {
                    break;
                }
                yield return null;
            }

            _scanController.OnUploadFinished -= UploadHandler;
            _gatewayClient.OnGatewayEvent -= WsEventHandler;

            if (!uploadCompleted)
            {
                onDone?.Invoke(false, "scan upload timeout");
                yield break;
            }
            if (!uploadSucceeded)
            {
                onDone?.Invoke(false, string.IsNullOrWhiteSpace(uploadError) ? "/api/frame failed" : uploadError);
                yield break;
            }
            if (!matchedEventObserved)
            {
                onDone?.Invoke(false, "WS expected event timeout");
                yield break;
            }

            onDone?.Invoke(true, string.Empty);
        }

        private void Fail(string reason)
        {
            SetStatus("FAIL", reason);
            if (verboseLogs)
            {
                Debug.LogWarning($"[ByesQuest3SelfTestRunner] FAIL {_summary}");
            }
        }

        private IEnumerator PingOnce(Action<bool, long, string> onDone)
        {
            var payload = new JObject
            {
                ["deviceId"] = GetDeviceIdForSelfTest(),
                ["seq"] = 1,
                ["clientSendTsMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
            };
            var startedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            yield return SendRequest(
                UnityWebRequest.kHttpVerbPOST,
                "/api/ping",
                payload,
                (ok, response, error) =>
                {
                    if (!ok || response == null)
                    {
                        onDone?.Invoke(false, -1, string.IsNullOrWhiteSpace(error) ? "request failed" : error);
                        return;
                    }

                    var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    var rtt = Math.Max(0L, nowMs - startedAtMs);
                    onDone?.Invoke(true, rtt, string.Empty);
                });
        }

        private IEnumerator GetJson(string path, Action<bool, JObject, string> onDone)
        {
            yield return SendRequest(UnityWebRequest.kHttpVerbGET, path, null, onDone);
        }

        private IEnumerator VerifyModeRoundtrip(Action<bool, string> onDone)
        {
            var deviceId = GetDeviceIdForSelfTest();
            var readOk = false;
            var readErr = string.Empty;
            yield return PostMode("read_text", deviceId, (ok, error) =>
            {
                readOk = ok;
                readErr = error;
            });
            if (!readOk)
            {
                onDone?.Invoke(false, readErr);
                yield break;
            }

            var readBackOk = false;
            var readBackErr = string.Empty;
            yield return ValidateMode(deviceId, "read_text", (ok, error) =>
            {
                readBackOk = ok;
                readBackErr = error;
            });
            if (!readBackOk)
            {
                onDone?.Invoke(false, readBackErr);
                yield break;
            }

            var walkOk = false;
            var walkErr = string.Empty;
            yield return PostMode("walk", deviceId, (ok, error) =>
            {
                walkOk = ok;
                walkErr = error;
            });
            if (!walkOk)
            {
                onDone?.Invoke(false, walkErr);
                yield break;
            }

            var walkBackOk = false;
            var walkBackErr = string.Empty;
            yield return ValidateMode(deviceId, "walk", (ok, error) =>
            {
                walkBackOk = ok;
                walkBackErr = error;
            });
            onDone?.Invoke(walkBackOk, walkBackOk ? string.Empty : walkBackErr);
        }

        private IEnumerator PostMode(string mode, string deviceId, Action<bool, string> onDone)
        {
            var requestOk = false;
            var requestError = string.Empty;
            var payload = new JObject
            {
                ["runId"] = "quest3-smoke",
                ["frameSeq"] = 1,
                ["mode"] = mode,
                ["source"] = "xr",
                ["tsMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["deviceId"] = deviceId,
            };
            yield return SendRequest(UnityWebRequest.kHttpVerbPOST, "/api/mode", payload, (ok, _, error) =>
            {
                requestOk = ok;
                requestError = ok ? string.Empty : (string.IsNullOrWhiteSpace(error) ? "set mode failed" : error);
            });

            if (requestOk)
            {
                onDone?.Invoke(true, string.Empty);
                yield break;
            }

            // Backward compatibility: some builds still use "read" instead of "read_text".
            if (string.Equals(mode, "read_text", StringComparison.OrdinalIgnoreCase))
            {
                var accepted = false;
                var failure = string.Empty;
                yield return SendRequest(UnityWebRequest.kHttpVerbPOST, "/api/mode", new JObject
                {
                    ["runId"] = "quest3-smoke",
                    ["frameSeq"] = 1,
                    ["mode"] = "read",
                    ["source"] = "xr",
                    ["tsMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                    ["deviceId"] = deviceId,
                }, (ok, _, error) =>
                {
                    accepted = ok;
                    failure = error;
                });

                if (accepted)
                {
                    onDone?.Invoke(true, string.Empty);
                    yield break;
                }

                onDone?.Invoke(false, string.IsNullOrWhiteSpace(failure) ? requestError : failure);
                yield break;
            }

            onDone?.Invoke(false, requestError);
        }

        private IEnumerator ValidateMode(string deviceId, string expectedMode, Action<bool, string> onDone)
        {
            var retries = 5;
            string lastError = "mode readback failed";
            for (var attempt = 0; attempt < retries; attempt += 1)
            {
                var done = false;
                var success = false;
                var path = $"/api/mode?deviceId={UnityWebRequest.EscapeURL(deviceId)}";
                yield return GetJson(path, (ok, obj, error) =>
                {
                    done = true;
                    if (!ok || obj == null)
                    {
                        lastError = string.IsNullOrWhiteSpace(error) ? "mode readback failed" : error;
                        return;
                    }

                    var actual = NormalizeModeToken(obj.Value<string>("mode"));
                    if (string.Equals(actual, expectedMode, StringComparison.Ordinal))
                    {
                        success = true;
                        return;
                    }

                    lastError = $"expected {expectedMode}, got {actual}";
                });

                if (done && success)
                {
                    onDone?.Invoke(true, string.Empty);
                    yield break;
                }

                // Compatibility fallback: some gateway builds still store mode in default bucket
                // and ignore device-specific key on readback.
                var globalDone = false;
                var globalSuccess = false;
                yield return GetJson("/api/mode", (ok, obj, error) =>
                {
                    globalDone = true;
                    if (!ok || obj == null)
                    {
                        if (!string.IsNullOrWhiteSpace(error))
                        {
                            lastError = error;
                        }
                        return;
                    }

                    var globalMode = NormalizeModeToken(obj.Value<string>("mode"));
                    if (string.Equals(globalMode, expectedMode, StringComparison.Ordinal))
                    {
                        globalSuccess = true;
                        return;
                    }

                    lastError = $"expected {expectedMode}, got {globalMode}";
                });

                if (globalDone && globalSuccess)
                {
                    onDone?.Invoke(true, string.Empty);
                    yield break;
                }

                yield return new WaitForSecondsRealtime(0.2f);
            }

            onDone?.Invoke(false, lastError);
        }

        private static string NormalizeModeToken(string mode)
        {
            var normalized = string.IsNullOrWhiteSpace(mode) ? "walk" : mode.Trim().ToLowerInvariant();
            if (string.Equals(normalized, "read", StringComparison.Ordinal))
            {
                return "read_text";
            }

            return normalized;
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

            if (_scanController == null)
            {
                _scanController = FindFirstObjectByType<ScanController>();
            }

            if (_panel == null)
            {
                _panel = FindFirstObjectByType<ByesQuest3ConnectionPanelMinimal>();
            }
        }

        private string GetDeviceIdForSelfTest()
        {
            ResolveRefs();
            var fromPanel = _panel != null ? (_panel.GetDeviceId() ?? string.Empty).Trim() : string.Empty;
            if (!string.IsNullOrWhiteSpace(fromPanel))
            {
                return fromPanel;
            }

            var fromTelemetry = (ByesFrameTelemetry.DeviceId ?? string.Empty).Trim();
            if (!string.IsNullOrWhiteSpace(fromTelemetry))
            {
                return fromTelemetry;
            }

            return "quest3-selftest";
        }

        private void SetStatus(string status, string summary)
        {
            _status = string.IsNullOrWhiteSpace(status) ? "UNKNOWN" : status.Trim().ToUpperInvariant();
            _summary = string.IsNullOrWhiteSpace(summary) ? "-" : summary.Trim();
        }

        private long GetStepMs(string key)
        {
            return _stepDurationsMs.TryGetValue(key, out var value) ? value : -1L;
        }
    }
}
