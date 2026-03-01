using System;
using System.Collections;
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
        private Coroutine _selfTestRoutine;
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
            SetStatus("RUNNING", "step1 ping");
            ResolveRefs();
            if (_gatewayClient == null)
            {
                Fail("gateway-client missing");
                _selfTestRoutine = null;
                yield break;
            }

            if (_scanController == null)
            {
                Fail("scan-controller missing");
                _selfTestRoutine = null;
                yield break;
            }

            var pingOk = false;
            long pingRttMs = -1;
            string pingError = string.Empty;
            yield return PingOnce((ok, rttMs, error) =>
            {
                pingOk = ok;
                pingRttMs = rttMs;
                pingError = error;
            });
            if (!pingOk)
            {
                Fail($"/api/ping failed: {pingError}");
                _selfTestRoutine = null;
                yield break;
            }

            SetStatus("RUNNING", "step2 version");
            var versionOk = false;
            var versionText = string.Empty;
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
            if (!versionOk)
            {
                Fail($"/api/version failed: {versionText}");
                _selfTestRoutine = null;
                yield break;
            }

            SetStatus("RUNNING", "step3 mode");
            var modeOk = false;
            var modeValue = string.Empty;
            var modePath = $"/api/mode?deviceId={UnityWebRequest.EscapeURL(ByesFrameTelemetry.DeviceId)}";
            yield return GetJson(modePath, (ok, obj, error) =>
            {
                if (!ok || obj == null)
                {
                    modeOk = false;
                    modeValue = string.IsNullOrWhiteSpace(error) ? "request failed" : error;
                    return;
                }

                modeValue = (obj.Value<string>("mode") ?? string.Empty).Trim();
                modeOk = !string.IsNullOrWhiteSpace(modeValue);
                if (!modeOk)
                {
                    modeValue = "missing mode field";
                }
            });
            if (!modeOk)
            {
                Fail($"/api/mode failed: {modeValue}");
                _selfTestRoutine = null;
                yield break;
            }

            SetStatus("RUNNING", "step3b mode roundtrip");
            var modeRoundtripOk = false;
            var roundtripError = string.Empty;
            yield return VerifyModeRoundtrip((ok, error) =>
            {
                modeRoundtripOk = ok;
                roundtripError = error;
            });
            if (!modeRoundtripOk)
            {
                Fail($"mode roundtrip failed: {roundtripError}");
                _selfTestRoutine = null;
                yield break;
            }

            SetStatus("RUNNING", "step4 scan+ws");
            var uploadCompleted = false;
            var uploadSucceeded = false;
            var uploadError = string.Empty;
            var wsEventObserved = false;
            var stepStartedAt = Time.realtimeSinceStartup;

            void UploadHandler(ScanController.UploadMetrics metrics)
            {
                uploadCompleted = true;
                uploadSucceeded = metrics.Ok;
                uploadError = string.IsNullOrWhiteSpace(metrics.Error) ? string.Empty : metrics.Error.Trim();
            }

            void WsEventHandler(JObject _)
            {
                wsEventObserved = true;
            }

            _scanController.OnUploadFinished += UploadHandler;
            _gatewayClient.OnGatewayEvent += WsEventHandler;
            _scanController.ScanOnceFromUi();

            var timeoutSec = Mathf.Max(1f, scanWaitTimeoutSec);
            while (Time.realtimeSinceStartup - stepStartedAt < timeoutSec)
            {
                if (uploadCompleted && uploadSucceeded && wsEventObserved)
                {
                    break;
                }

                yield return null;
            }

            _scanController.OnUploadFinished -= UploadHandler;
            _gatewayClient.OnGatewayEvent -= WsEventHandler;

            if (!uploadCompleted)
            {
                Fail("scan upload timeout");
                _selfTestRoutine = null;
                yield break;
            }

            if (!uploadSucceeded)
            {
                Fail($"/api/frame failed: {uploadError}");
                _selfTestRoutine = null;
                yield break;
            }

            if (!wsEventObserved)
            {
                Fail("WS no events in 5s");
                _selfTestRoutine = null;
                yield break;
            }

            SetStatus("PASS", $"ping={pingRttMs}ms version={versionText} mode={modeValue} scan=ok ws=ok");
            if (verboseLogs)
            {
                Debug.Log($"[ByesQuest3SelfTestRunner] PASS {_summary}");
            }

            _selfTestRoutine = null;
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
                ["deviceId"] = ByesFrameTelemetry.DeviceId,
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
            var deviceId = ByesFrameTelemetry.DeviceId;
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
            var payload = new JObject
            {
                ["runId"] = "quest3-smoke",
                ["frameSeq"] = 1,
                ["mode"] = mode,
                ["source"] = "selftest",
                ["tsMs"] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                ["deviceId"] = deviceId,
            };
            yield return SendRequest(UnityWebRequest.kHttpVerbPOST, "/api/mode", payload, (ok, _, error) =>
            {
                onDone?.Invoke(ok, ok ? string.Empty : (string.IsNullOrWhiteSpace(error) ? "set mode failed" : error));
            });
        }

        private IEnumerator ValidateMode(string deviceId, string expectedMode, Action<bool, string> onDone)
        {
            var path = $"/api/mode?deviceId={UnityWebRequest.EscapeURL(deviceId)}";
            yield return GetJson(path, (ok, obj, error) =>
            {
                if (!ok || obj == null)
                {
                    onDone?.Invoke(false, string.IsNullOrWhiteSpace(error) ? "mode readback failed" : error);
                    return;
                }

                var actual = (obj.Value<string>("mode") ?? string.Empty).Trim().ToLowerInvariant();
                if (string.Equals(actual, expectedMode, StringComparison.Ordinal))
                {
                    onDone?.Invoke(true, string.Empty);
                    return;
                }

                onDone?.Invoke(false, $"expected {expectedMode}, got {actual}");
            });
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
        }

        private void SetStatus(string status, string summary)
        {
            _status = string.IsNullOrWhiteSpace(status) ? "UNKNOWN" : status.Trim().ToUpperInvariant();
            _summary = string.IsNullOrWhiteSpace(summary) ? "-" : summary.Trim();
        }
    }
}
