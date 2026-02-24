using System;
using UnityEngine;

namespace BYES.Plan
{
    [Serializable]
    public sealed class ActionPlanV1
    {
        public string schemaVersion = "byes.action_plan.v1";
        public string runId = "unknown-run";
        public int frameSeq = 1;
        public string riskLevel = "unknown";
        public ActionPlanAction[] actions = Array.Empty<ActionPlanAction>();
        public string[] guardrailsApplied = Array.Empty<string>();
        public ActionPlanMeta meta = new ActionPlanMeta();
    }

    [Serializable]
    public sealed class ActionPlanAction
    {
        public string actionId = string.Empty;
        public string type = string.Empty;
        public string reason = string.Empty;
        public bool blocking = false;
        public bool requiresConfirm = false;
        public ActionPlanPayload payload = new ActionPlanPayload();
    }

    [Serializable]
    public sealed class ActionPlanPayload
    {
        public string text = string.Empty;
        public string label = string.Empty;
        public string confirmId = string.Empty;
        public int timeoutMs = 0;
        public string source = string.Empty;
        public string[] sourceDecisionIds = Array.Empty<string>();
    }

    [Serializable]
    public sealed class ActionPlanMeta
    {
        public ActionPlanPlannerMeta planner = new ActionPlanPlannerMeta();
    }

    [Serializable]
    public sealed class ActionPlanPlannerMeta
    {
        public string backend = string.Empty;
        public string model = string.Empty;
        public string endpoint = string.Empty;
        public string promptVersion = string.Empty;
        public bool fallbackUsed = false;
    }

    public static class ActionPlanParser
    {
        public static bool TryParse(string rawJson, out ActionPlanV1 plan, out string error)
        {
            plan = null;
            error = string.Empty;
            if (string.IsNullOrWhiteSpace(rawJson))
            {
                error = "empty_json";
                return false;
            }

            try
            {
                plan = JsonUtility.FromJson<ActionPlanV1>(rawJson);
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }

            if (plan == null)
            {
                error = "deserialized_null";
                return false;
            }

            if (string.IsNullOrWhiteSpace(plan.schemaVersion))
            {
                plan.schemaVersion = "byes.action_plan.v1";
            }

            if (plan.actions == null)
            {
                plan.actions = Array.Empty<ActionPlanAction>();
            }

            if (plan.meta == null)
            {
                plan.meta = new ActionPlanMeta();
            }
            if (plan.meta.planner == null)
            {
                plan.meta.planner = new ActionPlanPlannerMeta();
            }

            plan.frameSeq = Mathf.Max(1, plan.frameSeq);
            plan.runId = string.IsNullOrWhiteSpace(plan.runId) ? "unknown-run" : plan.runId.Trim();
            return true;
        }

        public static ActionPlanV1 BuildSafeFallback(string message, string runId = "unknown-run", int frameSeq = 1)
        {
            return new ActionPlanV1
            {
                schemaVersion = "byes.action_plan.v1",
                runId = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim(),
                frameSeq = Mathf.Max(1, frameSeq),
                riskLevel = "critical",
                actions = new[]
                {
                    new ActionPlanAction
                    {
                        actionId = "fallback-speak-1",
                        type = "speak",
                        blocking = false,
                        requiresConfirm = false,
                        reason = "json_parse_failed",
                        payload = new ActionPlanPayload
                        {
                            text = string.IsNullOrWhiteSpace(message) ? "Action plan parse failed. Please stop and retry." : message.Trim(),
                        },
                    },
                },
                guardrailsApplied = new[] {"unity_actionplan_parse_fallback"},
                meta = new ActionPlanMeta
                {
                    planner = new ActionPlanPlannerMeta
                    {
                        backend = "unity-local",
                        model = "action-plan-parser-v1",
                        promptVersion = "n/a",
                        fallbackUsed = true,
                    },
                },
            };
        }
    }
}
