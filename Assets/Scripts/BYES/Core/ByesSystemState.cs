using System;
using BYES.Plan;
using UnityEngine;

namespace BYES.Core
{
    public enum ByesMode
    {
        Walk,
        ReadText,
        Inspect,
    }

    public sealed class ByesSystemState : MonoBehaviour
    {
        private static ByesSystemState _instance;

        [SerializeField] private string runId = "unknown-run";
        [SerializeField] private int frameSeq = 1;
        [SerializeField] private ByesMode currentMode = ByesMode.Walk;
        [SerializeField] private string lastActionPlanJson = string.Empty;
        [SerializeField] private string lastRiskLevel = string.Empty;
        [SerializeField] private string[] topHazards = Array.Empty<string>();
        [SerializeField] private int pendingConfirmCount = 0;
        [SerializeField] private string lastConfirmId = string.Empty;

        private ActionPlanV1 _lastActionPlan;

        public static ByesSystemState Instance => _instance ?? EnsureExists();

        public string RunId => runId;
        public int FrameSeq => frameSeq;
        public ByesMode CurrentMode => currentMode;
        public string LastActionPlanJson => lastActionPlanJson;
        public ActionPlanV1 LastActionPlan => _lastActionPlan;
        public string LastRiskLevel => lastRiskLevel;
        public string[] TopHazards => topHazards;
        public int PendingConfirmCount => pendingConfirmCount;
        public string LastConfirmId => lastConfirmId;

        public static ByesSystemState EnsureExists()
        {
            if (_instance != null)
            {
                return _instance;
            }

            var existing = FindFirstObjectByType<ByesSystemState>();
            if (existing != null)
            {
                _instance = existing;
                DontDestroyOnLoad(_instance.gameObject);
                return _instance;
            }

            var root = new GameObject("BYES_SystemState");
            DontDestroyOnLoad(root);
            _instance = root.AddComponent<ByesSystemState>();
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
            frameSeq = Mathf.Max(1, frameSeq);
        }

        public void SetRunFrame(string value, int seq)
        {
            runId = string.IsNullOrWhiteSpace(value) ? "unknown-run" : value.Trim();
            frameSeq = Mathf.Max(1, seq);
        }

        public void SetMode(ByesMode mode)
        {
            currentMode = mode;
        }

        public void SetRiskSnapshot(string riskLevel, string[] hazards)
        {
            lastRiskLevel = string.IsNullOrWhiteSpace(riskLevel) ? string.Empty : riskLevel.Trim();
            topHazards = hazards ?? Array.Empty<string>();
        }

        public void SetPendingConfirm(int count, string confirmId)
        {
            pendingConfirmCount = Mathf.Max(0, count);
            lastConfirmId = string.IsNullOrWhiteSpace(confirmId) ? string.Empty : confirmId.Trim();
        }

        public void RecordActionPlanRaw(string rawJson)
        {
            lastActionPlanJson = rawJson ?? string.Empty;
            if (!ActionPlanParser.TryParse(lastActionPlanJson, out var parsed, out var error))
            {
                _lastActionPlan = ActionPlanParser.BuildSafeFallback("ActionPlan parse failed: " + error, runId, frameSeq);
                return;
            }

            RecordActionPlan(parsed, lastActionPlanJson);
        }

        public void RecordActionPlan(ActionPlanV1 plan, string rawJson = "")
        {
            if (plan == null)
            {
                return;
            }

            _lastActionPlan = plan;
            if (!string.IsNullOrWhiteSpace(rawJson))
            {
                lastActionPlanJson = rawJson;
            }

            if (!string.IsNullOrWhiteSpace(plan.runId))
            {
                runId = plan.runId.Trim();
            }

            if (plan.frameSeq > 0)
            {
                frameSeq = plan.frameSeq;
            }

            lastRiskLevel = string.IsNullOrWhiteSpace(plan.riskLevel) ? string.Empty : plan.riskLevel.Trim();
        }
    }
}
