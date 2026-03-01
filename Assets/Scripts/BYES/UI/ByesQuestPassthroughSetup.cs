using System;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BYES.UI
{
    public sealed class ByesQuestPassthroughSetup : MonoBehaviour
    {
        private const string PrefAutoInstall = "BYES_PASSTHROUGH_AUTOINSTALL";
        private static bool _missingArFoundationLogged;
        private static ByesQuestPassthroughSetup _instance;
        private bool _isEnabled;
        private Camera _camera;
        private Behaviour _cameraManager;
        private Behaviour _cameraBackground;

        public static ByesQuestPassthroughSetup Instance => _instance ?? FindFirstObjectByType<ByesQuestPassthroughSetup>();
        public bool IsEnabled => _isEnabled;

        public static ByesQuestPassthroughSetup EnsureInstance()
        {
            var existing = Instance;
            if (existing != null)
            {
                return existing;
            }

            var host = new GameObject("BYES_Quest3PassthroughSetup");
            return host.AddComponent<ByesQuestPassthroughSetup>();
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AutoInstallOnQuestSmokeScene()
        {
            var scene = SceneManager.GetActiveScene();
            if (!string.Equals(scene.name, "Quest3SmokeScene", StringComparison.Ordinal))
            {
                return;
            }

            // Keep startup stable on Quest: passthrough helper is opt-in unless explicitly enabled.
            if (PlayerPrefs.GetInt(PrefAutoInstall, 0) != 1)
            {
                return;
            }

            if (FindFirstObjectByType<ByesQuestPassthroughSetup>() == null)
            {
                var host = new GameObject("BYES_Quest3PassthroughSetup");
                host.AddComponent<ByesQuestPassthroughSetup>();
            }
        }

        private void Awake()
        {
            if (_instance != null && _instance != this)
            {
                Destroy(gameObject);
                return;
            }

            _instance = this;
            EnsureArSession();
            EnsureCameraPassthroughSettings();
            SetEnabled(_isEnabled);
        }

        private static void EnsureArSession()
        {
            var sessionType = ResolveType("UnityEngine.XR.ARFoundation.ARSession, Unity.XR.ARFoundation");
            if (sessionType == null)
            {
                LogMissingArFoundationOnce();
                return;
            }

            if (UnityEngine.Object.FindFirstObjectByType(sessionType) != null)
            {
                return;
            }

            var session = new GameObject("AR Session");
            session.AddComponent(sessionType);
        }

        private static void EnsureCameraPassthroughSettings()
        {
            var cam = Camera.main;
            if (cam == null)
            {
                cam = FindFirstObjectByType<Camera>();
            }

            if (cam == null)
            {
                return;
            }

            cam.clearFlags = CameraClearFlags.SolidColor;
            var color = cam.backgroundColor;
            color.a = 0f;
            cam.backgroundColor = color;

            var cameraManagerType = ResolveType("UnityEngine.XR.ARFoundation.ARCameraManager, Unity.XR.ARFoundation");
            var cameraBackgroundType = ResolveType("UnityEngine.XR.ARFoundation.ARCameraBackground, Unity.XR.ARFoundation");
            if (cameraManagerType == null || cameraBackgroundType == null)
            {
                LogMissingArFoundationOnce();
                return;
            }

            if (cam.GetComponent(cameraManagerType) == null)
            {
                cam.gameObject.AddComponent(cameraManagerType);
            }

            if (cam.GetComponent(cameraBackgroundType) == null)
            {
                cam.gameObject.AddComponent(cameraBackgroundType);
            }
        }

        public void SetEnabled(bool enabled)
        {
            _isEnabled = enabled;
            ApplyPassthroughState();
        }

        private void ApplyPassthroughState()
        {
            ResolveCameraAndComponents();
            if (_camera == null)
            {
                return;
            }

            _camera.clearFlags = CameraClearFlags.SolidColor;
            var color = _camera.backgroundColor;
            color.a = _isEnabled ? 0f : 1f;
            _camera.backgroundColor = color;

            if (_cameraManager != null)
            {
                _cameraManager.enabled = _isEnabled;
            }

            if (_cameraBackground != null)
            {
                _cameraBackground.enabled = _isEnabled;
            }
        }

        private void ResolveCameraAndComponents()
        {
            if (_camera == null || !_camera.isActiveAndEnabled)
            {
                _camera = Camera.main;
                if (_camera == null)
                {
                    _camera = FindFirstObjectByType<Camera>();
                }
            }

            if (_camera == null)
            {
                return;
            }

            var cameraManagerType = ResolveType("UnityEngine.XR.ARFoundation.ARCameraManager, Unity.XR.ARFoundation");
            var cameraBackgroundType = ResolveType("UnityEngine.XR.ARFoundation.ARCameraBackground, Unity.XR.ARFoundation");
            if (cameraManagerType != null && _cameraManager == null)
            {
                _cameraManager = _camera.GetComponent(cameraManagerType) as Behaviour;
            }

            if (cameraBackgroundType != null && _cameraBackground == null)
            {
                _cameraBackground = _camera.GetComponent(cameraBackgroundType) as Behaviour;
            }
        }

        private static Type ResolveType(string assemblyQualifiedName)
        {
            return Type.GetType(assemblyQualifiedName, throwOnError: false);
        }

        private static void LogMissingArFoundationOnce()
        {
            if (_missingArFoundationLogged)
            {
                return;
            }

            _missingArFoundationLogged = true;
            Debug.LogWarning("[ByesQuestPassthroughSetup] AR Foundation package not found. Quest passthrough helpers were skipped.");
        }
    }
}
