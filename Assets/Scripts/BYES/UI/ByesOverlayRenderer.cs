using BYES.Core;
using BYES.Plan;
using BYES.Telemetry;
using UnityEngine;
using UnityEngine.UI;

namespace BYES.UI
{
    public sealed class ByesOverlayRenderer : MonoBehaviour
    {
        private static ByesOverlayRenderer _instance;

        private Canvas _canvas;
        private Image _panel;
        private Text _titleText;
        private Text _detailText;
        private Text _hotspotText;

        private string _lastPlanSignature = string.Empty;
        private int _lastRenderedFrameSeq = -1;
        private string _lastRenderedRunId = string.Empty;

        public static ByesOverlayRenderer Instance => EnsureExists();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            _ = EnsureExists();
        }

        public static ByesOverlayRenderer EnsureExists()
        {
            if (_instance != null)
            {
                return _instance;
            }

            var existing = FindFirstObjectByType<ByesOverlayRenderer>();
            if (existing != null)
            {
                _instance = existing;
                DontDestroyOnLoad(_instance.gameObject);
                return _instance;
            }

            var root = new GameObject("BYES_OverlayRenderer");
            DontDestroyOnLoad(root);
            _instance = root.AddComponent<ByesOverlayRenderer>();
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
            EnsureUi();
            Hide();
        }

        private void Update()
        {
            var state = ByesSystemState.Instance;
            if (state == null)
            {
                return;
            }

            var plan = state.LastActionPlan;
            if (plan == null)
            {
                return;
            }

            var signature = $"{plan.runId}|{plan.frameSeq}|{state.LastActionPlanJson}";
            if (signature == _lastPlanSignature)
            {
                return;
            }

            _lastPlanSignature = signature;
            RenderFromActionPlan(plan);
        }

        public void RenderFromActionPlan(ActionPlanV1 plan)
        {
            if (plan == null)
            {
                return;
            }

            if (plan.actions != null)
            {
                foreach (var action in plan.actions)
                {
                    if (action == null)
                    {
                        continue;
                    }

                    var actionType = (action.type ?? string.Empty).Trim().ToLowerInvariant();
                    if (actionType == "stop")
                    {
                        RenderStop(plan.runId, plan.frameSeq, ResolveActionText(action, "STOP"));
                        return;
                    }

                    if (actionType == "overlay" || actionType == "ar")
                    {
                        var label = (action.payload != null ? action.payload.label : string.Empty) ?? string.Empty;
                        var text = ResolveActionText(action, label);
                        RenderOverlayCommand(plan.runId, plan.frameSeq, actionType, label, text, action.reason);
                        return;
                    }
                }
            }

            if ((plan.riskLevel ?? string.Empty).Trim().ToLowerInvariant() == "critical")
            {
                RenderStop(plan.runId, plan.frameSeq, "STOP");
            }
        }

        public void RenderOverlayCommand(string runId, int frameSeq, string commandType, string label, string text, string reason)
        {
            var blob = $"{commandType} {label} {text} {reason}".ToLowerInvariant();
            if (blob.Contains("left"))
            {
                RenderTurn(runId, frameSeq, "LEFT", string.IsNullOrWhiteSpace(text) ? "Turn left" : text);
                return;
            }
            if (blob.Contains("right"))
            {
                RenderTurn(runId, frameSeq, "RIGHT", string.IsNullOrWhiteSpace(text) ? "Turn right" : text);
                return;
            }

            var left = "low";
            var center = "medium";
            var right = "low";
            if (blob.Contains("center") || blob.Contains("front"))
            {
                center = "high";
            }
            if (blob.Contains("left_high"))
            {
                left = "high";
            }
            if (blob.Contains("right_high"))
            {
                right = "high";
            }
            RenderRiskHotspot(runId, frameSeq, left, center, right, string.IsNullOrWhiteSpace(text) ? "Risk hotspot" : text);
        }

        public void RenderStop(string runId, int frameSeq, string message)
        {
            EnsureUi();
            ApplyPanel(Color.red, "STOP", string.IsNullOrWhiteSpace(message) ? "STOP" : message, string.Empty);
            AcknowledgeAr(runId, frameSeq, true);
        }

        public void RenderTurn(string runId, int frameSeq, string direction, string message)
        {
            EnsureUi();
            var normalized = string.IsNullOrWhiteSpace(direction) ? "TURN" : direction.Trim().ToUpperInvariant();
            ApplyPanel(new Color(0.15f, 0.35f, 0.8f, 0.85f), $"TURN {normalized}", message, string.Empty);
            AcknowledgeAr(runId, frameSeq, true);
        }

        public void RenderRiskHotspot(string runId, int frameSeq, string left, string center, string right, string message)
        {
            EnsureUi();
            var hotspot = $"L:{left}  C:{center}  R:{right}";
            ApplyPanel(new Color(0.1f, 0.1f, 0.1f, 0.85f), "RISK HOTSPOT", message, hotspot);
            AcknowledgeAr(runId, frameSeq, true);
        }

        public void Hide()
        {
            EnsureUi();
            if (_canvas != null)
            {
                _canvas.enabled = false;
            }
        }

        private void AcknowledgeAr(string runId, int frameSeq, bool accepted)
        {
            var safeRunId = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim();
            var safeFrameSeq = Mathf.Max(1, frameSeq);
            if (_lastRenderedRunId == safeRunId && _lastRenderedFrameSeq == safeFrameSeq)
            {
                return;
            }

            if (ByesOverlayAckThrottler.Instance.TryMark(safeRunId, safeFrameSeq, "ar"))
            {
                _lastRenderedRunId = safeRunId;
                _lastRenderedFrameSeq = safeFrameSeq;
                ByesFrameTelemetry.AckFeedback(safeRunId, safeFrameSeq, "ar", accepted, ByesFrameTelemetry.NowUnixMs());
            }
        }

        private void ApplyPanel(Color color, string title, string detail, string hotspot)
        {
            if (_canvas == null || _panel == null || _titleText == null || _detailText == null || _hotspotText == null)
            {
                return;
            }

            _canvas.enabled = true;
            _panel.color = color;
            _titleText.text = title ?? string.Empty;
            _detailText.text = detail ?? string.Empty;
            _hotspotText.text = hotspot ?? string.Empty;
        }

        private void EnsureUi()
        {
            if (_canvas != null)
            {
                return;
            }

            var canvasGo = new GameObject("BYES_OverlayCanvas");
            canvasGo.transform.SetParent(transform, false);

            _canvas = canvasGo.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.worldCamera = Camera.main;
            canvasGo.AddComponent<CanvasScaler>();
            canvasGo.AddComponent<GraphicRaycaster>();

            var canvasRect = canvasGo.GetComponent<RectTransform>();
            canvasRect.sizeDelta = new Vector2(640f, 220f);
            canvasRect.localScale = Vector3.one * 0.0025f;
            canvasRect.localPosition = new Vector3(0f, 0f, 2.0f);

            var panelGo = new GameObject("OverlayPanel");
            panelGo.transform.SetParent(canvasGo.transform, false);
            _panel = panelGo.AddComponent<Image>();
            _panel.color = new Color(0f, 0f, 0f, 0.8f);

            var panelRect = panelGo.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0f, 0f);
            panelRect.anchorMax = new Vector2(1f, 1f);
            panelRect.offsetMin = Vector2.zero;
            panelRect.offsetMax = Vector2.zero;

            _titleText = CreateText("Title", panelGo.transform, TextAnchor.UpperCenter, 40, FontStyle.Bold);
            var titleRect = _titleText.GetComponent<RectTransform>();
            titleRect.anchorMin = new Vector2(0.05f, 0.65f);
            titleRect.anchorMax = new Vector2(0.95f, 0.95f);
            titleRect.offsetMin = Vector2.zero;
            titleRect.offsetMax = Vector2.zero;

            _detailText = CreateText("Detail", panelGo.transform, TextAnchor.MiddleCenter, 30, FontStyle.Normal);
            var detailRect = _detailText.GetComponent<RectTransform>();
            detailRect.anchorMin = new Vector2(0.05f, 0.30f);
            detailRect.anchorMax = new Vector2(0.95f, 0.70f);
            detailRect.offsetMin = Vector2.zero;
            detailRect.offsetMax = Vector2.zero;

            _hotspotText = CreateText("Hotspot", panelGo.transform, TextAnchor.LowerCenter, 24, FontStyle.Italic);
            var hotspotRect = _hotspotText.GetComponent<RectTransform>();
            hotspotRect.anchorMin = new Vector2(0.05f, 0.05f);
            hotspotRect.anchorMax = new Vector2(0.95f, 0.25f);
            hotspotRect.offsetMin = Vector2.zero;
            hotspotRect.offsetMax = Vector2.zero;
        }

        private static Text CreateText(string name, Transform parent, TextAnchor anchor, int size, FontStyle style)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var text = go.AddComponent<Text>();
            text.alignment = anchor;
            text.resizeTextForBestFit = true;
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize = size;
            text.fontStyle = style;
            text.color = Color.white;
            return text;
        }

        private static string ResolveActionText(ActionPlanAction action, string fallback)
        {
            if (action == null)
            {
                return fallback;
            }
            var fromPayload = action.payload != null ? action.payload.text : string.Empty;
            if (!string.IsNullOrWhiteSpace(fromPayload))
            {
                return fromPayload.Trim();
            }
            if (!string.IsNullOrWhiteSpace(action.reason))
            {
                return action.reason.Trim();
            }
            return fallback;
        }
    }
}
