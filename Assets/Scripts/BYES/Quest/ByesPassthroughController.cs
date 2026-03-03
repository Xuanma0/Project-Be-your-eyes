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
        private string _status = "unknown";
        private float _opacity = 1f;
        private DisplayMode _displayMode = DisplayMode.Color;

        public string StatusString => _status;
        public float Opacity => _opacity;
        public DisplayMode ColorMode => _displayMode;

        public bool IsAvailable()
        {
            return ResolveSetup(createIfMissing: false) != null;
        }

        public void SetEnabled(bool enabled)
        {
            var setup = ResolveSetup(createIfMissing: true);
            if (setup == null)
            {
                _status = "unavailable (missing setup)";
                return;
            }

            try
            {
                setup.SetEnabled(enabled);
                _status = enabled ? "enabled" : "disabled";
            }
            catch (Exception ex)
            {
                _status = "error: " + ex.GetType().Name;
                Debug.LogWarning("[ByesPassthroughController] set failed: " + ex.Message);
            }
        }

        public void SetOpacity(float value)
        {
            _opacity = Mathf.Clamp01(value);
            var setup = ResolveSetup(createIfMissing: true);
            if (setup == null)
            {
                _status = "unavailable (missing setup)";
                return;
            }
            try
            {
                setup.SetOpacity(_opacity);
                _status = $"{(_setup != null && _setup.IsEnabled ? "enabled" : "disabled")} opacity={_opacity:0.00}";
            }
            catch (Exception ex)
            {
                _status = "error: " + ex.GetType().Name;
                Debug.LogWarning("[ByesPassthroughController] opacity failed: " + ex.Message);
            }
        }

        public void SetColorMode(DisplayMode mode)
        {
            _displayMode = mode;
            var setup = ResolveSetup(createIfMissing: true);
            if (setup == null)
            {
                _status = "unavailable (missing setup)";
                return;
            }
            try
            {
                var setupMode = mode == DisplayMode.Gray
                    ? ByesQuestPassthroughSetup.PassthroughColorMode.Gray
                    : ByesQuestPassthroughSetup.PassthroughColorMode.Color;
                setup.SetColorMode(setupMode);
                if (mode == DisplayMode.Gray && !setup.SupportsGrayMode)
                {
                    _status = "enabled (gray unsupported)";
                }
                else
                {
                    _status = $"enabled ({mode.ToString().ToLowerInvariant()})";
                }
            }
            catch (Exception ex)
            {
                _status = "error: " + ex.GetType().Name;
                Debug.LogWarning("[ByesPassthroughController] color mode failed: " + ex.Message);
            }
        }

        private void Awake()
        {
            if (Application.platform != RuntimePlatform.Android)
            {
                _status = "unavailable (not android)";
                return;
            }

            var setup = ResolveSetup(createIfMissing: true);
            if (setup == null)
            {
                _status = "unavailable (setup missing)";
                return;
            }

            if (enableOnQuestStart)
            {
                setup.SetEnabled(true);
                _status = "enabled";
            }
            else
            {
                _status = setup.IsEnabled ? "enabled" : "disabled";
            }
            setup.SetOpacity(_opacity);
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
    }
}
