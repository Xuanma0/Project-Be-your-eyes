using System;
using BYES.Core;
using BYES.UI;
using BeYourEyes.Unity.Interaction;
using BYES.XR;
using UnityEngine;
using UnityEngine.UI;

namespace BYES.Quest
{
    public sealed class ByesWristMenuController : MonoBehaviour
    {
        [SerializeField] private bool createRuntimeUi = true;
        [SerializeField] private bool startVisible;
        [SerializeField] private float menuWidth = 640f;
        [SerializeField] private float menuHeight = 760f;
        [SerializeField] private float uiScale = 0.0006f;

        private Canvas _canvas;
        private GameObject[] _pages;
        private Text _feedbackText;
        private Text _titleText;

        private ByesQuest3ConnectionPanelMinimal _panel;
        private ScanController _scanController;
        private ByesQuest3SelfTestRunner _selfTestRunner;
        private ByesWristMenuAnchor _anchor;

        private void Awake()
        {
            ResolveRefs();
            if (createRuntimeUi)
            {
                BuildRuntimeUi();
                SetVisible(startVisible);
            }
        }

        private void ResolveRefs()
        {
            if (_panel == null)
            {
                _panel = FindFirstObjectByType<ByesQuest3ConnectionPanelMinimal>();
            }

            if (_scanController == null)
            {
                _scanController = FindFirstObjectByType<ScanController>();
            }

            if (_selfTestRunner == null)
            {
                _selfTestRunner = FindFirstObjectByType<ByesQuest3SelfTestRunner>();
            }

            if (_anchor == null)
            {
                _anchor = GetComponent<ByesWristMenuAnchor>();
            }
        }

        public void SetVisible(bool visible)
        {
            if (_canvas != null)
            {
                _canvas.enabled = visible;
            }
        }

        public bool IsVisible()
        {
            return _canvas != null && _canvas.enabled;
        }

        public void ToggleVisible()
        {
            SetVisible(!IsVisible());
        }

        private void BuildRuntimeUi()
        {
            if (GetComponentInChildren<Canvas>(includeInactive: true) != null)
            {
                _canvas = GetComponentInChildren<Canvas>(includeInactive: true);
                return;
            }

            var canvasGo = new GameObject("WristMenuCanvas", typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler));
            canvasGo.transform.SetParent(transform, false);
            _canvas = canvasGo.GetComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.worldCamera = Camera.main;
            _canvas.sortingOrder = 6000;

            var rect = canvasGo.GetComponent<RectTransform>();
            rect.sizeDelta = new Vector2(menuWidth, menuHeight);
            rect.localScale = Vector3.one * uiScale;
            rect.localPosition = Vector3.zero;
            rect.localRotation = Quaternion.identity;

            var trackedRaycasterType = Type.GetType("UnityEngine.XR.Interaction.Toolkit.UI.TrackedDeviceGraphicRaycaster, Unity.XR.Interaction.Toolkit");
            if (trackedRaycasterType != null)
            {
                canvasGo.AddComponent(trackedRaycasterType);
            }
            else
            {
                canvasGo.AddComponent<GraphicRaycaster>();
            }

            var panelGo = CreateUiObject("RootPanel", canvasGo.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(menuWidth, menuHeight), Vector2.zero);
            var panelImage = panelGo.AddComponent<Image>();
            panelImage.color = new Color(0f, 0f, 0f, 0.75f);
            var group = panelGo.AddComponent<CanvasGroup>();
            group.interactable = true;
            group.blocksRaycasts = true;

            _titleText = CreateText("Title", panelGo.transform, "BYES Wrist Menu", 36, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -40f), new Vector2(menuWidth - 20f, 60f));
            _feedbackText = CreateText("Feedback", panelGo.transform, "-", 24, TextAnchor.MiddleLeft, new Vector2(0.5f, 0f), new Vector2(0f, 25f), new Vector2(menuWidth - 30f, 44f));

            CreateTabButton(panelGo.transform, "ActionsTab", "Actions", new Vector2(-180f, -95f), () => SwitchPage(0));
            CreateTabButton(panelGo.transform, "PanelsTab", "Panels", new Vector2(0f, -95f), () => SwitchPage(1));
            CreateTabButton(panelGo.transform, "DebugTab", "Debug", new Vector2(180f, -95f), () => SwitchPage(2));

            _pages = new GameObject[3];
            _pages[0] = CreatePage(panelGo.transform, "ActionsPage");
            _pages[1] = CreatePage(panelGo.transform, "PanelsPage");
            _pages[2] = CreatePage(panelGo.transform, "DebugPage");

            BuildActionsPage(_pages[0].transform);
            BuildPanelsPage(_pages[1].transform);
            BuildDebugPage(_pages[2].transform);

            SwitchPage(0);
        }

        private static GameObject CreatePage(Transform parent, string name)
        {
            return CreateUiObject(name, parent, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(600f, 520f), new Vector2(0f, -20f));
        }

        private void BuildActionsPage(Transform page)
        {
            CreateMenuButton(page, "ScanOnce", "Scan Once", new Vector2(0f, 180f), () =>
            {
                ResolveRefs();
                if (_panel != null)
                {
                    _panel.TriggerScanOnceFromUi();
                    SetFeedback("Scan once requested");
                    return;
                }

                if (_scanController != null)
                {
                    _scanController.ScanOnceFromUi();
                    SetFeedback("Scan once requested");
                    return;
                }

                SetFeedback("Scan controller missing");
            });

            CreateMenuButton(page, "LiveToggle", "Live Toggle", new Vector2(0f, 95f), () =>
            {
                ResolveRefs();
                if (_panel != null)
                {
                    _panel.TriggerToggleLiveFromUi();
                    SetFeedback("Live toggled");
                    return;
                }

                if (_scanController != null)
                {
                    _scanController.ToggleLiveFromUi();
                    SetFeedback("Live toggled");
                    return;
                }

                SetFeedback("Scan controller missing");
            });

            CreateMenuButton(page, "CycleMode", "Cycle Mode", new Vector2(0f, 10f), () =>
            {
                ResolveRefs();
                if (_panel != null)
                {
                    _panel.TriggerCycleMode();
                    SetFeedback("Mode cycled");
                    return;
                }

                var modeManager = ByesModeManager.Instance;
                if (modeManager == null)
                {
                    SetFeedback("Mode manager missing");
                    return;
                }

                var current = modeManager.GetMode();
                var next = current switch
                {
                    ByesMode.Walk => ByesMode.ReadText,
                    ByesMode.ReadText => ByesMode.Inspect,
                    _ => ByesMode.Walk,
                };
                modeManager.SetMode(next, "xr");
                SetFeedback("Mode cycled");
            });
        }

        private void BuildPanelsPage(Transform page)
        {
            CreateMenuButton(page, "TogglePanel", "Toggle Smoke Panel", new Vector2(0f, 180f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.SetPanelVisible(!_panel.IsPanelVisible());
                SetFeedback("Smoke panel toggled");
            });

            CreateMenuButton(page, "ToggleOverlay", "Toggle Overlay", new Vector2(0f, 95f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.ToggleOverlayVisible();
                SetFeedback("Overlay toggled");
            });

            CreateMenuButton(page, "ToggleDebug", "Toggle Debug Text", new Vector2(0f, 10f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.ToggleRawDebugText();
                SetFeedback("Debug text toggled");
            });

            CreateMenuButton(page, "PinToggle", "Pin / Unpin", new Vector2(0f, -75f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.SetPinned(!_panel.IsPinned());
                SetFeedback(_panel.IsPinned() ? "Panel pinned" : "Panel unpinned");
            });

            CreateMenuButton(page, "Snap", "Snap Default", new Vector2(-140f, -160f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.SnapToDefaultPose();
                SetFeedback("Snapped to default");
            });

            CreateMenuButton(page, "Distance+", "Distance +", new Vector2(30f, -160f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.SetPanelDistance(_panel.GetPanelDistance() + 0.05f);
                SetFeedback($"Distance={_panel.GetPanelDistance():0.00}m");
            });

            CreateMenuButton(page, "Distance-", "Distance -", new Vector2(210f, -160f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.SetPanelDistance(_panel.GetPanelDistance() - 0.05f);
                SetFeedback($"Distance={_panel.GetPanelDistance():0.00}m");
            });

            CreateMenuButton(page, "Scale+", "Scale +", new Vector2(-140f, -245f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.SetPanelScale(_panel.GetPanelScale() + 0.1f);
                SetFeedback($"Scale={_panel.GetPanelScale():0.00}x");
            });

            CreateMenuButton(page, "Scale-", "Scale -", new Vector2(30f, -245f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.SetPanelScale(_panel.GetPanelScale() - 0.1f);
                SetFeedback($"Scale={_panel.GetPanelScale():0.00}x");
            });

            CreateMenuButton(page, "WristSide", "Switch Wrist", new Vector2(210f, -245f), () =>
            {
                ResolveRefs();
                if (_anchor == null)
                {
                    SetFeedback("Wrist anchor missing");
                    return;
                }

                _anchor.ToggleAnchorHand();
                SetFeedback(_anchor.AttachToLeftWrist ? "Anchor: LEFT wrist" : "Anchor: RIGHT wrist");
            });
        }

        private void BuildDebugPage(Transform page)
        {
            CreateMenuButton(page, "Ping", "Ping", new Vector2(0f, 180f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.TriggerPingFromUi();
                SetFeedback("Ping requested");
            });

            CreateMenuButton(page, "Version", "Get Version", new Vector2(0f, 95f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.TriggerVersionFromUi();
                SetFeedback("Version requested");
            });

            CreateMenuButton(page, "Mode", "Read Mode", new Vector2(0f, 10f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                _panel.TriggerModeReadFromUi();
                SetFeedback("Mode requested");
            });

            CreateMenuButton(page, "SelfTest", "Run SelfTest", new Vector2(0f, -75f), () =>
            {
                ResolveRefs();
                if (_panel != null)
                {
                    _panel.TriggerSelfTestFromUi();
                    SetFeedback("SelfTest started");
                    return;
                }

                if (_selfTestRunner != null)
                {
                    _selfTestRunner.StartSelfTest();
                    SetFeedback("SelfTest started");
                    return;
                }

                SetFeedback("SelfTest runner missing");
            });

            CreateMenuButton(page, "Export", "Export Debug Text", new Vector2(0f, -160f), () =>
            {
                ResolveRefs();
                if (_panel == null)
                {
                    SetFeedback("Smoke panel missing");
                    return;
                }

                var path = _panel.ExportDebugText();
                SetFeedback(string.IsNullOrWhiteSpace(path) ? "Export failed" : "Exported");
            });
        }

        private void SwitchPage(int pageIndex)
        {
            if (_pages == null)
            {
                return;
            }

            for (var i = 0; i < _pages.Length; i += 1)
            {
                if (_pages[i] != null)
                {
                    _pages[i].SetActive(i == pageIndex);
                }
            }
        }

        private void SetFeedback(string message)
        {
            if (_feedbackText == null)
            {
                return;
            }

            _feedbackText.text = string.IsNullOrWhiteSpace(message) ? "-" : message.Trim();
        }

        private static GameObject CreateUiObject(
            string name,
            Transform parent,
            Vector2 anchorMin,
            Vector2 anchorMax,
            Vector2 size,
            Vector2 anchoredPos)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            var rect = go.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.sizeDelta = size;
            rect.anchoredPosition = anchoredPos;
            return go;
        }

        private static Text CreateText(
            string name,
            Transform parent,
            string value,
            int fontSize,
            TextAnchor alignment,
            Vector2 anchor,
            Vector2 anchoredPos,
            Vector2 size)
        {
            var go = CreateUiObject(name, parent, anchor, anchor, size, anchoredPos);
            var text = go.AddComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.color = Color.white;
            text.alignment = alignment;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Truncate;
            text.resizeTextForBestFit = false;
            text.fontSize = fontSize;
            text.text = value ?? string.Empty;
            return text;
        }

        private static void CreateTabButton(Transform parent, string name, string label, Vector2 anchoredPos, Action onClick)
        {
            CreateMenuButton(parent, name, label, anchoredPos, onClick, new Vector2(170f, 52f), 24, new Color(0.18f, 0.35f, 0.68f, 0.95f));
        }

        private static void CreateMenuButton(Transform parent, string name, string label, Vector2 anchoredPos, Action onClick)
        {
            CreateMenuButton(parent, name, label, anchoredPos, onClick, new Vector2(340f, 62f), 27, new Color(0.21f, 0.54f, 0.91f, 0.95f));
        }

        private static void CreateMenuButton(
            Transform parent,
            string name,
            string label,
            Vector2 anchoredPos,
            Action onClick,
            Vector2 size,
            int labelSize,
            Color color)
        {
            var go = CreateUiObject(name, parent, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), size, anchoredPos);
            var image = go.AddComponent<Image>();
            image.color = color;
            var button = go.AddComponent<Button>();
            button.targetGraphic = image;
            button.onClick.AddListener(() => onClick?.Invoke());

            var text = CreateText("Label", go.transform, label, labelSize, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), Vector2.zero, size - new Vector2(12f, 8f));
            text.raycastTarget = false;
        }
    }
}
