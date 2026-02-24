using System;
using UnityEngine;
using UnityEngine.UI;
using BYES.Telemetry;

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

        private Canvas _confirmCanvas;
        private GameObject _confirmPanel;
        private Text _confirmText;
        private Button _yesButton;
        private Button _noButton;
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

            if (summary.uiCommands == null || summary.uiCommands.Length == 0)
            {
                Debug.Log("[PlanExecutor] no uiCommands to execute");
                return;
            }

            foreach (var cmd in summary.uiCommands)
            {
                if (cmd == null)
                {
                    continue;
                }
                ExecuteCommand(cmd, onConfirmDecision);
            }
        }

        private void ExecuteCommand(UiCommand command, Action<string, bool> onConfirmDecision)
        {
            string kind = (command.kind ?? string.Empty).Trim().ToLowerInvariant();
            if (kind == "ui.confirm_request")
            {
                ShowConfirmPanel(command, onConfirmDecision);
                return;
            }

            string commandType = (command.commandType ?? string.Empty).Trim().ToLowerInvariant();
            switch (commandType)
            {
                case "speak":
                    Debug.Log($"[PlanExecutor] SPEAK: {command.text}");
                    ByesFrameTelemetry.AckFeedback(
                        _runIdForAck,
                        _frameSeqForAck,
                        "tts",
                        true,
                        ByesFrameTelemetry.NowUnixMs()
                    );
                    break;
                case "overlay":
                    LastOverlayText = command.label;
                    Debug.Log($"[PlanExecutor] OVERLAY: {command.label} ({command.text})");
                    ByesFrameTelemetry.AckFeedback(
                        _runIdForAck,
                        _frameSeqForAck,
                        "ar",
                        true,
                        ByesFrameTelemetry.NowUnixMs()
                    );
                    break;
                case "haptic":
                    Debug.Log("[PlanExecutor] HAPTIC trigger");
                    ByesFrameTelemetry.AckFeedback(
                        _runIdForAck,
                        _frameSeqForAck,
                        "haptic",
                        true,
                        ByesFrameTelemetry.NowUnixMs()
                    );
                    break;
                case "stop":
                    IsStopped = true;
                    Debug.Log($"[PlanExecutor] STOP: {command.reason}");
                    break;
                default:
                    Debug.LogWarning($"[PlanExecutor] unknown ui command type={commandType}");
                    break;
            }
        }

        private void ShowConfirmPanel(UiCommand command, Action<string, bool> onConfirmDecision)
        {
            EnsureConfirmUi();
            if (_confirmPanel == null || _confirmText == null || _yesButton == null || _noButton == null)
            {
                Debug.LogWarning("[PlanExecutor] confirm UI unavailable");
                return;
            }

            string confirmId = string.IsNullOrWhiteSpace(command.confirmId) ? "confirm-unknown" : command.confirmId;
            string prompt = string.IsNullOrWhiteSpace(command.text) ? "Please confirm." : command.text;
            _confirmText.text = prompt;
            _confirmPanel.SetActive(true);

            _yesButton.onClick.RemoveAllListeners();
            _noButton.onClick.RemoveAllListeners();
            _yesButton.onClick.AddListener(() =>
            {
                _confirmPanel.SetActive(false);
                onConfirmDecision?.Invoke(confirmId, true);
            });
            _noButton.onClick.AddListener(() =>
            {
                _confirmPanel.SetActive(false);
                onConfirmDecision?.Invoke(confirmId, false);
            });
        }

        private void EnsureConfirmUi()
        {
            if (_confirmCanvas != null)
            {
                return;
            }

            var canvasGo = new GameObject("BYES_ConfirmCanvas");
            _confirmCanvas = canvasGo.AddComponent<Canvas>();
            _confirmCanvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvasGo.AddComponent<CanvasScaler>();
            canvasGo.AddComponent<GraphicRaycaster>();

            _confirmPanel = new GameObject("ConfirmPanel");
            _confirmPanel.transform.SetParent(canvasGo.transform, false);
            var panelImage = _confirmPanel.AddComponent<Image>();
            panelImage.color = new Color(0f, 0f, 0f, 0.75f);
            var panelRect = _confirmPanel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0.25f, 0.25f);
            panelRect.anchorMax = new Vector2(0.75f, 0.75f);
            panelRect.offsetMin = Vector2.zero;
            panelRect.offsetMax = Vector2.zero;

            _confirmText = CreateText("PromptText", _confirmPanel.transform, "Please confirm.");
            var textRect = _confirmText.GetComponent<RectTransform>();
            textRect.anchorMin = new Vector2(0.1f, 0.55f);
            textRect.anchorMax = new Vector2(0.9f, 0.9f);
            textRect.offsetMin = Vector2.zero;
            textRect.offsetMax = Vector2.zero;

            _yesButton = CreateButton("YesButton", _confirmPanel.transform, "Yes", new Vector2(0.2f, 0.15f), new Vector2(0.45f, 0.4f));
            _noButton = CreateButton("NoButton", _confirmPanel.transform, "No", new Vector2(0.55f, 0.15f), new Vector2(0.8f, 0.4f));

            _confirmPanel.SetActive(false);
        }

        private static Text CreateText(string name, Transform parent, string content)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var text = go.AddComponent<Text>();
            text.text = content;
            text.color = Color.white;
            text.alignment = TextAnchor.MiddleCenter;
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.resizeTextForBestFit = true;
            return text;
        }

        private static Button CreateButton(string name, Transform parent, string label, Vector2 anchorMin, Vector2 anchorMax)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var image = go.AddComponent<Image>();
            image.color = new Color(0.2f, 0.2f, 0.2f, 0.95f);
            var button = go.AddComponent<Button>();

            var rect = go.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;

            var text = CreateText("Label", go.transform, label);
            var textRect = text.GetComponent<RectTransform>();
            textRect.anchorMin = new Vector2(0f, 0f);
            textRect.anchorMax = new Vector2(1f, 1f);
            textRect.offsetMin = Vector2.zero;
            textRect.offsetMax = Vector2.zero;
            return button;
        }
    }
}
