using BYES.Core;
using BYES.Telemetry;
using UnityEngine;

namespace BYES.Plan
{
    public sealed class ActionPlanExecutor : MonoBehaviour
    {
        [Header("Audio (placeholder TTS)")]
        public AudioSource TtsAudioSource;
        public AudioClip PlaceholderTtsClip;

        [Header("Behavior")]
        public bool AutoAcknowledgeConfirm = true;

        private string _runId = "unknown-run";
        private int _frameSeq = 1;

        public void SetExecutionContext(string runId, int frameSeq)
        {
            _runId = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim();
            _frameSeq = Mathf.Max(1, frameSeq);
        }

        public void ExecuteFromJson(string planJson)
        {
            if (!ActionPlanParser.TryParse(planJson, out var plan, out var parseError))
            {
                plan = ActionPlanParser.BuildSafeFallback("ActionPlan parse failed: " + parseError, _runId, _frameSeq);
            }
            ExecutePlan(plan);
        }

        public void ExecutePlan(ActionPlanV1 plan)
        {
            if (plan == null)
            {
                return;
            }

            if (!string.IsNullOrWhiteSpace(plan.runId))
            {
                _runId = plan.runId.Trim();
            }
            _frameSeq = Mathf.Max(1, plan.frameSeq);

            var state = ByesSystemState.Instance;
            if (state != null)
            {
                state.RecordActionPlan(plan);
            }

            int pendingConfirm = 0;
            string lastConfirmId = string.Empty;

            if (plan.actions == null || plan.actions.Length == 0)
            {
                return;
            }

            foreach (var action in plan.actions)
            {
                if (action == null)
                {
                    continue;
                }

                var kind = (action.type ?? string.Empty).Trim().ToLowerInvariant();
                switch (kind)
                {
                    case "speak":
                        ExecuteSpeak(action);
                        break;
                    case "overlay":
                    case "ar":
                        ExecuteOverlay(action);
                        break;
                    case "haptic":
                        ExecuteHaptic(action);
                        break;
                    case "confirm":
                        pendingConfirm += 1;
                        lastConfirmId = action.payload != null ? action.payload.confirmId : string.Empty;
                        if (AutoAcknowledgeConfirm)
                        {
                            ByesFrameTelemetry.AckFeedback(_runId, _frameSeq, "tts", true, ByesFrameTelemetry.NowUnixMs());
                        }
                        break;
                    case "stop":
                        Debug.Log("[ActionPlanExecutor] STOP command received");
                        break;
                    default:
                        Debug.LogWarning("[ActionPlanExecutor] unknown action type=" + kind);
                        break;
                }
            }

            if (state != null)
            {
                state.SetPendingConfirm(pendingConfirm, lastConfirmId);
            }
        }

        private void ExecuteSpeak(ActionPlanAction action)
        {
            var text = action != null && action.payload != null ? action.payload.text : string.Empty;
            if (TtsAudioSource != null && PlaceholderTtsClip != null)
            {
                TtsAudioSource.PlayOneShot(PlaceholderTtsClip);
            }
            Debug.Log("[ActionPlanExecutor] SPEAK: " + text);
            ByesFrameTelemetry.AckFeedback(_runId, _frameSeq, "tts", true, ByesFrameTelemetry.NowUnixMs());
        }

        private void ExecuteOverlay(ActionPlanAction action)
        {
            var text = action != null && action.payload != null ? action.payload.text : string.Empty;
            Debug.Log("[ActionPlanExecutor] OVERLAY: " + text);
            ByesFrameTelemetry.AckFeedback(_runId, _frameSeq, "ar", true, ByesFrameTelemetry.NowUnixMs());
        }

        private void ExecuteHaptic(ActionPlanAction action)
        {
            Debug.Log("[ActionPlanExecutor] HAPTIC unsupported on current runtime, ack accepted=false");
            ByesFrameTelemetry.AckFeedback(_runId, _frameSeq, "haptic", false, ByesFrameTelemetry.NowUnixMs());
        }
    }
}
