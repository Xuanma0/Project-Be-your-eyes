using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using BYES.Core;
using BYES.Telemetry;

namespace BYES.Plan
{
    public class PlanClient : MonoBehaviour
    {
        [Header("Gateway")]
        public string GatewayBaseUrl = "http://127.0.0.1:8000";
        public string RunPackage = "Gateway/tests/fixtures/run_package_with_risk_gt_and_pov_min";
        public int FrameSeq = 1;

        [Header("Flow")]
        public bool AutoRunOnStart = false;
        public bool ExecuteAfterPlan = true;

        [Header("References")]
        public PlanExecutor Executor;
        public ActionPlanExecutor ActionExecutor;

        private string _lastPlanJson = string.Empty;
        private string _lastRunId = string.Empty;
        private int _lastFrameSeq = 1;

        [Serializable]
        private class PlanBudget
        {
            public int maxChars = 2000;
            public int maxTokensApprox = 256;
            public string mode = "decisions_plus_highlights";
        }

        [Serializable]
        private class PlanConstraints
        {
            public bool allowConfirm = true;
            public bool allowHaptic = false;
            public int maxActions = 3;
        }

        [Serializable]
        private class PlanGenerateRequest
        {
            public string runPackage;
            public int frameSeq;
            public PlanBudget budget = new PlanBudget();
            public PlanConstraints constraints = new PlanConstraints();
        }

        [Serializable]
        private class ActionPlanHeader
        {
            public string runId;
            public int frameSeq;
        }

        [Serializable]
        private class ConfirmResponseRequest
        {
            public string runId;
            public int frameSeq;
            public string confirmId;
            public bool accepted;
            public string runPackage;
        }

        private void Start()
        {
            if (Executor == null)
            {
                Executor = GetComponent<PlanExecutor>();
            }
            if (ActionExecutor == null)
            {
                ActionExecutor = GetComponent<ActionPlanExecutor>();
            }
            if (AutoRunOnStart)
            {
                StartCoroutine(RequestPlanAndMaybeExecute());
            }
        }

        public void TriggerPlanFlow()
        {
            StartCoroutine(RequestPlanAndMaybeExecute());
        }

        private IEnumerator RequestPlanAndMaybeExecute()
        {
            string planUrl = BuildUrl("/api/plan");
            var requestBody = new PlanGenerateRequest
            {
                runPackage = RunPackage,
                frameSeq = Mathf.Max(1, FrameSeq),
            };
            string requestJson = JsonUtility.ToJson(requestBody);

            using (var req = BuildJsonPost(planUrl, requestJson))
            {
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"[PlanClient] /api/plan failed: {req.error} | {req.downloadHandler.text}");
                    yield break;
                }

                _lastPlanJson = req.downloadHandler.text;
                var header = JsonUtility.FromJson<ActionPlanHeader>(_lastPlanJson);
                _lastRunId = header != null ? header.runId : string.Empty;
                _lastFrameSeq = (header != null && header.frameSeq > 0) ? header.frameSeq : Mathf.Max(1, FrameSeq);
                var state = ByesSystemState.Instance;
                if (state != null)
                {
                    state.SetRunFrame(_lastRunId, _lastFrameSeq);
                    state.RecordActionPlanRaw(_lastPlanJson);
                }
                Debug.Log($"[PlanClient] plan generated runId={_lastRunId} frameSeq={_lastFrameSeq}");
            }

            if (!ExecuteAfterPlan)
            {
                yield break;
            }

            yield return ExecuteLastPlan();
        }

        public IEnumerator ExecuteLastPlan()
        {
            if (string.IsNullOrWhiteSpace(_lastPlanJson))
            {
                Debug.LogWarning("[PlanClient] ExecuteLastPlan skipped: no plan cached.");
                yield break;
            }

            string executeUrl = BuildUrl("/api/plan/execute");
            string executeJson = BuildPlanExecuteJson(_lastPlanJson, RunPackage, _lastRunId, _lastFrameSeq);

            using (var req = BuildJsonPost(executeUrl, executeJson))
            {
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"[PlanClient] /api/plan/execute failed: {req.error} | {req.downloadHandler.text}");
                    yield break;
                }

                string executionJson = req.downloadHandler.text;
                var summary = JsonUtility.FromJson<PlanExecutor.ExecutionSummary>(executionJson);
                if (summary == null)
                {
                    Debug.LogWarning("[PlanClient] execution summary parse failed.");
                    yield break;
                }

                if (Executor != null)
                {
                    if (string.IsNullOrWhiteSpace(_lastRunId))
                    {
                        if (ByesFrameTelemetry.TryGetLatestFrameContext(out var latestRunId, out var latestFrameSeq))
                        {
                            _lastRunId = latestRunId;
                            _lastFrameSeq = Mathf.Max(1, latestFrameSeq);
                        }
                    }
                    Executor.SetExecutionContext(_lastRunId, Mathf.Max(1, _lastFrameSeq));
                    Executor.ExecuteSummary(summary, null);
                }
                else if (ActionExecutor != null)
                {
                    if (!ActionPlanParser.TryParse(_lastPlanJson, out var parsedPlan, out var parseError))
                    {
                        parsedPlan = ActionPlanParser.BuildSafeFallback("ActionPlan parse failed: " + parseError, _lastRunId, _lastFrameSeq);
                    }
                    ActionExecutor.SetExecutionContext(_lastRunId, Mathf.Max(1, _lastFrameSeq));
                    ActionExecutor.ExecutePlan(parsedPlan);
                }
                else
                {
                    Debug.LogWarning("[PlanClient] PlanExecutor missing, only logging execution summary.");
                }
            }
        }

        private void OnConfirmDecision(string confirmId, bool accepted)
        {
            StartCoroutine(SendConfirmResponse(confirmId, accepted));
        }

        private IEnumerator SendConfirmResponse(string confirmId, bool accepted)
        {
            if (string.IsNullOrWhiteSpace(_lastRunId))
            {
                Debug.LogWarning("[PlanClient] confirm skipped: runId is empty.");
                yield break;
            }

            var body = new ConfirmResponseRequest
            {
                runId = _lastRunId,
                frameSeq = Mathf.Max(1, _lastFrameSeq),
                confirmId = confirmId,
                accepted = accepted,
                runPackage = RunPackage,
            };
            string json = JsonUtility.ToJson(body);
            string url = BuildUrl("/api/confirm/response");

            using (var req = BuildJsonPost(url, json))
            {
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError($"[PlanClient] /api/confirm/response failed: {req.error} | {req.downloadHandler.text}");
                    yield break;
                }
                Debug.Log($"[PlanClient] confirm submitted id={confirmId} accepted={accepted}");
            }
        }

        private string BuildUrl(string path)
        {
            string baseUrl = (GatewayBaseUrl ?? string.Empty).TrimEnd('/');
            return baseUrl + path;
        }

        private static UnityWebRequest BuildJsonPost(string url, string json)
        {
            byte[] data = Encoding.UTF8.GetBytes(json ?? "{}");
            var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST)
            {
                uploadHandler = new UploadHandlerRaw(data),
                downloadHandler = new DownloadHandlerBuffer(),
            };
            req.SetRequestHeader("Content-Type", "application/json");
            return req;
        }

        private static string BuildPlanExecuteJson(string rawPlanJson, string runPackage, string runId, int frameSeq)
        {
            string safeRunPackage = EscapeJson(runPackage ?? string.Empty);
            string safeRunId = EscapeJson(runId ?? string.Empty);
            return "{" +
                   "\"plan\":" + rawPlanJson + "," +
                   "\"runPackage\":\"" + safeRunPackage + "\"," +
                   "\"runId\":\"" + safeRunId + "\"," +
                   "\"frameSeq\":" + Mathf.Max(1, frameSeq) +
                   "}";
        }

        private static string EscapeJson(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return string.Empty;
            }
            return value.Replace("\\", "\\\\").Replace("\"", "\\\"");
        }
    }
}
