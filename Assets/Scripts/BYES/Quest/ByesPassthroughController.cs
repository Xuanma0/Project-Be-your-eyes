using System;
using BYES.UI;
using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesPassthroughController : MonoBehaviour
    {
        [SerializeField] private bool enableOnQuestStart = true;

        private ByesQuestPassthroughSetup _setup;
        private string _status = "unknown";

        public string StatusString => _status;

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
