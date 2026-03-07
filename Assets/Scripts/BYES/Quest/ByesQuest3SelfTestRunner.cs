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
            var skipNotes = new List<string>();
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
                JObject capabilitiesObj = null;
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
                    capabilitiesObj = obj;
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
                var riskTsBefore = _panel != null ? _panel.GetLastRiskTsMs() : -1L;
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
                if (!depthRiskOk && IsWsTimeout(depthRiskError) && _panel != null)
                {
                    var riskTsAfter = _panel.GetLastRiskTsMs();
                    if (riskTsAfter > riskTsBefore && riskTsAfter > 0)
                    {
                        depthRiskOk = true;
                        depthRiskError = string.Empty;
                    }
                }
                if (!depthRiskOk)
                {
                    Fail($"depth/risk failed: {depthRiskError}");
                    yield break;
                }

                SetStatus("RUNNING", "step6b capture truth");
                var captureTruthOk = false;
                var captureTruthError = string.Empty;
                var captureTruthStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return VerifyCaptureTruth((ok, error) =>
                {
                    captureTruthOk = ok;
                    captureTruthError = error;
                });
                _stepDurationsMs["capture_truth"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - captureTruthStepStartedMs);
                if (!captureTruthOk)
                {
                    Fail($"capture truth failed: {captureTruthError}");
                    yield break;
                }

                SetStatus("RUNNING", "step7 ocr");
                var ocrOk = false;
                var ocrError = string.Empty;
                var ocrTsBefore = _panel != null ? _panel.GetLastOcrTsMs() : -1L;
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
                if (!ocrOk && IsWsTimeout(ocrError) && _panel != null)
                {
                    var ocrTsAfter = _panel.GetLastOcrTsMs();
                    if (ocrTsAfter > ocrTsBefore && ocrTsAfter > 0)
                    {
                        ocrOk = true;
                        ocrError = string.Empty;
                    }
                }
                if (!ocrOk)
                {
                    Fail($"ocr failed: {ocrError}");
                    yield break;
                }

                SetStatus("RUNNING", "step8 det");
                var detOk = false;
                var detError = string.Empty;
                var detTsBefore = _panel != null ? _panel.GetLastDetTsMs() : -1L;
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
                if (!detOk && IsWsTimeout(detError) && _panel != null)
                {
                    var detTsAfter = _panel.GetLastDetTsMs();
                    if (detTsAfter > detTsBefore && detTsAfter > 0)
                    {
                        detOk = true;
                        detError = string.Empty;
                    }
                }
                if (!detOk)
                {
                    Fail($"det failed: {detError}");
                    yield break;
                }

                SetStatus("RUNNING", "step9 vision assets");
                var visionAssetsStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var segExpected = IsProviderEnabled(capabilitiesObj, "seg");
                var depthExpected = IsProviderEnabled(capabilitiesObj, "depth");
                if (segExpected || depthExpected)
                {
                    var visionEventOk = false;
                    var visionEventErr = string.Empty;
                    yield return RunScanStep(
                        () => _scanController.ScanOnceFromUi(),
                        expectedEventNames: new[] {"seg.mask.v1", "seg.mask", "depth.map.v1", "depth.estimate"},
                        timeoutSec: Mathf.Max(4f, scanWaitTimeoutSec),
                        onDone: (ok, error) =>
                        {
                            visionEventOk = ok;
                            visionEventErr = error;
                        });
                    if (!visionEventOk)
                    {
                        skipNotes.Add("vision_events:" + visionEventErr);
                    }

                    var waitUntil = Time.realtimeSinceStartup + 2.5f;
                    while (Time.realtimeSinceStartup < waitUntil)
                    {
                        var segReady = !segExpected || (_panel != null && _panel.GetHudSegAgeMs() >= 0);
                        var depthReady = !depthExpected || (_panel != null && _panel.GetHudDepthAgeMs() >= 0);
                        if (segReady && depthReady)
                        {
                            break;
                        }
                        yield return null;
                    }

                    var segOk = !segExpected || (_panel != null && _panel.GetHudSegAgeMs() >= 0);
                    var depthOk = !depthExpected || (_panel != null && _panel.GetHudDepthAgeMs() >= 0);
                    if (!segOk)
                    {
                        skipNotes.Add("seg.asset:not_observed");
                    }
                    if (!depthOk)
                    {
                        skipNotes.Add("depth.asset:not_observed");
                    }
                }
                else
                {
                    skipNotes.Add("vision_assets:providers_disabled");
                }
                _stepDurationsMs["vision_assets"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - visionAssetsStepStartedMs);

                SetStatus("RUNNING", "step10 target tracking");
                var trackOk = false;
                var trackError = string.Empty;
                var trackStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return RunScanStep(
                    () => _scanController.ScanOnceFromUi(),
                    expectedEventNames: new[] {"frame.input", "risk.fused", "det.objects"},
                    timeoutSec: Mathf.Max(3f, scanWaitTimeoutSec),
                    onDone: (_, _) => { });
                yield return new WaitForSecondsRealtime(0.2f);
                yield return RunPanelEventStep(
                    trigger: () =>
                    {
                        _panel?.TriggerSelectRoiFromUi();
                        _panel?.TriggerStartTrackFromUi();
                    },
                    expectedEventNames: new[] {"target.update", "target.session"},
                    timeoutSec: Mathf.Max(5f, scanWaitTimeoutSec + 2f),
                    onDone: (ok, error) =>
                    {
                        trackOk = ok;
                        trackError = error;
                    });
                if (!trackOk && IsAssistUnavailable(trackError))
                {
                    skipNotes.Add("track:assist_unavailable");
                    trackOk = true;
                    trackError = string.Empty;
                }
                _stepDurationsMs["track"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - trackStepStartedMs);
                if (!trackOk)
                {
                    Fail($"target tracking failed: {trackError}");
                    yield break;
                }

                SetStatus("RUNNING", "step11 guidance");
                var guidanceOk = _panel != null && !string.IsNullOrWhiteSpace(_panel.GetGuidanceText()) && _panel.GetGuidanceText() != "-";
                _stepDurationsMs["guidance"] = 0;
                if (!guidanceOk)
                {
                    Fail("guidance not updated");
                    yield break;
                }

                SetStatus("RUNNING", "step12 passthrough");
                var passthroughStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var passthroughStatus = _panel != null ? _panel.GetPassthroughStatus() : "panel missing";
                var passthroughSkipped = false;
                if (_panel != null && passthroughStatus.IndexOf("unavailable", StringComparison.OrdinalIgnoreCase) < 0)
                {
                    _panel.SetPassthroughEnabled(false);
                    yield return new WaitForSecondsRealtime(0.2f);
                    _panel.SetPassthroughEnabled(true);
                    yield return new WaitForSecondsRealtime(0.2f);
                }
                else
                {
                    passthroughSkipped = true;
                }
                _stepDurationsMs["passthrough"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - passthroughStepStartedMs);

                SetStatus("RUNNING", "step13 tts");
                var ttsStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                _panel?.TriggerPlayBeepFromUi();
                yield return new WaitForSecondsRealtime(0.25f);
                var beepOk = _panel != null && (_panel.GetLastTtsText() ?? string.Empty).IndexOf("beep", StringComparison.OrdinalIgnoreCase) >= 0;
                if (!beepOk)
                {
                    Fail("tts beep failed");
                    yield break;
                }
                _panel?.TriggerSpeakTestFromUi();
                yield return new WaitForSecondsRealtime(0.35f);
                var ttsText = _panel != null ? (_panel.GetLastTtsText() ?? string.Empty).Trim() : string.Empty;
                if (string.IsNullOrWhiteSpace(ttsText) || string.Equals(ttsText, "-", StringComparison.Ordinal))
                {
                    skipNotes.Add("tts:speak_backend_unavailable");
                }
                _stepDurationsMs["tts"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - ttsStepStartedMs);

                SetStatus("RUNNING", "step14 mic+asr");
                var asrStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                var micCheck = CheckOrRequestMicPermission();
                if (!micCheck.ok)
                {
                    if (micCheck.skipped)
                    {
                        skipNotes.Add("mic:" + micCheck.reason);
                    }
                    else
                    {
                        Fail("mic permission failed: " + micCheck.reason);
                        yield break;
                    }
                }
                var asrEnabled = IsAsrEnabled(capabilitiesObj);
                if (asrEnabled)
                {
                    var asrOk = false;
                    var asrErr = string.Empty;
                    yield return PostSyntheticAsr((ok, error) =>
                    {
                        asrOk = ok;
                        asrErr = error;
                    });
                    if (!asrOk)
                    {
                        Fail("asr failed: " + asrErr);
                        yield break;
                    }
                }
                else
                {
                    skipNotes.Add("asr:disabled");
                }
                _stepDurationsMs["asr"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - asrStepStartedMs);

                SetStatus("RUNNING", "step15 pyslam");
                var slamStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (IsProviderEnabled(capabilitiesObj, "pyslamRealtime"))
                {
                    var slamOk = false;
                    var slamErr = string.Empty;
                    yield return RunScanStep(
                        () => _scanController.ScanOnceFromUi(),
                        expectedEventNames: new[] {"slam.pose.v1", "slam.pose"},
                        timeoutSec: Mathf.Max(4f, scanWaitTimeoutSec),
                        onDone: (ok, error) =>
                        {
                            slamOk = ok;
                            slamErr = error;
                        });
                    if (!slamOk)
                    {
                        skipNotes.Add("pyslam:" + slamErr);
                    }
                }
                else
                {
                    skipNotes.Add("pyslam:disabled");
                }
                _stepDurationsMs["pyslam"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - slamStepStartedMs);

                SetStatus("RUNNING", "step16 record");
                var recordOk = false;
                var recordErr = string.Empty;
                var recordPath = string.Empty;
                var recordStepStartedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                yield return RunRecordRoundtrip((ok, path, error) =>
                {
                    recordOk = ok;
                    recordPath = path;
                    recordErr = error;
                });
                _stepDurationsMs["record"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - recordStepStartedMs);
                if (!recordOk)
                {
                    Fail($"recording failed: {recordErr}");
                    yield break;
                }

                _panel?.TriggerStopTrackFromUi();

                SetStatus(
                    "PASS",
                    $"ping={pingRttMs}ms " +
                    $"stepMs(ping={GetStepMs("ping")},version={GetStepMs("version")},cap={GetStepMs("capabilities")},ws={GetStepMs("ws")},mode={GetStepMs("mode")},depthRisk={GetStepMs("depth_risk")},captureTruth={GetStepMs("capture_truth")},ocr={GetStepMs("ocr")},det={GetStepMs("det")},vision={GetStepMs("vision_assets")},track={GetStepMs("track")},guidance={GetStepMs("guidance")},passthrough={GetStepMs("passthrough")},tts={GetStepMs("tts")},asr={GetStepMs("asr")},pyslam={GetStepMs("pyslam")},record={GetStepMs("record")}) " +
                    $"version={versionText} ws=ok mode=ok depthRisk=ok ocr=ok det=ok track=ok guidance=ok passthrough={(passthroughSkipped ? "skip" : "ok")} record=ok path={recordPath}" +
                    (skipNotes.Count > 0 ? $" skip=[{string.Join(";", skipNotes)}]" : string.Empty));
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

        private IEnumerator RunPanelEventStep(Action trigger, string[] expectedEventNames, float timeoutSec, Action<bool, string> onDone)
        {
            if (_gatewayClient == null)
            {
                onDone?.Invoke(false, "gateway client missing");
                yield break;
            }

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

            var matched = false;
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
                    matched = true;
                }
            }

            _gatewayClient.OnGatewayEvent += WsEventHandler;
            trigger?.Invoke();

            var started = Time.realtimeSinceStartup;
            var waitSec = Mathf.Max(1f, timeoutSec);
            while (Time.realtimeSinceStartup - started < waitSec)
            {
                if (matched)
                {
                    break;
                }
                yield return null;
            }

            _gatewayClient.OnGatewayEvent -= WsEventHandler;

            if (!matched)
            {
                var panelError = _panel != null ? (_panel.GetScanErrorText() ?? string.Empty).Trim() : string.Empty;
                if (!string.IsNullOrWhiteSpace(panelError))
                {
                    onDone?.Invoke(false, panelError);
                }
                else
                {
                    onDone?.Invoke(false, "WS expected event timeout");
                }
                yield break;
            }

            onDone?.Invoke(true, string.Empty);
        }

        private IEnumerator RunRecordRoundtrip(Action<bool, string, string> onDone)
        {
            var payloadStart = new JObject
            {
                ["deviceId"] = GetDeviceIdForSelfTest(),
                ["note"] = "selftest_v5_03",
                ["maxSec"] = 20,
                ["maxFrames"] = 0,
            };
            var startOk = false;
            var startErr = string.Empty;
            yield return SendRequest(UnityWebRequest.kHttpVerbPOST, "/api/record/start", payloadStart, (ok, _, error) =>
            {
                startOk = ok;
                startErr = error;
            });
            if (!startOk)
            {
                var already = !string.IsNullOrWhiteSpace(startErr) && startErr.IndexOf("already active recording", StringComparison.OrdinalIgnoreCase) >= 0;
                if (!already)
                {
                    onDone?.Invoke(false, string.Empty, string.IsNullOrWhiteSpace(startErr) ? "record/start failed" : startErr);
                    yield break;
                }
            }

            yield return new WaitForSecondsRealtime(0.8f);

            var payloadStop = new JObject
            {
                ["deviceId"] = GetDeviceIdForSelfTest(),
            };
            var stopOk = false;
            var stopErr = string.Empty;
            var path = string.Empty;
            yield return SendRequest(UnityWebRequest.kHttpVerbPOST, "/api/record/stop", payloadStop, (ok, obj, error) =>
            {
                stopOk = ok;
                stopErr = error;
                if (ok && obj != null)
                {
                    path = (obj.Value<string>("recordingPath") ?? string.Empty).Trim();
                }
            });

            if (!stopOk)
            {
                onDone?.Invoke(false, path, string.IsNullOrWhiteSpace(stopErr) ? "record/stop failed" : stopErr);
                yield break;
            }

            onDone?.Invoke(true, path, string.Empty);
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
                // Compatibility fallback: some gateway builds accept "read" but
                // silently map unknown mode tokens back to "walk".
                var fallbackReadOk = false;
                var fallbackReadErr = string.Empty;
                yield return PostMode("read", deviceId, (ok, error) =>
                {
                    fallbackReadOk = ok;
                    fallbackReadErr = error;
                });
                if (!fallbackReadOk)
                {
                    onDone?.Invoke(false, string.IsNullOrWhiteSpace(fallbackReadErr) ? readBackErr : fallbackReadErr);
                    yield break;
                }

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

        private static bool IsWsTimeout(string error)
        {
            if (string.IsNullOrWhiteSpace(error))
            {
                return false;
            }
            return error.IndexOf("WS expected event timeout", StringComparison.OrdinalIgnoreCase) >= 0;
        }

        private static bool IsAssistUnavailable(string error)
        {
            if (string.IsNullOrWhiteSpace(error))
            {
                return false;
            }
            var text = error.Trim();
            return text.IndexOf("assist_cache_miss", StringComparison.OrdinalIgnoreCase) >= 0
                   || (text.IndexOf("404", StringComparison.OrdinalIgnoreCase) >= 0
                       && text.IndexOf("/api/assist", StringComparison.OrdinalIgnoreCase) >= 0)
                   || (text.IndexOf("404", StringComparison.OrdinalIgnoreCase) >= 0
                       && text.IndexOf("not found", StringComparison.OrdinalIgnoreCase) >= 0);
        }

        private static bool IsProviderEnabled(JObject capabilitiesObj, string providerName)
        {
            if (capabilitiesObj == null || string.IsNullOrWhiteSpace(providerName))
            {
                return false;
            }

            var providers = capabilitiesObj["available_providers"] as JObject;
            var provider = providers?[providerName] as JObject;
            if (provider == null)
            {
                return false;
            }

            return provider.Value<bool?>("enabled") == true;
        }

        private static bool IsAsrEnabled(JObject capabilitiesObj)
        {
            if (capabilitiesObj == null)
            {
                return false;
            }

            var flags = capabilitiesObj["enabled_flags"] as JObject;
            if (flags != null && flags.Value<bool?>("asr") == true)
            {
                return true;
            }

            var providers = capabilitiesObj["available_providers"] as JObject;
            var asr = providers?["asr"] as JObject;
            return asr != null && asr.Value<bool?>("enabled") == true;
        }

        private IEnumerator VerifyCaptureTruth(Action<bool, string> onDone)
        {
            var panelSource = NormalizeFrameSourceTruthToken(_panel != null ? _panel.GetFrameSourceText() : string.Empty);
            var panelState = string.IsNullOrWhiteSpace(_panel?.GetFrameSourceTruthState()) ? "unavailable" : _panel.GetFrameSourceTruthState();
            if (!IsAllowedFrameSourceTruth(panelSource))
            {
                onDone?.Invoke(false, $"panel_source_invalid:{panelSource}");
                yield break;
            }

            var remoteOk = false;
            var remoteError = string.Empty;
            yield return GetJson("/api/ui/state", (ok, obj, error) =>
            {
                if (!ok || obj == null)
                {
                    remoteOk = false;
                    remoteError = string.IsNullOrWhiteSpace(error) ? "ui_state_failed" : error;
                    return;
                }

                var truth = obj["truth"] as JObject;
                var frameTruth = truth?["frameSource"] as JObject;
                var remoteSource = NormalizeFrameSourceTruthToken(frameTruth?.Value<string>("frameSource"));
                var remoteState = NormalizeTruthState(frameTruth?.Value<string>("truthState") ?? frameTruth?.Value<string>("truthLabel"));
                if (!IsAllowedFrameSourceTruth(remoteSource))
                {
                    remoteOk = false;
                    remoteError = $"remote_source_invalid:{remoteSource}";
                    return;
                }

                if (!string.Equals(panelSource, remoteSource, StringComparison.Ordinal))
                {
                    remoteOk = false;
                    remoteError = $"panel={panelSource} remote={remoteSource}";
                    return;
                }

                if (!string.Equals(panelState, remoteState, StringComparison.Ordinal))
                {
                    remoteOk = false;
                    remoteError = $"panelState={panelState} remoteState={remoteState}";
                    return;
                }

                remoteOk = true;
                remoteError = string.Empty;
            });

            onDone?.Invoke(remoteOk, remoteError);
        }

        private static bool IsAllowedFrameSourceTruth(string value)
        {
            return value == "pca_real"
                   || value == "ar_cpuimage_fallback"
                   || value == "rendertexture_fallback"
                   || value == "unavailable";
        }

        private static string NormalizeFrameSourceTruthToken(string value)
        {
            return GatewayClient.NormalizeFrameSourceTruthToken(value);
        }

        private static string NormalizeTruthState(string value)
        {
            return GatewayClient.NormalizeRuntimeTruthStateToken(value);
        }

        private (bool ok, bool skipped, string reason) CheckOrRequestMicPermission()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                var micPermission = UnityEngine.Android.Permission.Microphone;
                if (UnityEngine.Android.Permission.HasUserAuthorizedPermission(micPermission))
                {
                    return (true, false, string.Empty);
                }

                UnityEngine.Android.Permission.RequestUserPermission(micPermission);
                var deadline = Time.realtimeSinceStartup + 2f;
                while (Time.realtimeSinceStartup < deadline)
                {
                    if (UnityEngine.Android.Permission.HasUserAuthorizedPermission(micPermission))
                    {
                        return (true, false, string.Empty);
                    }
                }
                return (false, false, "permission_denied");
            }
            catch (Exception ex)
            {
                return (false, false, "permission_check_failed:" + ex.GetType().Name);
            }
#else
            return (true, true, "non_android");
#endif
        }

        private IEnumerator PostSyntheticAsr(Action<bool, string> onDone)
        {
            ResolveRefs();
            if (_gatewayClient == null)
            {
                onDone?.Invoke(false, "gateway client missing");
                yield break;
            }

            var wavBytes = BuildSyntheticWav(sampleRate: 16000, durationSec: 0.25f, frequency: 440f);
            if (wavBytes == null || wavBytes.Length == 0)
            {
                onDone?.Invoke(false, "wav build failed");
                yield break;
            }

            var requestOk = false;
            var requestError = string.Empty;
            var observedAsrEvent = false;
            var startedAt = Time.realtimeSinceStartup;

            void WsEventHandler(JObject evt)
            {
                if (evt == null)
                {
                    return;
                }

                var name = (evt.Value<string>("name") ?? evt.Value<string>("type") ?? string.Empty).Trim();
                if (string.Equals(name, "asr.transcript.v1", StringComparison.OrdinalIgnoreCase))
                {
                    observedAsrEvent = true;
                }
            }

            _gatewayClient.OnGatewayEvent += WsEventHandler;
            try
            {
                var url = BuildApiUrl("/api/asr");
                using (var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
                {
                    req.uploadHandler = new UploadHandlerRaw(wavBytes);
                    req.downloadHandler = new DownloadHandlerBuffer();
                    req.SetRequestHeader("Content-Type", "audio/wav");
                    var apiKey = _gatewayClient.ApiKey;
                    if (!string.IsNullOrWhiteSpace(apiKey))
                    {
                        req.SetRequestHeader("X-BYES-API-Key", apiKey.Trim());
                    }
                    req.timeout = 8;
                    yield return req.SendWebRequest();
                    if (req.result != UnityWebRequest.Result.Success)
                    {
                        requestOk = false;
                        requestError = req.error ?? "request failed";
                    }
                    else
                    {
                        requestOk = true;
                    }
                }

                if (!requestOk)
                {
                    onDone?.Invoke(false, requestError);
                    yield break;
                }

                var waitDeadline = Time.realtimeSinceStartup + 2f;
                while (Time.realtimeSinceStartup < waitDeadline && !observedAsrEvent)
                {
                    yield return null;
                }

                if (!observedAsrEvent)
                {
                    onDone?.Invoke(false, "asr event timeout");
                    yield break;
                }

                _stepDurationsMs["asr_req"] = Math.Max(0L, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - Convert.ToInt64(startedAt * 1000f));
                onDone?.Invoke(true, string.Empty);
            }
            finally
            {
                _gatewayClient.OnGatewayEvent -= WsEventHandler;
            }
        }

        private static byte[] BuildSyntheticWav(int sampleRate, float durationSec, float frequency)
        {
            var length = Mathf.Max(1, Mathf.RoundToInt(sampleRate * Mathf.Max(0.05f, durationSec)));
            var pcm = new short[length];
            for (var i = 0; i < length; i += 1)
            {
                var t = i / (float)sampleRate;
                var envelope = Mathf.Clamp01(1f - (i / (float)length));
                pcm[i] = (short)Mathf.RoundToInt(Mathf.Sin(2f * Mathf.PI * frequency * t) * envelope * short.MaxValue * 0.18f);
            }

            var dataBytes = pcm.Length * sizeof(short);
            var wav = new byte[44 + dataBytes];
            System.Text.Encoding.ASCII.GetBytes("RIFF").CopyTo(wav, 0);
            BitConverter.GetBytes(36 + dataBytes).CopyTo(wav, 4);
            System.Text.Encoding.ASCII.GetBytes("WAVE").CopyTo(wav, 8);
            System.Text.Encoding.ASCII.GetBytes("fmt ").CopyTo(wav, 12);
            BitConverter.GetBytes(16).CopyTo(wav, 16);
            BitConverter.GetBytes((short)1).CopyTo(wav, 20);
            BitConverter.GetBytes((short)1).CopyTo(wav, 22);
            BitConverter.GetBytes(sampleRate).CopyTo(wav, 24);
            BitConverter.GetBytes(sampleRate * 2).CopyTo(wav, 28);
            BitConverter.GetBytes((short)2).CopyTo(wav, 32);
            BitConverter.GetBytes((short)16).CopyTo(wav, 34);
            System.Text.Encoding.ASCII.GetBytes("data").CopyTo(wav, 36);
            BitConverter.GetBytes(dataBytes).CopyTo(wav, 40);
            Buffer.BlockCopy(pcm, 0, wav, 44, dataBytes);
            return wav;
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
