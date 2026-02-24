using BYES.Core;
using BYES.Telemetry;
using BYES.UI;
using UnityEngine;

namespace BYES.Plan
{
    public sealed class ActionPlanExecutor : MonoBehaviour
    {
        [Header("Audio (placeholder TTS)")]
        public AudioSource TtsAudioSource;
        public AudioClip PlaceholderTtsClip;

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

            var pendingConfirm = 0;
            var lastConfirmId = string.Empty;

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
                        ExecuteHaptic();
                        break;
                    case "confirm":
                        pendingConfirm += 1;
                        lastConfirmId = ExecuteConfirm(action);
                        break;
                    case "stop":
                        ExecuteStop(action);
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
            var label = action != null && action.payload != null ? action.payload.label : string.Empty;
            var text = action != null && action.payload != null ? action.payload.text : string.Empty;
            ByesOverlayRenderer.EnsureExists().RenderOverlayCommand(_runId, _frameSeq, "overlay", label, text, action != null ? action.reason : string.Empty);
        }

        private static void ExecuteHaptic()
        {
            Debug.Log("[ActionPlanExecutor] HAPTIC unsupported on current runtime");
        }

        private string ExecuteConfirm(ActionPlanAction action)
        {
            var payload = action != null ? action.payload : null;
            var confirmId = payload != null ? payload.confirmId : string.Empty;
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                confirmId = !string.IsNullOrWhiteSpace(action?.actionId) ? action.actionId : $"confirm-{Time.frameCount}";
            }
            var prompt = payload != null ? payload.text : string.Empty;
            if (string.IsNullOrWhiteSpace(prompt))
            {
                prompt = "Please confirm.";
            }
            var timeoutMs = payload != null ? payload.timeoutMs : 0;
            if (timeoutMs <= 0)
            {
                timeoutMs = 5000;
            }

            ByesConfirmPanel.EnsureExists().ShowConfirm(
                _runId,
                _frameSeq,
                confirmId,
                prompt,
                timeoutMs,
                onDecision: (id, _accepted) =>
                {
                    var state = ByesSystemState.Instance;
                    if (state != null)
                    {
                        state.SetPendingConfirm(0, id);
                    }
                }
            );
            return confirmId;
        }

        private void ExecuteStop(ActionPlanAction action)
        {
            var text = action != null && action.payload != null ? action.payload.text : string.Empty;
            if (string.IsNullOrWhiteSpace(text))
            {
                text = "STOP";
            }
            ByesOverlayRenderer.EnsureExists().RenderStop(_runId, _frameSeq, text);
            Debug.Log("[ActionPlanExecutor] STOP command received");
        }
    }
}
