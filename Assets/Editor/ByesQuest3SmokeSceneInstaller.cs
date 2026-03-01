#if UNITY_EDITOR
using System;
using BYES.Quest;
using BYES.Telemetry;
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
        private const string WristMenuName = "BYES_WristMenu";
        private const string GestureShortcutsName = "BYES_HandGestureShortcuts";
        private const string WristMenuPrefabPath = "Assets/Prefabs/BYES/Quest/BYES_WristMenu.prefab";

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

            var wristMenuPrefab = EnsureWristMenuPrefab();
            var wristMenu = EnsureWristMenuInstance(smokeRig.transform, wristMenuPrefab);
            wristMenu.transform.localPosition = Vector3.zero;
            wristMenu.transform.localRotation = Quaternion.identity;
            wristMenu.transform.localScale = Vector3.one;

            var gestureShortcuts = FindOrCreateChild(smokeRig.transform, GestureShortcutsName);
            gestureShortcuts.transform.localPosition = Vector3.zero;
            gestureShortcuts.transform.localRotation = Quaternion.identity;
            gestureShortcuts.transform.localScale = Vector3.one;

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
            _ = EnsureComponent<ByesSmokePanelGrabHandle>(panel);
            _ = EnsureComponent<ByesWristMenuController>(wristMenu);
            _ = EnsureComponent<ByesWristMenuAnchor>(wristMenu);
            _ = EnsureComponent<ByesHandGestureShortcuts>(gestureShortcuts);
            _ = EnsureComponent<ByesXrUiWiringGuard>(xrUiGuard);
            _ = EnsureComponent<ByesQuest3SelfTestRunner>(selfTestHost);

            var gatewayClient = EnsureComponent<GatewayClient>(gatewayClientHost);
            var grabber = EnsureComponent<ScreenFrameGrabber>(frameCaptureHost);
            var frameCapture = EnsureComponent<FrameCapture>(frameCaptureHost);
            _ = EnsureComponent<GatewayFrameUploader>(frameCaptureHost);
            var scanController = EnsureComponent<ScanController>(frameCaptureHost);
            _ = EnsureComponent<ByesHitchMonitor>(frameCaptureHost);

            ConfigureQuestSmokeDefaults(gatewayClient, grabber, frameCapture, scanController);
            var disabledCoachingCount = DisableCoachingUi(scene);

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);

            Debug.Log($"[ByesQuest3SmokeSceneInstaller] installed at {AppRootName}/{SmokeRigName}/{PanelName} + {WristMenuName} + {FrameRigName} + {XrUiGuardName}; coachingDisabled={disabledCoachingCount}");
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

            var panel = UnityEngine.Object.FindFirstObjectByType<ByesQuest3ConnectionPanelMinimal>();
            if (panel != null)
            {
                var so = new SerializedObject(panel);
                SetBoolIfExists(so, "showActionControlsOnAndroid", false);
                SetBoolIfExists(so, "autoProbeOnAndroid", false);
                SetFloatIfExists(so, "defaultPanelDistance", 0.55f);
                SetFloatIfExists(so, "defaultPanelScale", 1f);
                so.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        private static GameObject EnsureWristMenuPrefab()
        {
            EnsureFolder("Assets/Prefabs");
            EnsureFolder("Assets/Prefabs/BYES");
            EnsureFolder("Assets/Prefabs/BYES/Quest");

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(WristMenuPrefabPath);
            if (prefab != null)
            {
                return prefab;
            }

            var temp = new GameObject(WristMenuName);
            temp.AddComponent<ByesWristMenuController>();
            temp.AddComponent<ByesWristMenuAnchor>();
            var saved = PrefabUtility.SaveAsPrefabAsset(temp, WristMenuPrefabPath);
            UnityEngine.Object.DestroyImmediate(temp);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            return saved;
        }

        private static GameObject EnsureWristMenuInstance(Transform parent, GameObject prefab)
        {
            var existing = parent.Find(WristMenuName);
            if (prefab == null)
            {
                return existing != null ? existing.gameObject : FindOrCreateChild(parent, WristMenuName);
            }

            if (existing == null)
            {
                var instantiated = PrefabUtility.InstantiatePrefab(prefab, parent) as GameObject;
                if (instantiated != null)
                {
                    instantiated.name = WristMenuName;
                    return instantiated;
                }

                return FindOrCreateChild(parent, WristMenuName);
            }

            var source = PrefabUtility.GetCorrespondingObjectFromSource(existing.gameObject);
            if (source == prefab)
            {
                return existing.gameObject;
            }

            UnityEngine.Object.DestroyImmediate(existing.gameObject);
            var replacement = PrefabUtility.InstantiatePrefab(prefab, parent) as GameObject;
            if (replacement != null)
            {
                replacement.name = WristMenuName;
                return replacement;
            }

            return FindOrCreateChild(parent, WristMenuName);
        }

        private static int DisableCoachingUi(Scene scene)
        {
            var disabled = 0;
            foreach (var root in scene.GetRootGameObjects())
            {
                disabled += DisableCoachingRecursive(root.transform);
            }

            return disabled;
        }

        private static int DisableCoachingRecursive(Transform node)
        {
            if (node == null)
            {
                return 0;
            }

            var disabled = 0;
            var lowered = node.name.ToLowerInvariant();
            if (lowered.Contains("coaching") || lowered.Contains("tutorial") || lowered.Contains("guide"))
            {
                if (node.gameObject.activeSelf)
                {
                    node.gameObject.SetActive(false);
                    disabled += 1;
                }
            }

            for (var i = 0; i < node.childCount; i += 1)
            {
                disabled += DisableCoachingRecursive(node.GetChild(i));
            }

            return disabled;
        }

        private static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path))
            {
                return;
            }

            var parent = System.IO.Path.GetDirectoryName(path)?.Replace("\\", "/");
            var leaf = System.IO.Path.GetFileName(path);
            if (string.IsNullOrWhiteSpace(parent) || string.IsNullOrWhiteSpace(leaf))
            {
                return;
            }

            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, leaf);
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
