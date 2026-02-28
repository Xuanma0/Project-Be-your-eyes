#if UNITY_EDITOR
using System;
using BYES.Quest;
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

            _ = EnsureComponent<ByesHeadLockedPanel>(panel);
            _ = EnsureComponent<ByesQuest3ConnectionPanelMinimal>(panel);

            EditorSceneManager.MarkSceneDirty(scene);
            EditorSceneManager.SaveScene(scene);

            Debug.Log($"[ByesQuest3SmokeSceneInstaller] installed at {AppRootName}/{SmokeRigName}/{PanelName}");
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
    }
}
#endif
