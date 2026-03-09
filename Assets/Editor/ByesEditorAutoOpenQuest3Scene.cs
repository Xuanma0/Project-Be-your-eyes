#if UNITY_EDITOR
using System;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BYES.Editor
{
    [InitializeOnLoad]
    public static class ByesEditorAutoOpenQuest3Scene
    {
        private const string ScenePath = "Assets/Scenes/Quest3SmokeScene.unity";
        private const string PrefKey = "BYES.Editor.AutoOpenQuest3Scene";
        private const string MenuPath = "BYES/Quest3/Auto Open Quest3SmokeScene";

        static ByesEditorAutoOpenQuest3Scene()
        {
            if (Application.isBatchMode)
            {
                return;
            }

            EditorApplication.delayCall += TryOpenOnEditorLaunch;
            EditorApplication.playModeStateChanged += HandlePlayModeChange;
        }

        [MenuItem(MenuPath)]
        private static void ToggleAutoOpen()
        {
            var next = !IsEnabled();
            EditorPrefs.SetBool(PrefKey, next);
            Menu.SetChecked(MenuPath, next);
            Debug.Log($"[ByesEditorAutoOpenQuest3Scene] auto-open {(next ? "enabled" : "disabled")}");
        }

        [MenuItem(MenuPath, true)]
        private static bool ToggleAutoOpenValidate()
        {
            Menu.SetChecked(MenuPath, IsEnabled());
            return true;
        }

        private static bool IsEnabled()
        {
            return EditorPrefs.GetBool(PrefKey, true);
        }

        private static void TryOpenOnEditorLaunch()
        {
            if (!IsEnabled())
            {
                return;
            }

            OpenQuestSceneIfNeeded("launch");
        }

        private static void HandlePlayModeChange(PlayModeStateChange change)
        {
            if (!IsEnabled())
            {
                return;
            }

            if (change != PlayModeStateChange.ExitingEditMode)
            {
                return;
            }

            OpenQuestSceneIfNeeded("play");
        }

        private static void OpenQuestSceneIfNeeded(string reason)
        {
            if (Application.isBatchMode)
            {
                return;
            }

            if (!System.IO.File.Exists(ScenePath))
            {
                return;
            }

            var activeScene = SceneManager.GetActiveScene();
            if (string.Equals(activeScene.path, ScenePath, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }

            if (activeScene.IsValid() && activeScene.isDirty)
            {
                Debug.LogWarning("[ByesEditorAutoOpenQuest3Scene] skipped auto-open because active scene has unsaved changes.");
                return;
            }

            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            Debug.Log($"[ByesEditorAutoOpenQuest3Scene] opened {ScenePath} ({reason}).");
        }
    }
}
#endif
