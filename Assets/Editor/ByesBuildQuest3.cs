#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace BYES.Editor
{
    public static class ByesBuildQuest3
    {
        private const string QuestScenePath = "Assets/Scenes/Quest3SmokeScene.unity";
        private const string SampleScenePath = "Assets/Scenes/SampleScene.unity";
        private const string FallbackVersion = "v4.95";

        public static void BuildQuest3SmokeApk()
        {
            try
            {
                if (!BuildPipeline.IsBuildTargetSupported(BuildTargetGroup.Android, BuildTarget.Android))
                {
                    Debug.LogError(
                        "[ByesBuildQuest3] Android build target is not supported by this Unity installation. " +
                        "Please install Android Build Support (SDK/NDK/OpenJDK) for this editor and rerun."
                    );
                    EditorApplication.Exit(1);
                    return;
                }

                var switched = EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android);
                if (!switched)
                {
                    Debug.LogError(
                        "[ByesBuildQuest3] Failed to switch active build target to Android. " +
                        "Verify Android Build Support is installed for this Unity editor."
                    );
                    EditorApplication.Exit(1);
                    return;
                }

                PlayerSettings.SetScriptingBackend(BuildTargetGroup.Android, ScriptingImplementation.IL2CPP);
                PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;

                EditorUserBuildSettings.development = true;
                EditorUserBuildSettings.allowDebugging = false;

                var scenes = ResolveBuildScenes();
                if (scenes.Count == 0)
                {
                    Debug.LogError("[ByesBuildQuest3] No valid scenes resolved for Android build.");
                    EditorApplication.Exit(1);
                    return;
                }

                var repoRoot = ResolveRepoRoot();
                var version = ResolveVersion(repoRoot);
                var outputPath = Path.Combine(repoRoot, "Builds", "Quest3", $"BYES_Quest3Smoke_{version}.apk");
                Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? Path.Combine(repoRoot, "Builds", "Quest3"));

                var options = new BuildPlayerOptions
                {
                    scenes = scenes.ToArray(),
                    target = BuildTarget.Android,
                    targetGroup = BuildTargetGroup.Android,
                    locationPathName = outputPath,
                    options = BuildOptions.Development,
                };

                var report = BuildPipeline.BuildPlayer(options);
                var summary = report.summary;
                Debug.Log($"[ByesBuildQuest3] Result={summary.result} TotalErrors={summary.totalErrors} TotalWarnings={summary.totalWarnings} TotalSize={summary.totalSize} Output={summary.outputPath}");

                if (summary.result != BuildResult.Succeeded)
                {
                    LogBuildErrors(report);
                    EditorApplication.Exit(1);
                    return;
                }

                EditorApplication.Exit(0);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ByesBuildQuest3] Unhandled exception: {ex}");
                EditorApplication.Exit(1);
            }
        }

        private static List<string> ResolveBuildScenes()
        {
            var scenes = new List<string>();
            if (File.Exists(QuestScenePath))
            {
                scenes.Add(QuestScenePath);
            }

            if (File.Exists(SampleScenePath))
            {
                scenes.Add(SampleScenePath);
            }

            return scenes;
        }

        private static string ResolveRepoRoot()
        {
            return Directory.GetParent(Application.dataPath)?.FullName ?? Directory.GetCurrentDirectory();
        }

        private static string ResolveVersion(string repoRoot)
        {
            var versionFile = Path.Combine(repoRoot, "VERSION");
            if (!File.Exists(versionFile))
            {
                return FallbackVersion;
            }

            var version = File.ReadAllText(versionFile).Trim();
            if (string.IsNullOrWhiteSpace(version))
            {
                return FallbackVersion;
            }

            return version.StartsWith("v", StringComparison.OrdinalIgnoreCase) ? version : $"v{version}";
        }

        private static void LogBuildErrors(BuildReport report)
        {
            foreach (var step in report.steps)
            {
                var errors = step.messages.Where(msg => msg.type == LogType.Error).ToArray();
                if (errors.Length == 0)
                {
                    continue;
                }

                Debug.LogError($"[ByesBuildQuest3] Build step failed: {step.name}");
                foreach (var message in errors)
                {
                    Debug.LogError($"[ByesBuildQuest3] {message.content}");
                }
            }
        }
    }
}
#endif
