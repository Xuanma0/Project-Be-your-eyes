#if UNITY_EDITOR
using System;
using BYES.Quest;
using BYES.XR;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Unity.Capture;
using BeYourEyes.Unity.Interaction;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BYES.Editor
{
    public static class ByesQuest3SmokeSceneInstaller
    {
        private const string ScenePath = "Assets/Scenes/Quest3SmokeScene.unity";
        private const string AppRootName = "AppRoot";
        private const string SmokeRigName = "BYES_SmokeRig";
        private const string PanelName = "BYES_ConnectionPanel";
        private const string XrUiGuardName = "BYES_XrUiWiringGuard";
        private const string FrameRigName = "BYES_FrameRig";
        private const string FrameCaptureHostName = "BYES_FrameCaptureHost";
        private const string GatewayClientHostName = "BYES_GatewayClient";
        private const string SelfTestHostName = "BYES_Quest3SelfTestRunner";

        [MenuItem("BYES/Quest3/Install Smoke Rig")]
        public static void InstallFromMenu()
        {
            InstallCore();
        }

        public static void InstallFromBatch()
        {
            try
            {
                InstallCore();
                EditorApplication.Exit(0);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ByesQuest3SmokeSceneInstaller] failed: {ex}");
                EditorApplication.Exit(1);
            }
        }

        private static void InstallCore()
        {
            var scene = EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);

            var appRoot = FindOrCreateRoot(scene, AppRootName);
            var smokeRig = FindOrCreateChild(appRoot.transform, SmokeRigName);
            smokeRig.transform.localPosition = Vector3.zero;
            smokeRig.transform.localRotation = Quaternion.identity;
            smokeRig.transform.localScale = Vector3.one;

            var panel = FindOrCreateChild(smokeRig.transform, PanelName);
            panel.transform.localPosition = Vector3.zero;
            panel.transform.localRotation = Quaternion.identity;
            panel.transform.localScale = Vector3.one;

            var xrUiGuard = FindOrCreateChild(smokeRig.transform, XrUiGuardName);
            xrUiGuard.transform.localPosition = Vector3.zero;
            xrUiGuard.transform.localRotation = Quaternion.identity;
            xrUiGuard.transform.localScale = Vector3.one;

            var frameRig = FindOrCreateChild(smokeRig.transform, FrameRigName);
            frameRig.transform.localPosition = Vector3.zero;
            frameRig.transform.localRotation = Quaternion.identity;
            frameRig.transform.localScale = Vector3.one;

            var frameCaptureHost = FindOrCreateChild(frameRig.transform, FrameCaptureHostName);
            frameCaptureHost.transform.localPosition = Vector3.zero;
            frameCaptureHost.transform.localRotation = Quaternion.identity;
            frameCaptureHost.transform.localScale = Vector3.one;

            var gatewayClientHost = FindOrCreateChild(frameRig.transform, GatewayClientHostName);
            gatewayClientHost.transform.localPosition = Vector3.zero;
            gatewayClientHost.transform.localRotation = Quaternion.identity;
            gatewayClientHost.transform.localScale = Vector3.one;

            var selfTestHost = FindOrCreateChild(smokeRig.transform, SelfTestHostName);
            selfTestHost.transform.localPosition = Vector3.zero;
            selfTestHost.transform.localRotation = Quaternion.identity;
            selfTestHost.transform.localScale = Vector3.one;

            _ = EnsureComponent<ByesHeadLockedPanel>(panel);
            _ = EnsureComponent<ByesQuest3ConnectionPanelMinimal>(panel);
            _ = EnsureComponent<ByesXrUiWiringGuard>(xrUiGuard);
            _ = EnsureComponent<ByesQuest3SelfTestRunner>(selfTestHost);

            var gatewayClient = EnsureComponent<GatewayClient>(gatewayClientHost);
            var grabber = EnsureComponent<ScreenFrameGrabber>(frameCaptureHost);
            var frameCapture = EnsureComponent<FrameCapture>(frameCaptureHost);
            _ = EnsureComponent<GatewayFrameUploader>(frameCaptureHost);
            var scanController = EnsureComponent<ScanController>(frameCaptureHost);

            ConfigureQuestSmokeDefaults(gatewayClient, grabber, frameCapture, scanController);

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);

            Debug.Log($"[ByesQuest3SmokeSceneInstaller] installed at {AppRootName}/{SmokeRigName}/{PanelName} + {FrameRigName} + {XrUiGuardName}");
        }

        private static GameObject FindOrCreateRoot(Scene scene, string name)
        {
            foreach (var root in scene.GetRootGameObjects())
            {
                if (string.Equals(root.name, name, StringComparison.Ordinal))
                {
                    return root;
                }
            }

            var created = new GameObject(name);
            SceneManager.MoveGameObjectToScene(created, scene);
            return created;
        }

        private static GameObject FindOrCreateChild(Transform parent, string name)
        {
            var child = parent.Find(name);
            if (child != null)
            {
                return child.gameObject;
            }

            var created = new GameObject(name);
            created.transform.SetParent(parent, false);
            return created;
        }

        private static T EnsureComponent<T>(GameObject go) where T : Component
        {
            var existing = go.GetComponent<T>();
            if (existing != null)
            {
                return existing;
            }

            return go.AddComponent<T>();
        }

        private static void ConfigureQuestSmokeDefaults(
            GatewayClient gatewayClient,
            ScreenFrameGrabber grabber,
            FrameCapture frameCapture,
            ScanController scanController)
        {
            if (gatewayClient != null)
            {
                var so = new SerializedObject(gatewayClient);
                SetStringIfExists(so, "baseUrl", "http://127.0.0.1:18000");
                SetStringIfExists(so, "wsUrl", "ws://127.0.0.1:18000/ws/events");
                SetBoolIfExists(so, "connectOnEnable", true);
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            if (grabber != null)
            {
                var so = new SerializedObject(grabber);
                SetIntIfExists(so, "maxWidth", 960);
                SetIntIfExists(so, "maxHeight", 540);
                SetIntIfExists(so, "jpegQuality", 70);
                SetBoolIfExists(so, "keepAspect", true);
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            if (frameCapture != null)
            {
                var so = new SerializedObject(frameCapture);
                SetBoolIfExists(so, "autoStart", false);
                SetIntIfExists(so, "captureWidth", 960);
                SetIntIfExists(so, "captureHeight", 540);
                SetIntIfExists(so, "normalJpegQuality", 70);
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            if (scanController != null)
            {
                var so = new SerializedObject(scanController);
                SetBoolIfExists(so, "liveEnabledDefault", false);
                SetFloatIfExists(so, "liveFps", 1f);
                SetIntIfExists(so, "liveMaxInflight", 1);
                SetBoolIfExists(so, "liveDropIfBusy", true);
                so.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        private static void SetBoolIfExists(SerializedObject so, string fieldName, bool value)
        {
            var prop = so.FindProperty(fieldName);
            if (prop != null)
            {
                prop.boolValue = value;
            }
        }

        private static void SetIntIfExists(SerializedObject so, string fieldName, int value)
        {
            var prop = so.FindProperty(fieldName);
            if (prop != null)
            {
                prop.intValue = value;
            }
        }

        private static void SetFloatIfExists(SerializedObject so, string fieldName, float value)
        {
            var prop = so.FindProperty(fieldName);
            if (prop != null)
            {
                prop.floatValue = value;
            }
        }

        private static void SetStringIfExists(SerializedObject so, string fieldName, string value)
        {
            var prop = so.FindProperty(fieldName);
            if (prop != null)
            {
                prop.stringValue = value ?? string.Empty;
            }
        }
    }
}
#endif
