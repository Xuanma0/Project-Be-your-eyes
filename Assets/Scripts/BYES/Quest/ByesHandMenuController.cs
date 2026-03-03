using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using BYES.Core;
using BYES.UI;
using BYES.XR;
using BeYourEyes.Unity.Interaction;
using UnityEngine;
using UnityEngine.Events;
using UnityEngine.InputSystem;
using UnityEngine.UI;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
using UnityEngine.XR.Interaction.Toolkit.Samples.Hands;
using UnityEngine.XR.Interaction.Toolkit.UI.BodyUI;

namespace BYES.Quest
{
    public sealed class ByesHandMenuController : MonoBehaviour
    {
        private const string PrefShowFullPanel = "BYES_HANDMENU_SHOW_FULL_PANEL";
        private const string PrefGestureEnabled = "BYES_HANDMENU_GESTURES_ENABLED";
        private const string PrefShortcutHand = "BYES_HANDMENU_SHORTCUT_HAND";
        private const string PrefConflictMode = "BYES_HANDMENU_CONFLICT_MODE";
        private const string PrefMenuHand = "BYES_HANDMENU_MENU_HAND";
        private const string PrefUiScale = "BYES_HANDMENU_UI_SCALE";
        private const string PrefPassthrough = "BYES_HANDMENU_PASSTHROUGH";
        private const string PrefLockToHead = "BYES_HANDMENU_LOCK_TO_HEAD";
        private const string PrefMoveResize = "BYES_HANDMENU_MOVE_RESIZE";

        [SerializeField] private float baseUiScale = 0.00038f;
        [SerializeField] private float refreshIntervalSec = 0.75f;
        [SerializeField] private bool disableCompetingTemplateMenus = true;
        [SerializeField] private float defaultGazeDivergenceThresholdDeg = 120f;

        private HandMenu _handMenu;
        private MetaSystemGestureDetector _metaGestureDetector;
        private GameObject _menuHost;
        private Canvas _canvas;
        private GameObject _rootPanel;

        private ByesQuest3ConnectionPanelMinimal _panel;
        private ByesHandGestureShortcuts _shortcuts;
        private ByesQuest3SelfTestRunner _selfTestRunner;
        private ByesQuestPassthroughSetup _passthroughSetup;

        private readonly Dictionary<string, GameObject> _pages = new Dictionary<string, GameObject>();
        private readonly Dictionary<Text, string> _textCache = new Dictionary<Text, string>();
        private readonly StringBuilder _sb = new StringBuilder(512);

        private Text _feedbackText;
        private Text _connectionText;
        private Text _modeText;
        private Text _settingsText;
        private Text _debugText;
        private Text _scaleText;

        private Toggle _showFullPanelToggle;
        private Toggle _gestureEnabledToggle;
        private Toggle _passthroughToggle;
        private Toggle _lockToHeadToggle;
        private Toggle _moveResizeToggle;
        private Toggle _autoSpeakOcrToggle;
        private Toggle _autoSpeakDetToggle;
        private Toggle _autoSpeakRiskToggle;
        private Toggle _autoSpeakFindToggle;
        private Toggle _autoGuidanceToggle;
        private Toggle _guidanceAudioToggle;
        private Toggle _guidanceHapticsToggle;
        private Toggle _ocrVerboseToggle;
        private Slider _uiScaleSlider;

        private bool _systemGestureActive;
        private bool _uiSuppressed;
        private Coroutine _refreshRoutine;

        private enum MenuHandPref
        {
            Left = 1,
            Right = 2,
            Either = 3,
        }

        private void Awake()
        {
            ResolveRefs();
            EnsureOfficialHandMenu();
            TryEnsureMetaGestureDetector();
            BuildRuntimeUi();
            LoadPrefsAndApply();
            SetPage("home");
        }

        private void OnEnable()
        {
            ResolveRefs();
            if (_shortcuts != null)
            {
                _shortcuts.OnShortcutTriggered -= HandleShortcutTriggered;
                _shortcuts.OnShortcutTriggered += HandleShortcutTriggered;
            }

            if (_refreshRoutine == null)
            {
                _refreshRoutine = StartCoroutine(RefreshLoop());
            }
        }

        private void OnDisable()
        {
            if (_shortcuts != null)
            {
                _shortcuts.OnShortcutTriggered -= HandleShortcutTriggered;
            }

            if (_refreshRoutine != null)
            {
                StopCoroutine(_refreshRoutine);
                _refreshRoutine = null;
            }
        }

        public bool IsMenuVisible() => _rootPanel != null && _rootPanel.activeInHierarchy;
        public bool IsSystemGestureActive() => _systemGestureActive;

        private void ResolveRefs()
        {
            _panel ??= FindFirstObjectByType<ByesQuest3ConnectionPanelMinimal>();
            _shortcuts ??= FindFirstObjectByType<ByesHandGestureShortcuts>();
            _selfTestRunner ??= FindFirstObjectByType<ByesQuest3SelfTestRunner>();
            _passthroughSetup ??= ByesQuestPassthroughSetup.Instance;
        }

        private void EnsureOfficialHandMenu()
        {
            _handMenu = GetComponentInChildren<HandMenu>(true);
            if (_handMenu == null)
            {
                _handMenu = gameObject.AddComponent<HandMenu>();
            }

            var previousMenuHost = _handMenu.handMenuUIGameObject;
            Transform hostParent = null;
            if (previousMenuHost != null && previousMenuHost.transform.parent != null)
            {
                hostParent = previousMenuHost.transform.parent;
            }

            if (hostParent == null)
            {
                var followNode = transform.Find("OfficialHandMenuRig/Follow GameObject") ?? transform.Find("Follow GameObject");
                if (followNode != null)
                {
                    hostParent = followNode;
                }
            }

            if (hostParent == null)
            {
                hostParent = transform;
            }

            var byesHost = hostParent.Find("BYES_HandMenuUIRoot");
            if (byesHost == null)
            {
                var created = new GameObject("BYES_HandMenuUIRoot");
                created.transform.SetParent(hostParent, false);
                _menuHost = created;
            }
            else
            {
                _menuHost = byesHost.gameObject;
            }

            _handMenu.handMenuUIGameObject = _menuHost;
            _handMenu.handMenuUpDirection = HandMenu.UpDirection.CameraUp;
            _handMenu.menuHandedness = HandMenu.MenuHandedness.Either;
            _handMenu.menuVisibleGazeDivergenceThreshold = Mathf.Clamp(defaultGazeDivergenceThresholdDeg, 15f, 180f);

            if (disableCompetingTemplateMenus)
            {
                DisableCompetingMenus(previousMenuHost);
            }
        }

        private void TryEnsureMetaGestureDetector()
        {
            try
            {
                // Reuse detector from the official HandMenuRig sample. Avoid creating one at runtime,
                // which can be partially uninitialized on device and break startup.
                _metaGestureDetector = GetComponentInChildren<MetaSystemGestureDetector>(true);
                if (_metaGestureDetector == null)
                {
                    Debug.LogWarning("[ByesHandMenuController] MetaSystemGestureDetector not found. System-gesture conflict isolation disabled.");
                    return;
                }

                var started = _metaGestureDetector.systemGestureStarted;
                if (started == null)
                {
                    started = new UnityEvent();
                    _metaGestureDetector.systemGestureStarted = started;
                }

                var ended = _metaGestureDetector.systemGestureEnded;
                if (ended == null)
                {
                    ended = new UnityEvent();
                    _metaGestureDetector.systemGestureEnded = ended;
                }

                started.RemoveListener(OnSystemGestureStarted);
                started.AddListener(OnSystemGestureStarted);

                ended.RemoveListener(OnSystemGestureEnded);
                ended.AddListener(OnSystemGestureEnded);
            }
            catch (Exception ex)
            {
                // Never allow menu wiring to crash app startup on device.
                _metaGestureDetector = null;
                Debug.LogWarning("[ByesHandMenuController] Failed to wire MetaSystemGestureDetector safely: " + ex.Message);
            }
        }

        private void BuildRuntimeUi()
        {
            if (_menuHost == null)
            {
                return;
            }

            _canvas = _menuHost.GetComponentInChildren<Canvas>(true);
            if (_canvas != null && _canvas.gameObject.name == "BYES_HandMenuCanvas")
            {
                _rootPanel = _canvas.transform.Find("PanelRoot")?.gameObject;
                return;
            }

            var canvasGo = new GameObject("BYES_HandMenuCanvas", typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler));
            canvasGo.transform.SetParent(_menuHost.transform, false);
            _canvas = canvasGo.GetComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.worldCamera = Camera.main;
            _canvas.sortingOrder = 6200;
            var rect = canvasGo.GetComponent<RectTransform>();
            rect.sizeDelta = new Vector2(960f, 1300f);
            rect.localScale = Vector3.one * baseUiScale;

            var trackedType = Type.GetType("UnityEngine.XR.Interaction.Toolkit.UI.TrackedDeviceGraphicRaycaster, Unity.XR.Interaction.Toolkit");
            if (trackedType != null)
            {
                canvasGo.AddComponent(trackedType);
            }
            else
            {
                canvasGo.AddComponent<GraphicRaycaster>();
            }

            _rootPanel = CreateUiObject("PanelRoot", canvasGo.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(920f, 1260f), Vector2.zero);
            var bg = _rootPanel.AddComponent<Image>();
            bg.color = new Color(0f, 0f, 0f, 0.82f);
            var cg = _rootPanel.AddComponent<CanvasGroup>();
            cg.blocksRaycasts = true;
            cg.interactable = true;

            _ = CreateText("Hint", _rootPanel.transform, "Flip wrist palm-up to open menu (no pinch needed)", 28, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -34f), new Vector2(820f, 48f));
            _feedbackText = CreateText("Feedback", _rootPanel.transform, "-", 22, TextAnchor.MiddleLeft, new Vector2(0.5f, 0f), new Vector2(0f, 20f), new Vector2(820f, 40f));

            BuildPages(_rootPanel.transform);
        }

        private void BuildPages(Transform root)
        {
            _pages["home"] = CreatePage(root, "Home");
            _pages["connection"] = CreatePage(root, "Connection");
            _pages["actions"] = CreatePage(root, "Actions");
            _pages["mode"] = CreatePage(root, "Mode");
            _pages["panels"] = CreatePage(root, "Panels");
            _pages["settings"] = CreatePage(root, "Settings");
            _pages["debug"] = CreatePage(root, "Debug");

            BuildHome(_pages["home"].transform);
            BuildConnection(_pages["connection"].transform);
            BuildActions(_pages["actions"].transform);
            BuildMode(_pages["mode"].transform);
            BuildPanels(_pages["panels"].transform);
            BuildSettings(_pages["settings"].transform);
            BuildDebug(_pages["debug"].transform);
        }

        private GameObject CreatePage(Transform root, string title)
        {
            var page = CreateUiObject("Page_" + title, root, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(860f, 1120f), new Vector2(0f, -34f));
            _ = CreateText("Title", page.transform, title, 30, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -40f), new Vector2(760f, 50f));
            return page;
        }

        private void BuildHome(Transform page)
        {
            CreateButton(page, "Connection", new Vector2(-200f, 200f), () => { SetPage("connection"); SetFeedback("Connection page"); });
            CreateButton(page, "Actions", new Vector2(0f, 200f), () => { SetPage("actions"); SetFeedback("Actions page"); });
            CreateButton(page, "Mode", new Vector2(200f, 200f), () => { SetPage("mode"); SetFeedback("Mode page"); });
            CreateButton(page, "Panels", new Vector2(-200f, 120f), () => { SetPage("panels"); SetFeedback("Panels page"); });
            CreateButton(page, "Settings", new Vector2(0f, 120f), () => { SetPage("settings"); SetFeedback("Settings page"); });
            CreateButton(page, "Debug", new Vector2(200f, 120f), () => { SetPage("debug"); SetFeedback("Debug page"); });
        }

        private void BuildConnection(Transform page)
        {
            _connectionText = CreateText("Info", page, "-", 22, TextAnchor.UpperLeft, new Vector2(0.5f, 0.5f), new Vector2(0f, 110f), new Vector2(760f, 160f));
            _showFullPanelToggle = CreateToggle(page, "Open Full Connection Panel", new Vector2(0f, 10f), value =>
            {
                PlayerPrefs.SetInt(PrefShowFullPanel, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetActionControlsVisible(value);
                SetFeedback("Full panel " + (value ? "ON" : "OFF"));
            });
            CreateButton(page, "Refresh", new Vector2(-120f, -120f), () => { _panel?.TriggerRefreshFromUi(); SetFeedback("Connection refresh"); });
            CreateButton(page, "Back", new Vector2(120f, -120f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private void BuildActions(Transform page)
        {
            CreateButton(page, "Scan Once", new Vector2(0f, 190f), () => { _panel?.TriggerScanOnceFromUi(); SetFeedback("Scan once"); });
            CreateButton(page, "Live Toggle", new Vector2(0f, 110f), () => { _panel?.TriggerToggleLiveFromUi(); SetFeedback("Live toggled"); });
            CreateButton(page, "Read Text Once", new Vector2(0f, 30f), () => { _panel?.TriggerReadTextOnceFromUi(); SetFeedback("OCR once"); });
            CreateButton(page, "Detect Once", new Vector2(0f, -50f), () => { _panel?.TriggerDetectObjectsOnceFromUi(); SetFeedback("DET once"); });
            CreateButton(page, "Run SelfTest", new Vector2(-260f, -130f), () => { _panel?.TriggerSelfTestFromUi(); SetFeedback("SelfTest started"); });
            CreateButton(page, "Rec Start", new Vector2(0f, -130f), () => { _panel?.TriggerStartRecordFromUi(); SetFeedback("Record start"); });
            CreateButton(page, "Rec Stop", new Vector2(260f, -130f), () => { _panel?.TriggerStopRecordFromUi(); SetFeedback("Record stop"); });

            CreateButton(page, "Find Door", new Vector2(-260f, -210f), () => { _panel?.TriggerFindConceptFromUi("door"); SetFeedback("Find door"); });
            CreateButton(page, "Find Exit", new Vector2(0f, -210f), () => { _panel?.TriggerFindConceptFromUi("exit sign"); SetFeedback("Find exit sign"); });
            CreateButton(page, "Find Stairs", new Vector2(260f, -210f), () => { _panel?.TriggerFindConceptFromUi("stairs"); SetFeedback("Find stairs"); });
            CreateButton(page, "Find Elevator", new Vector2(-260f, -290f), () => { _panel?.TriggerFindConceptFromUi("elevator"); SetFeedback("Find elevator"); });
            CreateButton(page, "Find Restroom", new Vector2(0f, -290f), () => { _panel?.TriggerFindConceptFromUi("restroom"); SetFeedback("Find restroom"); });
            CreateButton(page, "Find Person", new Vector2(260f, -290f), () => { _panel?.TriggerFindConceptFromUi("person"); SetFeedback("Find person"); });
            CreateButton(page, "Select ROI", new Vector2(-260f, -370f), () => { _panel?.TriggerSelectRoiFromUi(); SetFeedback("ROI selected"); });
            CreateButton(page, "Start Track", new Vector2(0f, -370f), () => { _panel?.TriggerStartTrackFromUi(); SetFeedback("Track start"); });
            CreateButton(page, "Track Step", new Vector2(260f, -370f), () => { _panel?.TriggerTrackStepFromUi(); SetFeedback("Track step"); });
            CreateButton(page, "Stop Track", new Vector2(-260f, -450f), () => { _panel?.TriggerStopTrackFromUi(); SetFeedback("Track stop"); });
            CreateButton(page, "Export Debug", new Vector2(0f, -450f), () => { _panel?.ExportDebugText(); SetFeedback("Debug exported"); });
            CreateButton(page, "Back", new Vector2(260f, -450f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private void BuildMode(Transform page)
        {
            _modeText = CreateText("Mode", page, "Mode: -", 24, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, 170f), new Vector2(760f, 42f));
            CreateButton(page, "Walk", new Vector2(-200f, 60f), () => { _panel?.TriggerSetModeWalk(); SetFeedback("Mode -> walk"); });
            CreateButton(page, "Read", new Vector2(0f, 60f), () => { _panel?.TriggerSetModeRead(); SetFeedback("Mode -> read_text"); });
            CreateButton(page, "Inspect", new Vector2(200f, 60f), () => { _panel?.TriggerSetModeInspect(); SetFeedback("Mode -> inspect"); });
            CreateButton(page, "Readback", new Vector2(-120f, -60f), () => { _panel?.TriggerModeReadFromUi(); SetFeedback("Mode readback"); });
            CreateButton(page, "Cycle", new Vector2(120f, -60f), () => { _panel?.TriggerCycleMode(); SetFeedback("Mode cycle"); });
            CreateButton(page, "Back", new Vector2(0f, -180f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private void BuildPanels(Transform page)
        {
            CreateToggle(page, "Smoke Panel Visible", new Vector2(0f, 170f), value =>
            {
                _panel?.SetPanelVisible(value);
                SetFeedback("Panel visible " + (value ? "ON" : "OFF"));
            });
            _lockToHeadToggle = CreateToggle(page, "Smoke Panel LockToHead", new Vector2(0f, 90f), value =>
            {
                PlayerPrefs.SetInt(PrefLockToHead, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetLockToHead(value);
                SetFeedback("LockToHead " + (value ? "ON" : "OFF"));
            });
            _moveResizeToggle = CreateToggle(page, "Enable Move/Resize", new Vector2(0f, 10f), value =>
            {
                PlayerPrefs.SetInt(PrefMoveResize, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetMoveResizeEnabled(value);
                SetFeedback("Move/Resize " + (value ? "ON" : "OFF"));
            });
            CreateButton(page, "Reset Pose/Scale", new Vector2(0f, -70f), () => { _panel?.SnapToDefaultPose(); SetFeedback("Panel reset"); });
            CreateButton(page, "Back", new Vector2(0f, -180f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private void BuildSettings(Transform page)
        {
            _gestureEnabledToggle = CreateToggle(page, "Gesture Shortcuts Enabled", new Vector2(0f, 190f), value =>
            {
                PlayerPrefs.SetInt(PrefGestureEnabled, value ? 1 : 0);
                PlayerPrefs.Save();
                _shortcuts?.SetShortcutsEnabled(value);
                SetFeedback("Shortcuts " + (value ? "ON" : "OFF"));
            });
            CreateButton(page, "Shortcut Hand", new Vector2(0f, 128f), CycleShortcutHand);
            CreateButton(page, "Conflict Mode", new Vector2(0f, 66f), CycleConflictMode);
            CreateButton(page, "Menu Hand", new Vector2(0f, 4f), CycleMenuHand);
            _autoSpeakOcrToggle = CreateToggle(page, "Auto Speak OCR", new Vector2(0f, -58f), value =>
            {
                _panel?.SetAutoSpeakOcr(value);
                SetFeedback("AutoSpeak OCR " + (value ? "ON" : "OFF"));
            });
            _ocrVerboseToggle = CreateToggle(page, "OCR Verbose", new Vector2(0f, -116f), value =>
            {
                _panel?.SetOcrVerbose(value);
                SetFeedback("OCR Verbose " + (value ? "ON" : "OFF"));
            });
            _autoSpeakDetToggle = CreateToggle(page, "Auto Speak DET", new Vector2(0f, -174f), value =>
            {
                _panel?.SetAutoSpeakDet(value);
                SetFeedback("AutoSpeak DET " + (value ? "ON" : "OFF"));
            });
            _autoSpeakRiskToggle = CreateToggle(page, "Auto Speak RISK", new Vector2(0f, -232f), value =>
            {
                _panel?.SetAutoSpeakRisk(value);
                SetFeedback("AutoSpeak RISK " + (value ? "ON" : "OFF"));
            });
            _autoSpeakFindToggle = CreateToggle(page, "Auto Speak FIND", new Vector2(0f, -290f), value =>
            {
                _panel?.SetAutoSpeakFind(value);
                SetFeedback("AutoSpeak FIND " + (value ? "ON" : "OFF"));
            });
            _autoGuidanceToggle = CreateToggle(page, "Auto Guidance", new Vector2(0f, -348f), value =>
            {
                _panel?.SetAutoGuidance(value);
                SetFeedback("Auto Guidance " + (value ? "ON" : "OFF"));
            });
            _guidanceAudioToggle = CreateToggle(page, "Guidance Audio", new Vector2(0f, -406f), value =>
            {
                _panel?.SetGuidanceAudio(value);
                SetFeedback("Guidance Audio " + (value ? "ON" : "OFF"));
            });
            _guidanceHapticsToggle = CreateToggle(page, "Guidance Haptics", new Vector2(0f, -464f), value =>
            {
                _panel?.SetGuidanceHaptics(value);
                SetFeedback("Guidance Haptics " + (value ? "ON" : "OFF"));
            });
            _passthroughToggle = CreateToggle(page, "Passthrough", new Vector2(0f, -522f), value =>
            {
                PlayerPrefs.SetInt(PrefPassthrough, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetPassthroughEnabled(value);
                SetFeedback("Passthrough " + (value ? "ON" : "OFF"));
            });
            _uiScaleSlider = CreateSlider(page, new Vector2(0f, -580f), 0.6f, 1.4f, value =>
            {
                PlayerPrefs.SetFloat(PrefUiScale, value);
                PlayerPrefs.Save();
                ApplyUiScale(value);
                SetFeedback($"UI Scale {value:0.00}x");
            });
            _scaleText = CreateText("ScaleText", page, "UI Scale: 1.00x", 20, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -626f), new Vector2(760f, 32f));
            _settingsText = CreateText("SettingsText", page, "-", 20, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -662f), new Vector2(780f, 32f));
            CreateButton(page, "Back", new Vector2(0f, -716f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private void BuildDebug(Transform page)
        {
            _debugText = CreateText("DebugText", page, "-", 20, TextAnchor.UpperLeft, new Vector2(0.5f, 0.5f), new Vector2(0f, 100f), new Vector2(760f, 340f));
            CreateButton(page, "Copy Debug", new Vector2(-120f, -170f), () =>
            {
                GUIUtility.systemCopyBuffer = (_panel != null ? _panel.BuildDebugSummary() : "panel missing") + "\nGestures=" + (_shortcuts != null ? _shortcuts.GetRecentTriggersAsText() : "-");
                SetFeedback("Debug copied");
            });
            CreateButton(page, "Refresh", new Vector2(120f, -170f), () => { RefreshStatus(); SetFeedback("Debug refresh"); });
            CreateButton(page, "Back", new Vector2(0f, -260f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private IEnumerator RefreshLoop()
        {
            while (enabled)
            {
                RefreshStatus();
                yield return new WaitForSecondsRealtime(Mathf.Max(0.25f, refreshIntervalSec));
            }
        }

        private void RefreshStatus()
        {
            ResolveRefs();
            if (_panel == null)
            {
                return;
            }

            _sb.Clear();
            _sb.Append("BaseUrl: ").Append(_panel.GetBaseUrl()).Append('\n');
            _sb.Append("WS: ").Append(_panel.IsWsConnected() ? "connected" : "disconnected").Append('\n');
            _sb.Append("DeviceId: ").Append(_panel.GetDeviceId()).Append('\n');
            _sb.Append("Mode: ").Append(_panel.GetCurrentModeText());
            SetText(_connectionText, _sb.ToString());
            SetText(_modeText, "Mode: " + _panel.GetCurrentModeText());

            _sb.Clear();
            _sb.Append("UploadMs=").Append(_panel.GetLastUploadMs()).Append("  E2E=").Append(_panel.GetLastE2eMs()).Append('\n');
            _sb.Append("LastEvent=").Append(_panel.GetLastEventType()).Append('\n');
            _sb.Append("LastFind=").Append(_panel.GetLastFindText()).Append('\n');
            _sb.Append("LastTarget=").Append(_panel.GetLastTargetText()).Append('\n');
            _sb.Append("Guidance=").Append(_panel.GetGuidanceText()).Append('\n');
            _sb.Append("Passthrough=").Append(_panel.GetPassthroughStatus()).Append('\n');
            _sb.Append("SelfTest=").Append(_selfTestRunner != null ? _selfTestRunner.CurrentStatus : "-").Append('\n');
            _sb.Append("Gestures=").Append(_shortcuts != null ? _shortcuts.GetRecentTriggersAsText() : "-").Append('\n');
            _sb.Append("GuideDisabler=").Append(ByesMrTemplateGuideDisabler.LastSummary);
            SetText(_debugText, _sb.ToString());

            if (_shortcuts != null)
            {
                SetText(_settingsText, $"Shortcuts={(_shortcuts.ShortcutsEnabled ? "ON" : "OFF")} Hand={_shortcuts.ActiveShortcutHand} Conflict={_shortcuts.ActiveConflictMode}");
            }
            _autoSpeakOcrToggle?.SetIsOnWithoutNotify(_panel.AutoSpeakOcrEnabled);
            _autoSpeakDetToggle?.SetIsOnWithoutNotify(_panel.AutoSpeakDetEnabled);
            _autoSpeakRiskToggle?.SetIsOnWithoutNotify(_panel.AutoSpeakRiskEnabled);
            _autoSpeakFindToggle?.SetIsOnWithoutNotify(_panel.AutoSpeakFindEnabled);
            _autoGuidanceToggle?.SetIsOnWithoutNotify(_panel.AutoGuidanceEnabled);
            _guidanceAudioToggle?.SetIsOnWithoutNotify(_panel.GuidanceAudioEnabled);
            _guidanceHapticsToggle?.SetIsOnWithoutNotify(_panel.GuidanceHapticsEnabled);
            _ocrVerboseToggle?.SetIsOnWithoutNotify(_panel.OcrVerboseEnabled);

            SetText(_scaleText, $"UI Scale: {(_uiScaleSlider != null ? _uiScaleSlider.value : 1f):0.00}x");
            _lockToHeadToggle?.SetIsOnWithoutNotify(_panel.IsLockToHead());
            _moveResizeToggle?.SetIsOnWithoutNotify(_panel.IsMoveResizeEnabled());
        }

        private void OnSystemGestureStarted()
        {
            _systemGestureActive = true;
            ApplyConflictIsolation(true);
            SetFeedback("Menu active");
        }

        private void OnSystemGestureEnded()
        {
            _systemGestureActive = false;
            ApplyConflictIsolation(false);
        }

        private void ApplyConflictIsolation(bool suppressUi)
        {
            if (_uiSuppressed == suppressUi)
            {
                return;
            }

            _uiSuppressed = suppressUi;
            var interactorList = FindObjectsByType<XRRayInteractor>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            for (var i = 0; i < interactorList.Length; i += 1)
            {
                try
                {
                    interactorList[i].enableUIInteraction = !suppressUi;
                }
                catch
                {
                    // ignore XRI version mismatch
                }
            }

            if (suppressUi)
            {
                _panel?.SetMoveResizeEnabled(false);
            }

            _shortcuts?.SetSystemGestureActive(suppressUi);
        }

        private void HandleShortcutTriggered(string action)
        {
            SetFeedback("Gesture: " + (string.IsNullOrWhiteSpace(action) ? "unknown" : action));
        }

        private void LoadPrefsAndApply()
        {
            _showFullPanelToggle?.SetIsOnWithoutNotify(PlayerPrefs.GetInt(PrefShowFullPanel, 0) == 1);
            _gestureEnabledToggle?.SetIsOnWithoutNotify(PlayerPrefs.GetInt(PrefGestureEnabled, 1) == 1);
            _passthroughToggle?.SetIsOnWithoutNotify(PlayerPrefs.GetInt(PrefPassthrough, 1) == 1);
            _lockToHeadToggle?.SetIsOnWithoutNotify(PlayerPrefs.GetInt(PrefLockToHead, 1) == 1);
            _moveResizeToggle?.SetIsOnWithoutNotify(PlayerPrefs.GetInt(PrefMoveResize, 0) == 1);
            _autoSpeakOcrToggle?.SetIsOnWithoutNotify(_panel != null && _panel.AutoSpeakOcrEnabled);
            _autoSpeakDetToggle?.SetIsOnWithoutNotify(_panel != null && _panel.AutoSpeakDetEnabled);
            _autoSpeakRiskToggle?.SetIsOnWithoutNotify(_panel != null && _panel.AutoSpeakRiskEnabled);
            _autoSpeakFindToggle?.SetIsOnWithoutNotify(_panel != null && _panel.AutoSpeakFindEnabled);
            _autoGuidanceToggle?.SetIsOnWithoutNotify(_panel != null && _panel.AutoGuidanceEnabled);
            _guidanceAudioToggle?.SetIsOnWithoutNotify(_panel != null && _panel.GuidanceAudioEnabled);
            _guidanceHapticsToggle?.SetIsOnWithoutNotify(_panel != null && _panel.GuidanceHapticsEnabled);
            _ocrVerboseToggle?.SetIsOnWithoutNotify(_panel != null && _panel.OcrVerboseEnabled);

            var uiScale = PlayerPrefs.GetFloat(PrefUiScale, 1f);
            if (_uiScaleSlider != null)
            {
                _uiScaleSlider.SetValueWithoutNotify(uiScale);
            }
            ApplyUiScale(uiScale);

            _shortcuts?.SetShortcutsEnabled(PlayerPrefs.GetInt(PrefGestureEnabled, 1) == 1);
            _shortcuts?.SetShortcutHand((ByesHandGestureShortcuts.ShortcutHand)PlayerPrefs.GetInt(PrefShortcutHand, (int)ByesHandGestureShortcuts.ShortcutHand.RightOnly));
            _shortcuts?.SetConflictMode((ByesHandGestureShortcuts.ConflictMode)PlayerPrefs.GetInt(PrefConflictMode, (int)ByesHandGestureShortcuts.ConflictMode.Safe));
            var passthroughEnabled = PlayerPrefs.GetInt(PrefPassthrough, 1) == 1;
            if (passthroughEnabled)
            {
                _panel?.SetPassthroughEnabled(true);
            }
            else
            {
                _panel?.SetPassthroughEnabled(false);
            }
            _panel?.SetActionControlsVisible(PlayerPrefs.GetInt(PrefShowFullPanel, 0) == 1);
            _panel?.SetLockToHead(PlayerPrefs.GetInt(PrefLockToHead, 1) == 1);
            _panel?.SetMoveResizeEnabled(PlayerPrefs.GetInt(PrefMoveResize, 0) == 1);
            ApplyMenuHandPreference((MenuHandPref)PlayerPrefs.GetInt(PrefMenuHand, (int)MenuHandPref.Either));
        }

        private void CycleShortcutHand()
        {
            var current = (ByesHandGestureShortcuts.ShortcutHand)PlayerPrefs.GetInt(PrefShortcutHand, (int)ByesHandGestureShortcuts.ShortcutHand.RightOnly);
            var next = current switch
            {
                ByesHandGestureShortcuts.ShortcutHand.RightOnly => ByesHandGestureShortcuts.ShortcutHand.LeftOnly,
                ByesHandGestureShortcuts.ShortcutHand.LeftOnly => ByesHandGestureShortcuts.ShortcutHand.Both,
                _ => ByesHandGestureShortcuts.ShortcutHand.RightOnly,
            };
            PlayerPrefs.SetInt(PrefShortcutHand, (int)next);
            PlayerPrefs.Save();
            _shortcuts?.SetShortcutHand(next);
            SetFeedback("Shortcut hand -> " + next);
        }

        private void CycleConflictMode()
        {
            var current = (ByesHandGestureShortcuts.ConflictMode)PlayerPrefs.GetInt(PrefConflictMode, (int)ByesHandGestureShortcuts.ConflictMode.Safe);
            var next = current == ByesHandGestureShortcuts.ConflictMode.Safe
                ? ByesHandGestureShortcuts.ConflictMode.Advanced
                : ByesHandGestureShortcuts.ConflictMode.Safe;
            PlayerPrefs.SetInt(PrefConflictMode, (int)next);
            PlayerPrefs.Save();
            _shortcuts?.SetConflictMode(next);
            SetFeedback("Conflict -> " + next);
        }

        private void CycleMenuHand()
        {
            var current = (MenuHandPref)PlayerPrefs.GetInt(PrefMenuHand, (int)MenuHandPref.Left);
            var next = current switch
            {
                MenuHandPref.Left => MenuHandPref.Right,
                MenuHandPref.Right => MenuHandPref.Either,
                _ => MenuHandPref.Left,
            };
            PlayerPrefs.SetInt(PrefMenuHand, (int)next);
            PlayerPrefs.Save();
            ApplyMenuHandPreference(next);
            SetFeedback("Menu hand -> " + next);
        }

        private void ApplyMenuHandPreference(MenuHandPref pref)
        {
            if (_handMenu == null)
            {
                return;
            }

            _handMenu.menuHandedness = pref switch
            {
                MenuHandPref.Right => HandMenu.MenuHandedness.Right,
                MenuHandPref.Either => HandMenu.MenuHandedness.Either,
                _ => HandMenu.MenuHandedness.Left,
            };
        }

        private void ApplyUiScale(float scale)
        {
            if (_canvas != null)
            {
                _canvas.transform.localScale = Vector3.one * (baseUiScale * Mathf.Clamp(scale, 0.6f, 1.4f));
            }
        }

        private void SetPage(string key)
        {
            foreach (var entry in _pages)
            {
                entry.Value.SetActive(string.Equals(entry.Key, key, StringComparison.Ordinal));
            }
        }

        private void SetFeedback(string message)
        {
            SetText(_feedbackText, string.IsNullOrWhiteSpace(message) ? "-" : message);
        }

        private void SetText(Text text, string value)
        {
            if (text == null)
            {
                return;
            }

            var resolved = value ?? string.Empty;
            if (_textCache.TryGetValue(text, out var cached) && string.Equals(cached, resolved, StringComparison.Ordinal))
            {
                return;
            }

            _textCache[text] = resolved;
            text.text = resolved;
        }

        private static GameObject CreateUiObject(string name, Transform parent, Vector2 anchorMin, Vector2 anchorMax, Vector2 size, Vector2 anchoredPos)
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

        private static Text CreateText(string name, Transform parent, string value, int fontSize, TextAnchor align, Vector2 anchor, Vector2 pos, Vector2 size)
        {
            var go = CreateUiObject(name, parent, anchor, anchor, size, pos);
            var text = go.AddComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.color = Color.white;
            text.alignment = align;
            text.fontSize = fontSize;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Truncate;
            text.text = value;
            return text;
        }

        private static Button CreateButton(Transform parent, string label, Vector2 pos, Action onClick)
        {
            var go = CreateUiObject(label.Replace(" ", string.Empty), parent, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(250f, 56f), pos);
            var image = go.AddComponent<Image>();
            image.color = new Color(0.2f, 0.5f, 0.9f, 0.95f);
            var button = go.AddComponent<Button>();
            button.targetGraphic = image;
            button.transition = Selectable.Transition.ColorTint;
            var colors = button.colors;
            colors.normalColor = new Color(0.2f, 0.5f, 0.9f, 0.95f);
            colors.highlightedColor = new Color(0.30f, 0.64f, 1.0f, 1.0f);
            colors.pressedColor = new Color(0.14f, 0.34f, 0.70f, 1.0f);
            colors.selectedColor = colors.highlightedColor;
            colors.disabledColor = new Color(0.25f, 0.25f, 0.25f, 0.7f);
            colors.colorMultiplier = 1f;
            colors.fadeDuration = 0.05f;
            button.colors = colors;
            button.onClick.AddListener(() => onClick?.Invoke());
            var text = CreateText("Label", go.transform, label, 22, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), Vector2.zero, new Vector2(230f, 48f));
            text.raycastTarget = false;
            return button;
        }

        private static Toggle CreateToggle(Transform parent, string label, Vector2 pos, Action<bool> onChanged)
        {
            var go = CreateUiObject(label.Replace(" ", string.Empty), parent, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(640f, 66f), pos);
            var rowImage = go.AddComponent<Image>();
            rowImage.color = new Color(0.13f, 0.20f, 0.31f, 0.95f);
            var labelText = CreateText("Label", go.transform, label, 23, TextAnchor.MiddleLeft, new Vector2(0.5f, 0.5f), new Vector2(-36f, 0f), new Vector2(520f, 58f));
            labelText.raycastTarget = false;
            var box = CreateUiObject("Box", go.transform, new Vector2(1f, 0.5f), new Vector2(1f, 0.5f), new Vector2(48f, 48f), new Vector2(-24f, 0f));
            var boxImage = box.AddComponent<Image>();
            boxImage.color = new Color(0.18f, 0.18f, 0.18f, 0.98f);
            var check = CreateUiObject("Check", box.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(34f, 34f), Vector2.zero);
            var checkImage = check.AddComponent<Image>();
            checkImage.color = new Color(0.1f, 0.8f, 0.25f, 1f);
            var toggle = go.AddComponent<Toggle>();
            toggle.targetGraphic = rowImage;
            toggle.graphic = checkImage;
            toggle.transition = Selectable.Transition.ColorTint;
            var colors = toggle.colors;
            colors.normalColor = new Color(0.13f, 0.20f, 0.31f, 0.95f);
            colors.highlightedColor = new Color(0.20f, 0.30f, 0.44f, 1f);
            colors.pressedColor = new Color(0.10f, 0.16f, 0.24f, 1f);
            colors.selectedColor = colors.highlightedColor;
            colors.disabledColor = new Color(0.22f, 0.22f, 0.22f, 0.7f);
            colors.fadeDuration = 0.05f;
            toggle.colors = colors;
            toggle.onValueChanged.AddListener(v => onChanged?.Invoke(v));
            return toggle;
        }

        private static Slider CreateSlider(Transform parent, Vector2 pos, float min, float max, Action<float> onChanged)
        {
            var go = CreateUiObject("ScaleSlider", parent, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(460f, 74f), pos);
            go.AddComponent<Image>().color = new Color(0.10f, 0.14f, 0.22f, 0.92f);

            var track = CreateUiObject("Track", go.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(400f, 16f), Vector2.zero);
            var trackImage = track.AddComponent<Image>();
            trackImage.color = new Color(0.18f, 0.20f, 0.24f, 1f);

            var fillArea = CreateUiObject("FillArea", go.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(400f, 16f), Vector2.zero);
            var fill = CreateUiObject("Fill", fillArea.transform, new Vector2(0f, 0f), new Vector2(0f, 1f), new Vector2(0f, 0f), Vector2.zero);
            var fillRect = fill.GetComponent<RectTransform>();
            fillRect.pivot = new Vector2(0f, 0.5f);
            var fillImage = fill.AddComponent<Image>();
            fillImage.color = new Color(0.10f, 0.45f, 0.85f, 0.9f);

            var handleSlide = CreateUiObject("HandleSlideArea", go.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(420f, 56f), Vector2.zero);
            var handle = CreateUiObject("Handle", handleSlide.transform, new Vector2(0f, 0.5f), new Vector2(0f, 0.5f), new Vector2(56f, 56f), Vector2.zero);
            var handleImage = handle.AddComponent<Image>();
            handleImage.color = Color.white;

            var slider = go.AddComponent<Slider>();
            slider.minValue = min;
            slider.maxValue = max;
            slider.direction = Slider.Direction.LeftToRight;
            slider.wholeNumbers = false;
            slider.fillRect = fillRect;
            slider.handleRect = handle.GetComponent<RectTransform>();
            slider.targetGraphic = handleImage;
            slider.transition = Selectable.Transition.ColorTint;
            var colors = slider.colors;
            colors.normalColor = Color.white;
            colors.highlightedColor = new Color(0.9f, 0.95f, 1f, 1f);
            colors.pressedColor = new Color(0.75f, 0.85f, 1f, 1f);
            colors.selectedColor = colors.highlightedColor;
            colors.disabledColor = new Color(0.5f, 0.5f, 0.5f, 0.7f);
            slider.colors = colors;
            slider.onValueChanged.AddListener(v => onChanged?.Invoke(v));
            return slider;
        }

        private void DisableCompetingMenus(GameObject previousMenuHost)
        {
            if (previousMenuHost != null && previousMenuHost != _menuHost)
            {
                previousMenuHost.SetActive(false);
            }

            var allCanvas = FindObjectsByType<Canvas>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            for (var i = 0; i < allCanvas.Length; i += 1)
            {
                var canvas = allCanvas[i];
                if (canvas == null || canvas.transform == null)
                {
                    continue;
                }

                if (_canvas != null && canvas == _canvas)
                {
                    continue;
                }

                var go = canvas.gameObject;
                var name = go.name ?? string.Empty;
                var lowered = name.ToLowerInvariant();
                if (name.StartsWith("BYES_", StringComparison.Ordinal))
                {
                    continue;
                }

                if (lowered.Contains("player setting")
                    || lowered.Contains("coaching")
                    || lowered.Contains("hand menu setup")
                    || lowered.Contains("mr template"))
                {
                    go.SetActive(false);
                }
            }
        }
    }
}
