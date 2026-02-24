using System;
using BYES.Core;
using BYES.Telemetry;
using BeYourEyes.Adapters.Networking;
using UnityEngine;
using UnityEngine.UI;

namespace BYES.UI
{
    public sealed class ByesConfirmPanel : MonoBehaviour
    {
        private static ByesConfirmPanel _instance;

        private Canvas _canvas;
        private GameObject _panel;
        private Text _promptText;
        private Text _countdownText;
        private Text _hintText;

        private GatewayClient _gatewayClient;
        private string _runId = "unknown-run";
        private int _frameSeq = 1;
        private string _confirmId = string.Empty;
        private float _deadlineRealtimeSec;
        private bool _visible;
        private bool _submitted;
        private Action<string, bool> _onDecision;

        public static ByesConfirmPanel Instance => EnsureExists();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            _ = EnsureExists();
        }

        public static ByesConfirmPanel EnsureExists()
        {
            if (_instance != null)
            {
                return _instance;
            }

            var existing = FindFirstObjectByType<ByesConfirmPanel>();
            if (existing != null)
            {
                _instance = existing;
                DontDestroyOnLoad(_instance.gameObject);
                return _instance;
            }

            var root = new GameObject("BYES_ConfirmPanel");
            DontDestroyOnLoad(root);
            _instance = root.AddComponent<ByesConfirmPanel>();
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
            if (!_visible || _submitted)
            {
                return;
            }

            if (Input.GetKeyDown(KeyCode.Y))
            {
                SubmitDecision(true, "keyboard_yes");
                return;
            }
            if (Input.GetKeyDown(KeyCode.N))
            {
                SubmitDecision(false, "keyboard_no");
                return;
            }

            var remaining = Mathf.Max(0f, _deadlineRealtimeSec - Time.realtimeSinceStartup);
            if (_countdownText != null)
            {
                _countdownText.text = $"Timeout in {Mathf.CeilToInt(remaining)}s";
            }

            if (remaining <= 0f)
            {
                SubmitDecision(false, "timeout");
            }
        }

        public void ShowConfirm(
            string runId,
            int frameSeq,
            string confirmId,
            string prompt,
            int timeoutMs,
            Action<string, bool> onDecision = null
        )
        {
            EnsureUi();
            _runId = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim();
            _frameSeq = Mathf.Max(1, frameSeq);
            _confirmId = string.IsNullOrWhiteSpace(confirmId) ? $"confirm-{_frameSeq}" : confirmId.Trim();
            _onDecision = onDecision;
            _submitted = false;

            var timeoutSec = Mathf.Max(1f, Mathf.Max(1000, timeoutMs) / 1000f);
            _deadlineRealtimeSec = Time.realtimeSinceStartup + timeoutSec;

            if (_promptText != null)
            {
                _promptText.text = string.IsNullOrWhiteSpace(prompt) ? "Please confirm." : prompt.Trim();
            }
            if (_hintText != null)
            {
                _hintText.text = "Press Y to accept / N to reject  (XR input TODO)";
            }
            if (_countdownText != null)
            {
                _countdownText.text = $"Timeout in {Mathf.CeilToInt(timeoutSec)}s";
            }
            if (_canvas != null)
            {
                _canvas.enabled = true;
            }
            if (_panel != null)
            {
                _panel.SetActive(true);
            }
            _visible = true;

            var state = ByesSystemState.Instance;
            if (state != null)
            {
                state.SetPendingConfirm(1, _confirmId);
            }
        }

        private void SubmitDecision(bool accepted, string source)
        {
            if (_submitted)
            {
                return;
            }

            _submitted = true;
            _visible = false;
            Hide();

            var state = ByesSystemState.Instance;
            if (state != null)
            {
                state.SetPendingConfirm(0, _confirmId);
            }

            ResolveGatewayClient();
            if (_gatewayClient != null)
            {
                _gatewayClient.SendConfirmResponseV1(
                    _runId,
                    _frameSeq,
                    _confirmId,
                    accepted,
                    runPackage: null,
                    source: source,
                    onDone: (ok, message) =>
                    {
                        Debug.Log($"[ByesConfirmPanel] confirm_response id={_confirmId} accepted={accepted} ok={ok} msg={message}");
                    }
                );
            }
            else
            {
                Debug.LogWarning("[ByesConfirmPanel] GatewayClient not found, confirm_response not sent");
            }

            ByesFrameTelemetry.AckFeedback(_runId, _frameSeq, "ar", accepted, ByesFrameTelemetry.NowUnixMs());
            _onDecision?.Invoke(_confirmId, accepted);
            _onDecision = null;
        }

        private void ResolveGatewayClient()
        {
            if (_gatewayClient != null)
            {
                return;
            }

            _gatewayClient = FindFirstObjectByType<GatewayClient>();
        }

        private void Hide()
        {
            if (_panel != null)
            {
                _panel.SetActive(false);
            }
            if (_canvas != null)
            {
                _canvas.enabled = false;
            }
            _visible = false;
        }

        private void EnsureUi()
        {
            if (_canvas != null)
            {
                return;
            }

            var canvasGo = new GameObject("BYES_ConfirmCanvas");
            canvasGo.transform.SetParent(transform, false);
            _canvas = canvasGo.AddComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.worldCamera = Camera.main;
            canvasGo.AddComponent<CanvasScaler>();
            canvasGo.AddComponent<GraphicRaycaster>();

            var canvasRect = canvasGo.GetComponent<RectTransform>();
            canvasRect.sizeDelta = new Vector2(760f, 360f);
            canvasRect.localScale = Vector3.one * 0.0025f;
            canvasRect.localPosition = new Vector3(0f, -0.2f, 2.0f);

            _panel = new GameObject("ConfirmPanel");
            _panel.transform.SetParent(canvasGo.transform, false);
            var panelImage = _panel.AddComponent<Image>();
            panelImage.color = new Color(0f, 0f, 0f, 0.85f);
            var panelRect = _panel.GetComponent<RectTransform>();
            panelRect.anchorMin = new Vector2(0f, 0f);
            panelRect.anchorMax = new Vector2(1f, 1f);
            panelRect.offsetMin = Vector2.zero;
            panelRect.offsetMax = Vector2.zero;

            _promptText = CreateText("Prompt", _panel.transform, TextAnchor.UpperCenter, FontStyle.Bold, 34);
            var promptRect = _promptText.GetComponent<RectTransform>();
            promptRect.anchorMin = new Vector2(0.05f, 0.50f);
            promptRect.anchorMax = new Vector2(0.95f, 0.90f);
            promptRect.offsetMin = Vector2.zero;
            promptRect.offsetMax = Vector2.zero;

            _countdownText = CreateText("Countdown", _panel.transform, TextAnchor.MiddleCenter, FontStyle.Normal, 30);
            var countdownRect = _countdownText.GetComponent<RectTransform>();
            countdownRect.anchorMin = new Vector2(0.05f, 0.30f);
            countdownRect.anchorMax = new Vector2(0.95f, 0.50f);
            countdownRect.offsetMin = Vector2.zero;
            countdownRect.offsetMax = Vector2.zero;

            _hintText = CreateText("Hints", _panel.transform, TextAnchor.LowerCenter, FontStyle.Italic, 24);
            var hintRect = _hintText.GetComponent<RectTransform>();
            hintRect.anchorMin = new Vector2(0.05f, 0.08f);
            hintRect.anchorMax = new Vector2(0.95f, 0.28f);
            hintRect.offsetMin = Vector2.zero;
            hintRect.offsetMax = Vector2.zero;
        }

        private static Text CreateText(string name, Transform parent, TextAnchor anchor, FontStyle style, int size)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            var text = go.AddComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.color = Color.white;
            text.fontStyle = style;
            text.fontSize = size;
            text.alignment = anchor;
            text.resizeTextForBestFit = true;
            return text;
        }
    }
}
