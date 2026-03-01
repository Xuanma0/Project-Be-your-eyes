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
        private const string HandMenuRootName = "BYES_HandMenuRoot";
        private const string GuideDisablerName = "BYES_MrTemplateGuideDisabler";
        private const string LegacyWristMenuName = "BYES_WristMenu";
        private const string HandMenuPrefabPath = "Assets/Prefabs/BYES/Quest/BYES_HandMenu.prefab";
        private const string SampleHandMenuRigPrefabPath = "Assets/Samples/XR Interaction Toolkit/3.3.0/Hands Interaction Demo/Prefabs/HandMenuRig.prefab";
        private const string MrTemplateHandMenuPrefabPath = "Assets/MRTemplateAssets/Prefabs/UI/HandMenuSetupVariant_MRTemplate.prefab";
        private const string MrTemplateCoachingPrefabPath = "Assets/MRTemplateAssets/Prefabs/UI/CoachingUI.prefab";

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

            var legacyWristMenu = smokeRig.transform.Find(LegacyWristMenuName);
            if (legacyWristMenu != null)
            {
                UnityEngine.Object.DestroyImmediate(legacyWristMenu.gameObject);
            }

            var handMenuPrefab = EnsureHandMenuPrefab();
            var handMenuRoot = EnsureHandMenuInstance(smokeRig.transform, handMenuPrefab);
            handMenuRoot.transform.localPosition = Vector3.zero;
            handMenuRoot.transform.localRotation = Quaternion.identity;
            handMenuRoot.transform.localScale = Vector3.one;

            var guideDisablerHost = FindOrCreateChild(smokeRig.transform, GuideDisablerName);
            guideDisablerHost.transform.localPosition = Vector3.zero;
            guideDisablerHost.transform.localRotation = Quaternion.identity;
            guideDisablerHost.transform.localScale = Vector3.one;

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
            _ = EnsureComponent<ByesHandMenuController>(handMenuRoot);
            _ = EnsureComponent<ByesHandGestureShortcuts>(handMenuRoot);
            _ = EnsureComponent<ByesMrTemplateGuideDisabler>(guideDisablerHost);
            _ = EnsureComponent<ByesXrUiWiringGuard>(xrUiGuard);
            _ = EnsureComponent<ByesQuest3SelfTestRunner>(selfTestHost);

            var gatewayClient = EnsureComponent<GatewayClient>(gatewayClientHost);
            var grabber = EnsureComponent<ScreenFrameGrabber>(frameCaptureHost);
            var frameCapture = EnsureComponent<FrameCapture>(frameCaptureHost);
            _ = EnsureComponent<GatewayFrameUploader>(frameCaptureHost);
            var scanController = EnsureComponent<ScanController>(frameCaptureHost);
            _ = EnsureComponent<ByesHitchMonitor>(frameCaptureHost);

            ConfigureQuestSmokeDefaults(gatewayClient, grabber, frameCapture, scanController);
            var removedTemplateUiCount = RemoveTemplateUiInstances(scene);
            var disabledCoachingCount = DisableCoachingUi(scene);
            EnsureBuildSettingsQuestOnly();

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);

            Debug.Log($"[ByesQuest3SmokeSceneInstaller] installed at {AppRootName}/{SmokeRigName}/{PanelName} + {HandMenuRootName} + {FrameRigName} + {XrUiGuardName}; templateUiRemoved={removedTemplateUiCount}; coachingDisabled={disabledCoachingCount}");
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

            var grabHandle = UnityEngine.Object.FindFirstObjectByType<ByesSmokePanelGrabHandle>();
            if (grabHandle != null)
            {
                var so = new SerializedObject(grabHandle);
                SetBoolIfExists(so, "moveResizeEnabled", false);
                SetBoolIfExists(so, "restoreHeadLockAfterRelease", true);
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            var headLockedPanel = UnityEngine.Object.FindFirstObjectByType<ByesHeadLockedPanel>();
            if (headLockedPanel != null)
            {
                var so = new SerializedObject(headLockedPanel);
                SetBoolIfExists(so, "lockToHead", true);
                so.ApplyModifiedPropertiesWithoutUndo();
            }

            var shortcut = UnityEngine.Object.FindFirstObjectByType<ByesHandGestureShortcuts>();
            if (shortcut != null)
            {
                var so = new SerializedObject(shortcut);
                SetBoolIfExists(so, "shortcutsEnabled", true);
                SetIntIfExists(so, "shortcutHand", 0);
                SetIntIfExists(so, "conflictMode", 0);
                so.ApplyModifiedPropertiesWithoutUndo();
            }
        }

        private static GameObject EnsureHandMenuPrefab()
        {
            EnsureFolder("Assets/Prefabs");
            EnsureFolder("Assets/Prefabs/BYES");
            EnsureFolder("Assets/Prefabs/BYES/Quest");

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(HandMenuPrefabPath);
            if (prefab != null)
            {
                return prefab;
            }

            var temp = new GameObject(HandMenuRootName);
            temp.AddComponent<ByesHandMenuController>();

            var sampleRig = AssetDatabase.LoadAssetAtPath<GameObject>(SampleHandMenuRigPrefabPath);
            if (sampleRig != null)
            {
                var sampleInstance = PrefabUtility.InstantiatePrefab(sampleRig, temp.transform) as GameObject;
                if (sampleInstance != null)
                {
                    sampleInstance.name = "OfficialHandMenuRig";
                    sampleInstance.transform.localPosition = Vector3.zero;
                    sampleInstance.transform.localRotation = Quaternion.identity;
                    sampleInstance.transform.localScale = Vector3.one;
                }
            }

            var saved = PrefabUtility.SaveAsPrefabAsset(temp, HandMenuPrefabPath);
            UnityEngine.Object.DestroyImmediate(temp);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            return saved;
        }

        private static GameObject EnsureHandMenuInstance(Transform parent, GameObject prefab)
        {
            var existing = parent.Find(HandMenuRootName);
            if (prefab == null)
            {
                return existing != null ? existing.gameObject : FindOrCreateChild(parent, HandMenuRootName);
            }

            if (existing == null)
            {
                var instantiated = PrefabUtility.InstantiatePrefab(prefab, parent) as GameObject;
                if (instantiated != null)
                {
                    instantiated.name = HandMenuRootName;
                    return instantiated;
                }

                return FindOrCreateChild(parent, HandMenuRootName);
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
                replacement.name = HandMenuRootName;
                return replacement;
            }

            return FindOrCreateChild(parent, HandMenuRootName);
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

        private static int RemoveTemplateUiInstances(Scene scene)
        {
            var removed = 0;
            var roots = scene.GetRootGameObjects();
            for (var i = roots.Length - 1; i >= 0; i -= 1)
            {
                removed += RemoveTemplateUiRecursive(roots[i].transform);
            }

            return removed;
        }

        private static int RemoveTemplateUiRecursive(Transform node)
        {
            if (node == null)
            {
                return 0;
            }

            var removed = 0;
            for (var i = node.childCount - 1; i >= 0; i -= 1)
            {
                removed += RemoveTemplateUiRecursive(node.GetChild(i));
            }

            if (ShouldRemoveTemplateUi(node.gameObject))
            {
                UnityEngine.Object.DestroyImmediate(node.gameObject);
                removed += 1;
            }

            return removed;
        }

        private static bool ShouldRemoveTemplateUi(GameObject go)
        {
            if (go == null)
            {
                return false;
            }

            var name = go.name ?? string.Empty;
            if (name.StartsWith("BYES_", StringComparison.Ordinal))
            {
                return false;
            }

            var lowered = name.ToLowerInvariant();
            if (lowered.Contains("hand menu setup mr template")
                || lowered.Contains("coaching ui")
                || lowered.Contains("tutorial player")
                || lowered.Contains("player setting"))
            {
                return true;
            }

            var prefabPath = PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot(go);
            if (string.IsNullOrWhiteSpace(prefabPath))
            {
                return false;
            }

            return string.Equals(prefabPath, MrTemplateHandMenuPrefabPath, StringComparison.OrdinalIgnoreCase)
                   || string.Equals(prefabPath, MrTemplateCoachingPrefabPath, StringComparison.OrdinalIgnoreCase);
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

        private static void EnsureBuildSettingsQuestOnly()
        {
            var scenes = new[]
            {
                new EditorBuildSettingsScene(ScenePath, true),
            };
            EditorBuildSettings.scenes = scenes;
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
