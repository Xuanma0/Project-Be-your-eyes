using System;
using UnityEngine;
using UnityEngine.SceneManagement;
using Unity.XR.ARFoundation;

namespace BYES.UI
{
    public sealed class ByesQuestPassthroughSetup : MonoBehaviour
    {
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
            if (FindFirstObjectByType<ARSession>() != null)
            {
                return;
            }

            var session = new GameObject("AR Session");
            session.AddComponent<ARSession>();
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

            if (cam.GetComponent<ARCameraManager>() == null)
            {
                cam.gameObject.AddComponent<ARCameraManager>();
            }

            if (cam.GetComponent<ARCameraBackground>() == null)
            {
                cam.gameObject.AddComponent<ARCameraBackground>();
            }
        }
    }
}
