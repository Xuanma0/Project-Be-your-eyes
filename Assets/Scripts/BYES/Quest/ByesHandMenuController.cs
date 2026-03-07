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
        private const string PrefFavorites = "BYES_HANDMENU_FAVORITES";
        private const int FavoriteSlotCount = 3;

        [SerializeField] private float baseUiScale = 0.00038f;
        [SerializeField] private float refreshIntervalSec = 0.75f;
        [SerializeField] private bool disableCompetingTemplateMenus = true;
        [SerializeField] private float defaultGazeDivergenceThresholdDeg = 95f;

        private HandMenu _handMenu;
        private MetaSystemGestureDetector _metaGestureDetector;
        private GameObject _menuHost;
        private Canvas _canvas;
        private GameObject _rootPanel;

        private ByesQuest3ConnectionPanelMinimal _panel;
        private ByesHandGestureShortcuts _shortcuts;
        private ByesQuest3SelfTestRunner _selfTestRunner;
        private ByesQuestPassthroughSetup _passthroughSetup;
        private ByesPassthroughController _passthroughController;
        private ByesVisionHudController _visionHud;

        private readonly Dictionary<string, GameObject> _pages = new Dictionary<string, GameObject>();
        private readonly Dictionary<Text, string> _textCache = new Dictionary<Text, string>();
        private readonly Dictionary<string, MenuAction> _actionRegistry = new Dictionary<string, MenuAction>(StringComparer.OrdinalIgnoreCase);
        private readonly List<string> _favorites = new List<string>();
        private readonly List<Button> _favoriteButtons = new List<Button>();
        private readonly StringBuilder _sb = new StringBuilder(512);
        private string _lastActionKey = string.Empty;

        private Text _feedbackText;
        private Text _connectionText;
        private Text _modeText;
        private Text _settingsText;
        private Text _debugText;
        private Text _scaleText;
        private Text _visionText;
        private Text _guidanceText;
        private Text _voiceText;

        private Toggle _showFullPanelToggle;
        private Toggle _gestureEnabledToggle;
        private Toggle _passthroughToggle;
        private Toggle _passthroughGrayToggle;
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
        private Toggle _autoVoiceCommandToggle;
        private Slider _uiScaleSlider;
        private Slider _detAlphaSlider;
        private Slider _segAlphaSlider;
        private Slider _depthAlphaSlider;
        private Slider _passthroughOpacitySlider;
        private Slider _guidanceRateSlider;
        private Toggle _freezeOverlayToggle;

        private bool _systemGestureActive;
        private bool _uiSuppressed;
        private Coroutine _refreshRoutine;

        private sealed class MenuAction
        {
            public string Label = string.Empty;
            public Action Callback;
        }

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
            DisableLegacyWristMenus();
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
            _passthroughController ??= FindFirstObjectByType<ByesPassthroughController>();
            _visionHud ??= FindFirstObjectByType<ByesVisionHudController>();
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
            rect.sizeDelta = new Vector2(980f, 1860f);
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

            _rootPanel = CreateUiObject("PanelRoot", canvasGo.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(940f, 1760f), Vector2.zero);
            var bg = _rootPanel.AddComponent<Image>();
            bg.color = new Color(0f, 0f, 0f, 0.82f);
            var cg = _rootPanel.AddComponent<CanvasGroup>();
            cg.blocksRaycasts = true;
            cg.interactable = true;

            _ = CreateText("Hint", _rootPanel.transform, "Flip wrist palm-up to open menu (no pinch needed)", 26, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -30f), new Vector2(820f, 44f));
            _feedbackText = CreateText("Feedback", _rootPanel.transform, "-", 21, TextAnchor.MiddleLeft, new Vector2(0.5f, 0f), new Vector2(0f, 22f), new Vector2(840f, 38f));

            BuildPages(_rootPanel.transform);
        }

        private void BuildPages(Transform root)
        {
            RegisterCoreActions();
            _pages["home"] = CreatePage(root, "Home");
            _pages["vision"] = CreatePage(root, "Vision");
            _pages["guidance"] = CreatePage(root, "Guidance");
            _pages["voice"] = CreatePage(root, "Voice");
            _pages["dev"] = CreatePage(root, "Dev");

            BuildHome(_pages["home"].transform);
            BuildVision(_pages["vision"].transform);
            BuildGuidancePage(_pages["guidance"].transform);
            BuildVoice(_pages["voice"].transform);
            BuildDev(_pages["dev"].transform);
        }

        private GameObject CreatePage(Transform root, string title)
        {
            var page = CreateUiObject("Page_" + title, root, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(860f, 1560f), new Vector2(0f, -22f));
            _ = CreateText("Title", page.transform, title, 30, TextAnchor.MiddleCenter, new Vector2(0.5f, 1f), new Vector2(0f, -34f), new Vector2(760f, 44f));
            return page;
        }

        private void RegisterCoreActions()
        {
            _actionRegistry.Clear();
            RegisterAction("scan", "Scan Once", () => _panel?.TriggerScanOnceFromUi());
            RegisterAction("read", "Read Text", () => _panel?.TriggerReadTextOnceFromUi());
            RegisterAction("find_door", "Find Door", () => _panel?.TriggerFindConceptFromUi("door"));
            RegisterAction("find_exit", "Find Exit", () => _panel?.TriggerFindConceptFromUi("exit sign"));
            RegisterAction("find_person", "Find Person", () => _panel?.TriggerFindConceptFromUi("person"));
            RegisterAction("live_toggle", "Toggle Live", () => _panel?.TriggerToggleLiveFromUi());
            RegisterAction("mode_walk", "Mode Walk", () => _panel?.TriggerSetModeWalk());
            RegisterAction("mode_read", "Mode Read", () => _panel?.TriggerSetModeRead());
            RegisterAction("mode_inspect", "Mode Inspect", () => _panel?.TriggerSetModeInspect());
            RegisterAction("selftest", "Run SelfTest", () => _panel?.TriggerSelfTestFromUi());
            RegisterAction("record_start", "Start Record", () => _panel?.TriggerStartRecordFromUi());
            RegisterAction("record_stop", "Stop Record", () => _panel?.TriggerStopRecordFromUi());
            RegisterAction("roi_select", "Select ROI", () => _panel?.TriggerSelectRoiFromUi());
            RegisterAction("track_start", "Start Track", () => _panel?.TriggerStartTrackFromUi());
            RegisterAction("track_step", "Track Step", () => _panel?.TriggerTrackStepFromUi());
            RegisterAction("track_stop", "Stop Track", () => _panel?.TriggerStopTrackFromUi());
            RegisterAction("export_debug", "Export Debug", () => _panel?.ExportDebugText());
            RegisterAction("beep", "Play Beep", () => _panel?.TriggerPlayBeepFromUi());
            RegisterAction("speak_test", "Speak Test", () => _panel?.TriggerSpeakTestFromUi());
            RegisterAction("ptt_start", "PTT Start", () => _panel?.TriggerPushToTalkStartFromUi());
            RegisterAction("ptt_stop", "PTT Stop", () => _panel?.TriggerPushToTalkStopFromUi());
        }

        private void RegisterAction(string key, string label, Action callback)
        {
            if (string.IsNullOrWhiteSpace(key) || callback == null)
            {
                return;
            }

            _actionRegistry[key] = new MenuAction
            {
                Label = string.IsNullOrWhiteSpace(label) ? key : label,
                Callback = callback,
            };
        }

        private void InvokeAction(string key, string feedback)
        {
            if (!_actionRegistry.TryGetValue(key, out var action) || action == null || action.Callback == null)
            {
                SetFeedback("Action unavailable: " + key);
                return;
            }

            action.Callback.Invoke();
            _lastActionKey = key;
            SetFeedback(string.IsNullOrWhiteSpace(feedback) ? action.Label : feedback);
            RefreshFavoriteButtons();
        }

        private void BuildHome(Transform page)
        {
            CreateButton(page, "Scan", new Vector2(-260f, 220f), () => InvokeAction("scan", "Scan once"));
            CreateButton(page, "Read", new Vector2(0f, 220f), () => InvokeAction("read", "Read text"));
            CreateButton(page, "Find Door", new Vector2(260f, 220f), () => InvokeAction("find_door", "Find door"));

            CreateButton(page, "Vision", new Vector2(-260f, 140f), () => { SetPage("vision"); SetFeedback("Vision page"); });
            CreateButton(page, "Guidance", new Vector2(0f, 140f), () => { SetPage("guidance"); SetFeedback("Guidance page"); });
            CreateButton(page, "Voice", new Vector2(260f, 140f), () => { SetPage("voice"); SetFeedback("Voice page"); });
            CreateButton(page, "Dev", new Vector2(0f, 60f), () => { SetPage("dev"); SetFeedback("Dev page"); });

            _connectionText = CreateText("HomeStatus", page, "-", 21, TextAnchor.UpperLeft, new Vector2(0.5f, 0.5f), new Vector2(0f, -70f), new Vector2(780f, 270f));
            _modeText = CreateText("HomeMode", page, "Mode: -", 24, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -230f), new Vector2(780f, 42f));
            _ = CreateText("FavTitle", page, "Favorites (pin from Dev page)", 20, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -282f), new Vector2(760f, 34f));

            for (var i = 0; i < FavoriteSlotCount; i += 1)
            {
                var slot = i;
                var y = -344f - (i * 76f);
                var btn = CreateButton(page, $"Favorite {i + 1}", new Vector2(0f, y), () => InvokeFavorite(slot));
                btn.gameObject.SetActive(false);
                _favoriteButtons.Add(btn);
            }
        }

        private void BuildVision(Transform page)
        {
            _visionText = CreateText("VisionText", page, "-", 20, TextAnchor.UpperLeft, new Vector2(0.5f, 0.5f), new Vector2(0f, 266f), new Vector2(780f, 110f));
            var sections = new Dictionary<string, GameObject>(StringComparer.OrdinalIgnoreCase);
            sections["overlay"] = CreateSectionGroup(page, "VisionOverlaySection", new Vector2(820f, 920f), new Vector2(0f, -120f));
            sections["alpha"] = CreateSectionGroup(page, "VisionAlphaSection", new Vector2(820f, 920f), new Vector2(0f, -120f));
            sections["providers"] = CreateSectionGroup(page, "VisionProviderSection", new Vector2(820f, 920f), new Vector2(0f, -120f));
            _ = CreateSectionButton(page, "Overlay", new Vector2(-220f, 184f), () => SetActiveSection(sections, "overlay"));
            _ = CreateSectionButton(page, "Alpha/Passthru", new Vector2(0f, 184f), () => SetActiveSection(sections, "alpha"));
            _ = CreateSectionButton(page, "Providers", new Vector2(220f, 184f), () => SetActiveSection(sections, "providers"));

            var overlaySection = sections["overlay"].transform;
            CreateToggle(overlaySection, "Show DET Overlay", new Vector2(0f, 220f), value =>
            {
                _visionHud?.SetShowDet(value);
                SetFeedback("Show DET " + (value ? "ON" : "OFF"));
            });
            CreateToggle(overlaySection, "Show SEG Overlay", new Vector2(0f, 150f), value =>
            {
                _visionHud?.SetShowSeg(value);
                SetFeedback("Show SEG " + (value ? "ON" : "OFF"));
            });
            CreateToggle(overlaySection, "Show DEPTH Overlay", new Vector2(0f, 80f), value =>
            {
                _visionHud?.SetShowDepth(value);
                SetFeedback("Show DEPTH " + (value ? "ON" : "OFF"));
            });
            CreateToggle(overlaySection, "Show TARGET Overlay", new Vector2(0f, 10f), value =>
            {
                _visionHud?.SetShowTarget(value);
                SetFeedback("Show TARGET " + (value ? "ON" : "OFF"));
            });
            CreateToggle(overlaySection, "Full-FOV Overlay Layer", new Vector2(0f, -60f), value =>
            {
                _visionHud?.SetFullFovOverlayLayer(value);
                SetFeedback("Full-FOV Layer " + (value ? "ON" : "OFF"));
            });
            _freezeOverlayToggle = CreateToggle(overlaySection, "Freeze Overlay", new Vector2(0f, -130f), value =>
            {
                _visionHud?.SetFreezeOverlay(value);
                SetFeedback("Freeze Overlay " + (value ? "ON" : "OFF"));
            });
            CreateButton(overlaySection, "Reset HUD", new Vector2(-140f, -230f), () =>
            {
                _visionHud?.ResetHud();
                SetFeedback("HUD reset");
            });
            CreateButton(overlaySection, "Back", new Vector2(140f, -230f), () => { SetPage("home"); SetFeedback("Home"); });

            var alphaSection = sections["alpha"].transform;
            _detAlphaSlider = CreateLabeledSlider(alphaSection, "DET Alpha", new Vector2(0f, 182f), 0f, 1f, value =>
            {
                _visionHud?.SetDetAlpha(value);
                SetFeedback($"DET alpha {value:0.00}");
            });
            _segAlphaSlider = CreateLabeledSlider(alphaSection, "SEG Alpha", new Vector2(0f, 48f), 0f, 1f, value =>
            {
                _visionHud?.SetSegAlpha(value);
                SetFeedback($"SEG alpha {value:0.00}");
            });
            _depthAlphaSlider = CreateLabeledSlider(alphaSection, "DEPTH Alpha", new Vector2(0f, -86f), 0f, 1f, value =>
            {
                _visionHud?.SetDepthAlpha(value);
                SetFeedback($"DEPTH alpha {value:0.00}");
            });
            _passthroughToggle = CreateToggle(alphaSection, "Passthrough", new Vector2(0f, -220f), value =>
            {
                PlayerPrefs.SetInt(PrefPassthrough, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetPassthroughEnabled(value);
                SetFeedback("Passthrough " + (value ? "ON" : "OFF"));
            });
            _passthroughGrayToggle = CreateToggle(alphaSection, "Passthrough Gray", new Vector2(0f, -290f), value =>
            {
                _passthroughController?.SetColorMode(value ? ByesPassthroughController.DisplayMode.Gray : ByesPassthroughController.DisplayMode.Color);
                SetFeedback(value ? "Passthrough gray" : "Passthrough color");
            });
            _passthroughOpacitySlider = CreateLabeledSlider(alphaSection, "Passthrough Opacity", new Vector2(0f, -412f), 0f, 1f, value =>
            {
                _passthroughController?.SetOpacity(value);
                SetFeedback($"Passthrough opacity {value:0.00}");
            });
            CreateButton(alphaSection, "Back", new Vector2(0f, -520f), () => { SetPage("home"); SetFeedback("Home"); });

            var providerSection = sections["providers"].transform;
            CreateToggle(providerSection, "DET Service Enabled", new Vector2(0f, 190f), value =>
            {
                _panel?.TriggerSetProviderEnabledFromUi("det", value);
                SetFeedback("DET service " + (value ? "ON" : "OFF"));
            });
            CreateToggle(providerSection, "SEG Service Enabled", new Vector2(0f, 120f), value =>
            {
                _panel?.TriggerSetProviderEnabledFromUi("seg", value);
                SetFeedback("SEG service " + (value ? "ON" : "OFF"));
            });
            CreateToggle(providerSection, "DEPTH Service Enabled", new Vector2(0f, 50f), value =>
            {
                _panel?.TriggerSetProviderEnabledFromUi("depth", value);
                SetFeedback("DEPTH service " + (value ? "ON" : "OFF"));
            });
            CreateToggle(providerSection, "SLAM Service Enabled", new Vector2(0f, -20f), value =>
            {
                _panel?.TriggerSetProviderEnabledFromUi("slam", value);
                SetFeedback("SLAM service " + (value ? "ON" : "OFF"));
            });
            CreateToggle(providerSection, "pySLAM Realtime Enabled", new Vector2(0f, -90f), value =>
            {
                _panel?.TriggerSetProviderEnabledFromUi("pyslamRealtime", value);
                SetFeedback("pySLAM realtime " + (value ? "ON" : "OFF"));
            });
            _ = CreateText("ProviderHint", providerSection, "Backend overrides stay on the Smoke Panel / Desktop Console to keep the wrist menu short.", 18, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -188f), new Vector2(720f, 80f));
            CreateButton(providerSection, "Back", new Vector2(0f, -290f), () => { SetPage("home"); SetFeedback("Home"); });

            SetActiveSection(sections, "overlay");
        }

        private void BuildGuidancePage(Transform page)
        {
            _guidanceText = CreateText("GuidanceText", page, "-", 21, TextAnchor.UpperLeft, new Vector2(0.5f, 0.5f), new Vector2(0f, 180f), new Vector2(780f, 150f));
            _autoGuidanceToggle = CreateToggle(page, "Auto Guidance", new Vector2(0f, 96f), value =>
            {
                _panel?.SetAutoGuidance(value);
                SetFeedback("Auto Guidance " + (value ? "ON" : "OFF"));
            });
            _guidanceAudioToggle = CreateToggle(page, "Guidance Audio", new Vector2(0f, 38f), value =>
            {
                _panel?.SetGuidanceAudio(value);
                SetFeedback("Guidance Audio " + (value ? "ON" : "OFF"));
            });
            _guidanceHapticsToggle = CreateToggle(page, "Guidance Haptics", new Vector2(0f, -20f), value =>
            {
                _panel?.SetGuidanceHaptics(value);
                SetFeedback("Guidance Haptics " + (value ? "ON" : "OFF"));
            });
            _guidanceRateSlider = CreateLabeledSlider(page, "Guidance Rate", new Vector2(0f, -110f), 0.2f, 1.2f, value =>
            {
                _panel?.SetGuidanceRate(value);
                SetFeedback($"Guidance rate {value:0.00}s");
            });
            CreateButton(page, "Mode Walk", new Vector2(-260f, -196f), () => InvokeAction("mode_walk", "Mode walk"));
            CreateButton(page, "Mode Read", new Vector2(0f, -196f), () => InvokeAction("mode_read", "Mode read"));
            CreateButton(page, "Mode Inspect", new Vector2(260f, -196f), () => InvokeAction("mode_inspect", "Mode inspect"));
            CreateButton(page, "Find Exit", new Vector2(-260f, -274f), () => InvokeAction("find_exit", "Find exit"));
            CreateButton(page, "Find Person", new Vector2(0f, -274f), () => InvokeAction("find_person", "Find person"));
            CreateButton(page, "Back", new Vector2(260f, -274f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private void BuildVoice(Transform page)
        {
            _voiceText = CreateText("VoiceText", page, "-", 20, TextAnchor.UpperLeft, new Vector2(0.5f, 0.5f), new Vector2(0f, 266f), new Vector2(780f, 110f));
            var sections = new Dictionary<string, GameObject>(StringComparer.OrdinalIgnoreCase);
            sections["actions"] = CreateSectionGroup(page, "VoiceActionSection", new Vector2(820f, 920f), new Vector2(0f, -120f));
            sections["gestures"] = CreateSectionGroup(page, "VoiceGestureSection", new Vector2(820f, 920f), new Vector2(0f, -120f));
            _ = CreateSectionButton(page, "Voice Actions", new Vector2(-130f, 184f), () => SetActiveSection(sections, "actions"));
            _ = CreateSectionButton(page, "Gestures", new Vector2(130f, 184f), () => SetActiveSection(sections, "gestures"));

            var actionSection = sections["actions"].transform;
            _autoVoiceCommandToggle = CreateToggle(actionSection, "Auto Voice Command", new Vector2(0f, 210f), value =>
            {
                _panel?.SetAutoVoiceCommand(value);
                SetFeedback("Auto Voice Cmd " + (value ? "ON" : "OFF"));
            });
            CreateToggle(actionSection, "ASR Service Enabled", new Vector2(0f, 140f), value =>
            {
                _panel?.TriggerSetProviderEnabledFromUi("asr", value);
                SetFeedback("ASR service " + (value ? "ON" : "OFF"));
            });
            CreateButton(actionSection, "Play Beep", new Vector2(-200f, 46f), () => InvokeAction("beep", "Beep played"));
            CreateButton(actionSection, "Speak Test", new Vector2(0f, 46f), () => InvokeAction("speak_test", "Speak test"));
            CreateButton(actionSection, "PTT Start", new Vector2(200f, 46f), () => InvokeAction("ptt_start", "PTT start"));
            CreateButton(actionSection, "PTT Stop", new Vector2(0f, -36f), () => InvokeAction("ptt_stop", "PTT stop"));
            _ = CreateText("VoiceActionHint", actionSection, "ASR backend overrides stay on the Desktop Console / Smoke Panel to reduce menu length.", 18, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -136f), new Vector2(720f, 80f));
            CreateButton(actionSection, "Back", new Vector2(0f, -248f), () => { SetPage("home"); SetFeedback("Home"); });

            var gestureSection = sections["gestures"].transform;
            _gestureEnabledToggle = CreateToggle(gestureSection, "Gesture Shortcuts Enabled", new Vector2(0f, 210f), value =>
            {
                PlayerPrefs.SetInt(PrefGestureEnabled, value ? 1 : 0);
                PlayerPrefs.Save();
                _shortcuts?.SetShortcutsEnabled(value);
                SetFeedback("Shortcuts " + (value ? "ON" : "OFF"));
            });
            _autoSpeakOcrToggle = CreateToggle(gestureSection, "Auto Speak OCR", new Vector2(0f, 140f), value =>
            {
                _panel?.SetAutoSpeakOcr(value);
                SetFeedback("AutoSpeak OCR " + (value ? "ON" : "OFF"));
            });
            _autoSpeakDetToggle = CreateToggle(gestureSection, "Auto Speak DET", new Vector2(0f, 70f), value =>
            {
                _panel?.SetAutoSpeakDet(value);
                SetFeedback("AutoSpeak DET " + (value ? "ON" : "OFF"));
            });
            _autoSpeakRiskToggle = CreateToggle(gestureSection, "Auto Speak RISK", new Vector2(0f, 0f), value =>
            {
                _panel?.SetAutoSpeakRisk(value);
                SetFeedback("AutoSpeak RISK " + (value ? "ON" : "OFF"));
            });
            _autoSpeakFindToggle = CreateToggle(gestureSection, "Auto Speak FIND", new Vector2(0f, -70f), value =>
            {
                _panel?.SetAutoSpeakFind(value);
                SetFeedback("AutoSpeak FIND " + (value ? "ON" : "OFF"));
            });
            CreateButton(gestureSection, "Shortcut Hand", new Vector2(-220f, -170f), CycleShortcutHand);
            CreateButton(gestureSection, "Conflict Mode", new Vector2(0f, -170f), CycleConflictMode);
            CreateButton(gestureSection, "Menu Hand", new Vector2(220f, -170f), CycleMenuHand);
            CreateButton(gestureSection, "Back", new Vector2(0f, -262f), () => { SetPage("home"); SetFeedback("Home"); });

            SetActiveSection(sections, "actions");
        }

        private void BuildDev(Transform page)
        {
            _debugText = CreateText("DevText", page, "-", 20, TextAnchor.UpperLeft, new Vector2(0.5f, 0.5f), new Vector2(0f, 266f), new Vector2(780f, 120f));
            CreateButton(page, "Run SelfTest", new Vector2(-220f, 186f), () => InvokeAction("selftest", "SelfTest started"));
            CreateButton(page, "Rec Start", new Vector2(0f, 186f), () => InvokeAction("record_start", "Record start"));
            CreateButton(page, "Rec Stop", new Vector2(220f, 186f), () => InvokeAction("record_stop", "Record stop"));
            CreateButton(page, "Refresh", new Vector2(-220f, 106f), () =>
            {
                _panel?.TriggerRefreshFromUi();
                RefreshStatus();
                SetFeedback("Refreshed");
            });
            CreateButton(page, "Pin Last Action", new Vector2(0f, 106f), PinLastAction);
            CreateButton(page, "Copy Debug", new Vector2(220f, 106f), () =>
            {
                GUIUtility.systemCopyBuffer = (_panel != null ? _panel.BuildDebugSummary() : "panel missing") + "\nGestures=" + (_shortcuts != null ? _shortcuts.GetRecentTriggersAsText() : "-");
                SetFeedback("Debug copied");
            });
            _showFullPanelToggle = CreateToggle(page, "Show Advanced Panel Controls", new Vector2(0f, 10f), value =>
            {
                PlayerPrefs.SetInt(PrefShowFullPanel, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetActionControlsVisible(value);
                SetFeedback("Full panel " + (value ? "ON" : "OFF"));
            });
            _lockToHeadToggle = CreateToggle(page, "Smoke Panel LockToHead", new Vector2(0f, -60f), value =>
            {
                PlayerPrefs.SetInt(PrefLockToHead, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetLockToHead(value);
                SetFeedback("LockToHead " + (value ? "ON" : "OFF"));
            });
            _moveResizeToggle = CreateToggle(page, "Enable Move/Resize", new Vector2(0f, -130f), value =>
            {
                PlayerPrefs.SetInt(PrefMoveResize, value ? 1 : 0);
                PlayerPrefs.Save();
                _panel?.SetMoveResizeEnabled(value);
                SetFeedback("Move/Resize " + (value ? "ON" : "OFF"));
            });
            CreateButton(page, "Reset Pose/Scale", new Vector2(-140f, -232f), () => { _panel?.SnapToDefaultPose(); SetFeedback("Panel reset"); });
            CreateButton(page, "Clear Favorites", new Vector2(140f, -232f), ClearFavorites);
            _uiScaleSlider = CreateLabeledSlider(page, "UI Scale", new Vector2(0f, -382f), 0.6f, 1.4f, value =>
            {
                PlayerPrefs.SetFloat(PrefUiScale, value);
                PlayerPrefs.Save();
                ApplyUiScale(value);
                SetFeedback($"UI Scale {value:0.00}x");
            });
            _scaleText = CreateText("ScaleText", page, "UI Scale: 1.00x", 20, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -448f), new Vector2(760f, 32f));
            _settingsText = CreateText("SettingsText", page, "-", 20, TextAnchor.MiddleCenter, new Vector2(0.5f, 0.5f), new Vector2(0f, -486f), new Vector2(780f, 32f));
            CreateButton(page, "Back", new Vector2(0f, -566f), () => { SetPage("home"); SetFeedback("Home"); });
        }

        private void InvokeFavorite(int index)
        {
            if (index < 0 || index >= _favorites.Count)
            {
                return;
            }

            var key = _favorites[index];
            if (_actionRegistry.TryGetValue(key, out var action) && action != null)
            {
                InvokeAction(key, "Favorite -> " + action.Label);
            }
        }

        private void PinLastAction()
        {
            if (string.IsNullOrWhiteSpace(_lastActionKey))
            {
                SetFeedback("No recent action to pin");
                return;
            }

            _favorites.Remove(_lastActionKey);
            _favorites.Insert(0, _lastActionKey);
            while (_favorites.Count > FavoriteSlotCount)
            {
                _favorites.RemoveAt(_favorites.Count - 1);
            }
            SaveFavorites();
            RefreshFavoriteButtons();
            SetFeedback("Pinned: " + _lastActionKey);
        }

        private void ClearFavorites()
        {
            _favorites.Clear();
            SaveFavorites();
            LoadFavoritesFromPrefs();
            SetFeedback("Favorites reset");
        }

        private void LoadFavoritesFromPrefs()
        {
            _favorites.Clear();
            var raw = PlayerPrefs.GetString(PrefFavorites, string.Empty);
            var tokens = string.IsNullOrWhiteSpace(raw) ? Array.Empty<string>() : raw.Split(',');
            for (var i = 0; i < tokens.Length; i += 1)
            {
                var key = (tokens[i] ?? string.Empty).Trim();
                if (string.IsNullOrWhiteSpace(key) || !_actionRegistry.ContainsKey(key) || _favorites.Contains(key))
                {
                    continue;
                }
                _favorites.Add(key);
                if (_favorites.Count >= FavoriteSlotCount)
                {
                    break;
                }
            }

            if (_favorites.Count == 0)
            {
                _favorites.Add("scan");
                _favorites.Add("read");
                _favorites.Add("find_door");
                SaveFavorites();
            }

            RefreshFavoriteButtons();
        }

        private void SaveFavorites()
        {
            PlayerPrefs.SetString(PrefFavorites, string.Join(",", _favorites));
            PlayerPrefs.Save();
        }

        private void RefreshFavoriteButtons()
        {
            for (var i = 0; i < _favoriteButtons.Count; i += 1)
            {
                var btn = _favoriteButtons[i];
                if (btn == null)
                {
                    continue;
                }

                if (i >= _favorites.Count)
                {
                    btn.gameObject.SetActive(false);
                    continue;
                }

                var key = _favorites[i];
                if (!_actionRegistry.TryGetValue(key, out var action) || action == null)
                {
                    btn.gameObject.SetActive(false);
                    continue;
                }

                btn.gameObject.SetActive(true);
                var text = btn.GetComponentInChildren<Text>();
                if (text != null)
                {
                    text.text = action.Label;
                }
            }
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
            _sb.Append("HTTP: ").Append(_panel.GetBaseUrl()).Append('\n');
            _sb.Append("WS: ").Append(_panel.IsWsConnected() ? "connected" : "disconnected").Append('\n');
            _sb.Append("Frame Source: ").Append(_panel.GetFrameSourceText()).Append('\n');
            _sb.Append("Providers: ").Append(_panel.GetProviderSummaryText()).Append('\n');
            _sb.Append("Record: ").Append(_panel.IsRecording() ? "ON" : "OFF").Append('\n');
            _sb.Append("Overlay: ").Append(_panel.GetOverlayKindsText()).Append(" / ").Append(_panel.GetFrameSourceTruthState()).Append('\n');
            _sb.Append("DeviceId: ").Append(_panel.GetDeviceId()).Append('\n');
            _sb.Append("Upload/E2E: ").Append(_panel.GetLastUploadMs()).Append("ms / ").Append(_panel.GetLastE2eMs()).Append("ms");
            SetText(_connectionText, _sb.ToString());
            SetText(_modeText, "Mode: " + _panel.GetCurrentModeText());

            _sb.Clear();
            _sb.Append("HUD fps=").Append(_visionHud != null ? _visionHud.OverlayFps.ToString("0.0") : "-").Append('\n');
            _sb.Append("SEG age=").Append(_visionHud != null ? _visionHud.LastSegAgeMs.ToString() : "-").Append("ms  ");
            _sb.Append("DEPTH age=").Append(_visionHud != null ? _visionHud.LastDepthAgeMs.ToString() : "-").Append("ms  ");
            _sb.Append("DET age=").Append(_visionHud != null ? _visionHud.LastDetAgeMs.ToString() : "-").Append("ms\n");
            _sb.Append("Decode=").Append(_visionHud != null ? _visionHud.LastDecodeMs.ToString("0.0") : "-").Append("ms  Bytes=").Append(_visionHud != null ? _visionHud.LastAssetBytes : 0).Append('\n');
            _sb.Append("Mode=").Append(_visionHud != null && _visionHud.FullFovOverlayLayer ? "whole_fov_hold" : "panel_hold");
            _sb.Append(" Freeze=").Append(_visionHud != null && _visionHud.FreezeOverlay ? "on" : "off");
            _sb.Append(" Kinds=").Append(_panel != null ? _panel.GetOverlayKindsText() : "-").Append('\n');
            _sb.Append("pySLAM: ").Append(_panel != null ? _panel.GetPySlamSummaryText() : "-").Append('\n');
            _sb.Append("Providers: ").Append(_panel != null ? _panel.GetProviderSummaryText() : "-");
            SetText(_visionText, _sb.ToString());

            _sb.Clear();
            _sb.Append("Guidance: ").Append(_panel.GetGuidanceText()).Append('\n');
            _sb.Append("Auto=").Append(_panel.AutoGuidanceEnabled ? "on" : "off");
            _sb.Append(" Audio=").Append(_panel.GuidanceAudioEnabled ? "on" : "off");
            _sb.Append(" Haptics=").Append(_panel.GuidanceHapticsEnabled ? "on" : "off");
            SetText(_guidanceText, _sb.ToString());

            _sb.Clear();
            _sb.Append("Last ASR: ").Append(_panel.GetLastAsrText()).Append('\n');
            _sb.Append("Last TTS: ").Append(_panel.GetLastTtsText()).Append('\n');
            _sb.Append("Truth: ").Append(_panel.GetVoiceTruthSummary()).Append('\n');
            _sb.Append("AutoVoiceCmd: ").Append(_panel.AutoVoiceCommandEnabled ? "on" : "off");
            SetText(_voiceText, _sb.ToString());

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
            _autoVoiceCommandToggle?.SetIsOnWithoutNotify(_panel.AutoVoiceCommandEnabled);
            _passthroughToggle?.SetIsOnWithoutNotify(PlayerPrefs.GetInt(PrefPassthrough, 1) == 1);
            _passthroughGrayToggle?.SetIsOnWithoutNotify(_passthroughController != null && _passthroughController.ColorMode == ByesPassthroughController.DisplayMode.Gray);
            _freezeOverlayToggle?.SetIsOnWithoutNotify(_visionHud != null && _visionHud.FreezeOverlay);

            SetText(_scaleText, $"UI Scale: {(_uiScaleSlider != null ? _uiScaleSlider.value : 1f):0.00}x");
            _lockToHeadToggle?.SetIsOnWithoutNotify(_panel.IsLockToHead());
            _moveResizeToggle?.SetIsOnWithoutNotify(_panel.IsMoveResizeEnabled());

            if (_segAlphaSlider != null && _visionHud != null)
            {
                _segAlphaSlider.SetValueWithoutNotify(_visionHud.SegAlpha);
            }
            if (_depthAlphaSlider != null && _visionHud != null)
            {
                _depthAlphaSlider.SetValueWithoutNotify(_visionHud.DepthAlpha);
            }
            if (_detAlphaSlider != null && _visionHud != null)
            {
                _detAlphaSlider.SetValueWithoutNotify(_visionHud.DetAlpha);
            }
            if (_passthroughOpacitySlider != null && _passthroughController != null)
            {
                _passthroughOpacitySlider.SetValueWithoutNotify(_passthroughController.Opacity);
            }
            if (_guidanceRateSlider != null)
            {
                _guidanceRateSlider.SetValueWithoutNotify(_panel.GetGuidanceRate());
            }

            RefreshFavoriteButtons();
        }

        private void OnSystemGestureStarted()
        {
            _systemGestureActive = true;
            ApplyConflictIsolation(true);
            SetFeedback("System gesture active");
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

            var panelGroup = _rootPanel != null ? _rootPanel.GetComponent<CanvasGroup>() : null;
            if (panelGroup != null)
            {
                panelGroup.blocksRaycasts = !suppressUi;
                panelGroup.interactable = !suppressUi;
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
            _autoVoiceCommandToggle?.SetIsOnWithoutNotify(_panel != null && _panel.AutoVoiceCommandEnabled);
            _passthroughGrayToggle?.SetIsOnWithoutNotify(_passthroughController != null && _passthroughController.ColorMode == ByesPassthroughController.DisplayMode.Gray);

            var uiScale = PlayerPrefs.GetFloat(PrefUiScale, 1f);
            if (_uiScaleSlider != null)
            {
                _uiScaleSlider.SetValueWithoutNotify(uiScale);
            }
            if (_segAlphaSlider != null && _visionHud != null)
            {
                _segAlphaSlider.SetValueWithoutNotify(_visionHud.SegAlpha);
            }
            if (_depthAlphaSlider != null && _visionHud != null)
            {
                _depthAlphaSlider.SetValueWithoutNotify(_visionHud.DepthAlpha);
            }
            if (_detAlphaSlider != null && _visionHud != null)
            {
                _detAlphaSlider.SetValueWithoutNotify(_visionHud.DetAlpha);
            }
            if (_passthroughOpacitySlider != null && _passthroughController != null)
            {
                _passthroughOpacitySlider.SetValueWithoutNotify(_passthroughController.Opacity);
            }
            if (_guidanceRateSlider != null && _panel != null)
            {
                _guidanceRateSlider.SetValueWithoutNotify(_panel.GetGuidanceRate());
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
            _panel?.SetAutoVoiceCommand(PlayerPrefs.GetInt("BYES_AUTO_VOICE_COMMAND", 1) == 1);
            LoadFavoritesFromPrefs();
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

        private static GameObject CreateSectionGroup(Transform parent, string name, Vector2 size, Vector2 pos)
        {
            var go = CreateUiObject(name, parent, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), size, pos);
            var image = go.AddComponent<Image>();
            image.color = new Color(0.08f, 0.12f, 0.18f, 0.78f);
            return go;
        }

        private static Button CreateSectionButton(Transform parent, string label, Vector2 pos, Action onClick)
        {
            var button = CreateButton(parent, label, pos, onClick);
            var rect = button.GetComponent<RectTransform>();
            if (rect != null)
            {
                rect.sizeDelta = new Vector2(180f, 50f);
            }
            var text = button.GetComponentInChildren<Text>();
            if (text != null)
            {
                text.fontSize = 18;
            }
            return button;
        }

        private static void SetActiveSection(IReadOnlyDictionary<string, GameObject> sections, string activeKey)
        {
            foreach (var entry in sections)
            {
                if (entry.Value != null)
                {
                    entry.Value.SetActive(string.Equals(entry.Key, activeKey, StringComparison.Ordinal));
                }
            }
        }

        private static Slider CreateLabeledSlider(Transform parent, string label, Vector2 pos, float min, float max, Action<float> onChanged)
        {
            _ = CreateText(label.Replace(" ", string.Empty) + "Label", parent, label, 19, TextAnchor.MiddleLeft, new Vector2(0.5f, 0.5f), pos + new Vector2(0f, 28f), new Vector2(620f, 28f));
            return CreateSlider(parent, pos - new Vector2(0f, 10f), min, max, onChanged);
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

        private static void DisableLegacyWristMenus()
        {
            var wristMenus = FindObjectsByType<ByesWristMenuController>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            for (var i = 0; i < wristMenus.Length; i += 1)
            {
                var wristMenu = wristMenus[i];
                if (wristMenu == null)
                {
                    continue;
                }

                wristMenu.gameObject.SetActive(false);
            }
        }
    }
}
