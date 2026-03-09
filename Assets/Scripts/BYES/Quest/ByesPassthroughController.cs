using System;
using BYES.UI;
using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesPassthroughController : MonoBehaviour
    {
        public enum DisplayMode
        {
            Color = 0,
            Gray = 1,
        }

        [SerializeField] private bool enableOnQuestStart = true;

        private ByesQuestPassthroughSetup _setup;
        private string _status = "unavailable reason=unknown";
        private string _truthState = "unavailable";
        private string _reason = "unknown";
        private float _opacity = 1f;
        private DisplayMode _displayMode = DisplayMode.Color;
        private bool _requestedEnabled;

        public string StatusString => _status;
        public float Opacity => _opacity;
        public DisplayMode ColorMode => _displayMode;
        public string TruthState => _truthState;
        public string Reason => _reason;
        public bool RequestedEnabled => _requestedEnabled;
        public bool IsOperational => _requestedEnabled && !string.Equals(_truthState, "unavailable", StringComparison.OrdinalIgnoreCase);

        public bool IsAvailable()
        {
            return string.Equals(_truthState, "real", StringComparison.OrdinalIgnoreCase)
                   || string.Equals(_truthState, "fallback", StringComparison.OrdinalIgnoreCase)
                   || ResolveSetup(createIfMissing: false) != null;
        }

        public void SetEnabled(bool enabled)
        {
            _requestedEnabled = enabled;
            ApplyRequestedState();
        }

        public void SetOpacity(float value)
        {
            _opacity = Mathf.Clamp01(value);
            ApplyRequestedState();
        }

        public void SetColorMode(DisplayMode mode)
        {
            _displayMode = mode;
            ApplyRequestedState();
        }

        private void Awake()
        {
            _requestedEnabled = enableOnQuestStart;
            ApplyRequestedState();
        }

        private ByesQuestPassthroughSetup ResolveSetup(bool createIfMissing)
        {
            _setup ??= ByesQuestPassthroughSetup.Instance;
            if (_setup != null)
            {
                return _setup;
            }
            if (!createIfMissing)
            {
                return null;
            }
            _setup = ByesQuestPassthroughSetup.EnsureInstance();
            return _setup;
        }

        private void ApplyRequestedState()
        {
            var setup = ResolveSetup(createIfMissing: _requestedEnabled && Application.platform == RuntimePlatform.Android);
            if (!_requestedEnabled)
            {
                SafeDisable(setup);
                SetStatus("unavailable", "disabled");
                return;
            }

            var availabilityReason = EvaluateAvailabilityReason(setup);
            if (!string.IsNullOrWhiteSpace(availabilityReason))
            {
                SafeDisable(setup);
                SetStatus("unavailable", availabilityReason);
                return;
            }

            if (setup == null)
            {
                SetStatus("unavailable", "setup_missing");
                return;
            }

            try
            {
                setup.SetEnabled(true);
                setup.SetOpacity(_opacity);
                var setupMode = _displayMode == DisplayMode.Gray && setup.SupportsGrayMode
                    ? ByesQuestPassthroughSetup.PassthroughColorMode.Gray
                    : ByesQuestPassthroughSetup.PassthroughColorMode.Color;
                setup.SetColorMode(setupMode);

                if (_displayMode == DisplayMode.Gray && !setup.SupportsGrayMode)
                {
                    SetStatus("fallback", "gray_unsupported");
                    return;
                }

                if (!setup.IsEnabled)
                {
                    SafeDisable(setup);
                    SetStatus("unavailable", "not_ready");
                    return;
                }

                SetStatus("real", "quest_passthrough_ok");
            }
            catch (Exception ex)
            {
                SafeDisable(setup);
                SetStatus("unavailable", ex.GetType().Name.ToLowerInvariant());
                Debug.LogWarning("[ByesPassthroughController] passthrough apply failed: " + ex.Message);
            }
        }

        private static void SafeDisable(ByesQuestPassthroughSetup setup)
        {
            RestoreStableBackground(setup);
            if (setup == null)
            {
                return;
            }

            try
            {
                setup.SetEnabled(false);
            }
            catch
            {
                // Keep fallback path stable even if provider teardown fails.
            }
        }

        private string EvaluateAvailabilityReason(ByesQuestPassthroughSetup setup)
        {
            if (Application.isEditor || Application.platform != RuntimePlatform.Android)
            {
                return "link_unsupported";
            }

            if (!IsQuest3Family(SystemInfo.deviceModel))
            {
                return "unsupported_device";
            }

            if (setup == null)
            {
                return "setup_missing";
            }

            var camera = Camera.main != null ? Camera.main : FindFirstObjectByType<Camera>();
            if (camera == null)
            {
                return "camera_missing";
            }

            var cameraManagerType = Type.GetType("UnityEngine.XR.ARFoundation.ARCameraManager, Unity.XR.ARFoundation", throwOnError: false);
            var cameraBackgroundType = Type.GetType("UnityEngine.XR.ARFoundation.ARCameraBackground, Unity.XR.ARFoundation", throwOnError: false);
            if (cameraManagerType == null || cameraBackgroundType == null)
            {
                return "feature_disabled";
            }

            var cameraManager = camera.GetComponent(cameraManagerType) as Behaviour;
            var cameraBackground = camera.GetComponent(cameraBackgroundType) as Behaviour;
            if (cameraManager == null || cameraBackground == null)
            {
                return "feature_disabled";
            }

            if (!HasRequiredCameraPermission(cameraManager))
            {
                return "no_permission";
            }

            return null;
        }

        private static void RestoreStableBackground(ByesQuestPassthroughSetup setup)
        {
            try
            {
                if (setup != null)
                {
                    setup.SetOpacity(1f);
                    setup.SetColorMode(ByesQuestPassthroughSetup.PassthroughColorMode.Color);
                    setup.SetEnabled(false);
                    return;
                }
            }
            catch
            {
                // Fall through to a camera-level background reset.
            }

            var camera = Camera.main != null ? Camera.main : FindFirstObjectByType<Camera>();
            if (camera == null)
            {
                return;
            }

            camera.clearFlags = CameraClearFlags.SolidColor;
            var color = camera.backgroundColor;
            color.a = 1f;
            color.r = 0.03f;
            color.g = 0.03f;
            color.b = 0.03f;
            camera.backgroundColor = color;
        }

        private static bool HasRequiredCameraPermission(Behaviour cameraManager)
        {
            var arFoundationPermission = false;
            if (cameraManager != null)
            {
                try
                {
                    var permissionProperty = cameraManager.GetType().GetProperty("permissionGranted");
                    if (permissionProperty?.GetValue(cameraManager) is bool granted)
                    {
                        arFoundationPermission = granted;
                    }
                }
                catch
                {
                    arFoundationPermission = false;
                }
            }

#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                return arFoundationPermission
                       || UnityEngine.Android.Permission.HasUserAuthorizedPermission(UnityEngine.Android.Permission.Camera)
                       || UnityEngine.Android.Permission.HasUserAuthorizedPermission("horizonos.permission.USE_SCENE")
                       || UnityEngine.Android.Permission.HasUserAuthorizedPermission("horizonos.permission.USE_SCENE_UNDERSTANDING_COARSE");
            }
            catch
            {
                return arFoundationPermission;
            }
#else
            return arFoundationPermission;
#endif
        }

        private static bool IsQuest3Family(string deviceModel)
        {
            var lowered = string.IsNullOrWhiteSpace(deviceModel) ? string.Empty : deviceModel.Trim().ToLowerInvariant();
            return lowered.Contains("quest 3s")
                   || lowered.Contains("quest3s")
                   || lowered.Contains("quest 3")
                   || lowered.Contains("quest3");
        }

        private void SetStatus(string truthState, string reason)
        {
            _truthState = string.IsNullOrWhiteSpace(truthState) ? "unavailable" : truthState.Trim().ToLowerInvariant();
            _reason = string.IsNullOrWhiteSpace(reason) ? "unknown" : reason.Trim().ToLowerInvariant();
            _status = $"{_truthState} reason={_reason} requested={(_requestedEnabled ? "on" : "off")} opacity={_opacity:0.00} mode={_displayMode.ToString().ToLowerInvariant()}";
        }
    }
}
