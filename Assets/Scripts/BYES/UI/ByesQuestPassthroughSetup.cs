using System;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BYES.UI
{
    public sealed class ByesQuestPassthroughSetup : MonoBehaviour
    {
        private static bool _missingArFoundationLogged;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AutoInstallOnQuestSmokeScene()
        {
            var scene = SceneManager.GetActiveScene();
            if (!string.Equals(scene.name, "Quest3SmokeScene", StringComparison.Ordinal))
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
            EnsureArSession();
            EnsureCameraPassthroughSettings();
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
