using System;
using BYES.Core;
using BYES.Telemetry;
using BYES.UI;
using UnityEngine;

namespace BYES.Plan
{
    public class PlanExecutor : MonoBehaviour
    {
        [Serializable]
        public class ActionRef
        {
            public string type;
            public string actionId;
            public string reason;
        }

        [Serializable]
        public class PendingConfirm
        {
            public string confirmId;
            public int timeoutMs;
            public string actionId;
        }

        [Serializable]
        public class UiCommand
        {
            public string kind;
            public string commandType;
            public string actionId;
            public string text;
            public string label;
            public string reason;
            public string confirmId;
            public int timeoutMs;
        }

        [Serializable]
        public class ExecutionSummary
        {
            public bool ok;
            public int executedCount;
            public int blockedCount;
            public int pendingConfirmCount;
            public ActionRef[] executed;
            public ActionRef[] blocked;
            public PendingConfirm[] pendingConfirms;
            public UiCommand[] uiCommands;
        }

        public bool IsStopped { get; private set; }
        public string LastOverlayText { get; private set; } = string.Empty;

        private string _runIdForAck = "unknown-run";
        private int _frameSeqForAck = 1;

        public void SetExecutionContext(string runId, int frameSeq)
        {
            _runIdForAck = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim();
            _frameSeqForAck = Mathf.Max(1, frameSeq);
        }

        public void ExecuteSummary(ExecutionSummary summary, Action<string, bool> onConfirmDecision)
        {
            if (summary == null)
            {
                Debug.LogWarning("[PlanExecutor] execution summary is null");
                return;
            }

            if (summary.uiCommands != null && summary.uiCommands.Length > 0)
            {
                foreach (var cmd in summary.uiCommands)
                {
                    if (cmd == null)
                    {
                        continue;
                    }
                    ExecuteCommand(cmd, onConfirmDecision);
                }
            }

            if (summary.pendingConfirms != null && summary.pendingConfirms.Length > 0)
            {
                var pending = summary.pendingConfirms[0];
                if (pending != null)
                {
                    ShowConfirmFromPending(pending, onConfirmDecision);
                }
            }
        }

        private void ExecuteCommand(UiCommand command, Action<string, bool> onConfirmDecision)
        {
            var kind = (command.kind ?? string.Empty).Trim().ToLowerInvariant();
            if (kind == "ui.confirm_request")
            {
                var prompt = string.IsNullOrWhiteSpace(command.text) ? "Please confirm." : command.text;
                var timeoutMs = command.timeoutMs > 0 ? command.timeoutMs : 5000;
                ShowConfirm(command.confirmId, prompt, timeoutMs, onConfirmDecision);
                return;
            }

            var commandType = (command.commandType ?? string.Empty).Trim().ToLowerInvariant();
            switch (commandType)
            {
                case "speak":
                    Debug.Log($"[PlanExecutor] SPEAK: {command.text}");
                    ByesFrameTelemetry.AckFeedback(
                        _runIdForAck,
                        _frameSeqForAck,
                        "tts",
                        true,
                        ByesFrameTelemetry.NowUnixMs(),
                        providerBackend: "android_tts",
                        providerModel: "quest-tts",
                        providerDevice: "quest",
                        providerReason: "client_tts",
                        providerIsMock: false);
                    break;
                case "overlay":
                case "ar":
                    LastOverlayText = command.label ?? string.Empty;
                    ByesOverlayRenderer.EnsureExists().RenderOverlayCommand(
                        _runIdForAck,
                        _frameSeqForAck,
                        commandType,
                        command.label,
                        command.text,
                        command.reason
                    );
                    break;
                case "haptic":
                    if (ByesHaptics.Instance.TrySendPulse(HapticChannel.Both, 0.5f, 0.08f, command.actionId, command.confirmId))
                    {
                        if (ByesOverlayAckThrottler.Instance.TryMark(_runIdForAck, _frameSeqForAck, "haptic"))
                        {
                            ByesFrameTelemetry.AckFeedback(_runIdForAck, _frameSeqForAck, "haptic", true, ByesFrameTelemetry.NowUnixMs());
                        }
                    }
                    else if (Debug.isDebugBuild)
                    {
                        Debug.Log("[PlanExecutor] HAPTIC skipped (unsupported or debounced)");
                    }
                    break;
                case "stop":
                    IsStopped = true;
                    ByesOverlayRenderer.EnsureExists().RenderStop(_runIdForAck, _frameSeqForAck, string.IsNullOrWhiteSpace(command.text) ? "STOP" : command.text);
                    if (ByesHaptics.Instance.TrySendPulse(HapticChannel.Both, 0.9f, 0.15f, command.actionId, command.confirmId))
                    {
                        if (ByesOverlayAckThrottler.Instance.TryMark(_runIdForAck, _frameSeqForAck, "haptic"))
                        {
                            ByesFrameTelemetry.AckFeedback(_runIdForAck, _frameSeqForAck, "haptic", true, ByesFrameTelemetry.NowUnixMs());
                        }
                    }
                    Debug.Log($"[PlanExecutor] STOP: {command.reason}");
                    break;
                default:
                    Debug.LogWarning($"[PlanExecutor] unknown ui command type={commandType}");
                    break;
            }
        }

        private void ShowConfirmFromPending(PendingConfirm pending, Action<string, bool> onConfirmDecision)
        {
            var confirmId = pending != null ? pending.confirmId : string.Empty;
            var timeoutMs = pending != null ? pending.timeoutMs : 5000;
            var actionId = pending != null ? pending.actionId : string.Empty;
            var prompt = string.IsNullOrWhiteSpace(actionId) ? "Please confirm." : actionId;
            ShowConfirm(confirmId, prompt, timeoutMs, onConfirmDecision);
        }

        private void ShowConfirm(string confirmId, string prompt, int timeoutMs, Action<string, bool> onConfirmDecision)
        {
            var safeConfirmId = string.IsNullOrWhiteSpace(confirmId) ? $"confirm-{Time.frameCount}" : confirmId.Trim();
            var safePrompt = string.IsNullOrWhiteSpace(prompt) ? "Please confirm." : prompt.Trim();
            var safeTimeout = timeoutMs > 0 ? timeoutMs : 5000;

            var state = ByesSystemState.Instance;
            if (state != null)
            {
                state.SetPendingConfirm(1, safeConfirmId);
            }

            ByesConfirmPanel.EnsureExists().ShowConfirm(
                _runIdForAck,
                _frameSeqForAck,
                safeConfirmId,
                safePrompt,
                safeTimeout,
                onDecision: (id, accepted) =>
                {
                    if (state != null)
                    {
                        state.SetPendingConfirm(0, id);
                    }
                    onConfirmDecision?.Invoke(id, accepted);
                }
            );
        }
    }
}
