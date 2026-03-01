#if UNITY_EDITOR
using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace BYES.Editor
{
    /// <summary>
    /// Prevents the repo root VERSION file from shadowing the C++ standard header <version> on Windows.
    /// This runs for any Unity build entrypoint (Editor Build and batchmode build).
    /// </summary>
    public sealed class ByesVersionHeaderGuard : IPreprocessBuildWithReport, IPostprocessBuildWithReport
    {
        private const string VersionFileName = "VERSION";
        private const string TempFileName = "VERSION.unity-build-tmp";
        public int callbackOrder => int.MinValue;

        [InitializeOnLoadMethod]
        private static void RestoreIfNeededOnEditorLoad()
        {
            TryRestoreVersionFile();
        }

        public void OnPreprocessBuild(BuildReport report)
        {
            TryRestoreVersionFile();
            TryMoveVersionFileToTemp();
        }

        public void OnPostprocessBuild(BuildReport report)
        {
            TryRestoreVersionFile();
        }

        private static string ResolveRepoRoot()
        {
            return Directory.GetParent(Application.dataPath)?.FullName ?? Directory.GetCurrentDirectory();
        }

        private static string ResolveVersionPath()
        {
            return Path.Combine(ResolveRepoRoot(), VersionFileName);
        }

        private static string ResolveTempPath()
        {
            return Path.Combine(ResolveRepoRoot(), TempFileName);
        }

        private static void TryMoveVersionFileToTemp()
        {
            var versionPath = ResolveVersionPath();
            var tempPath = ResolveTempPath();

            if (!File.Exists(versionPath))
            {
                return;
            }

            try
            {
                if (File.Exists(tempPath))
                {
                    File.Delete(tempPath);
                }

                File.Move(versionPath, tempPath);
                Debug.Log("[ByesVersionHeaderGuard] Temporarily moved VERSION to avoid <version> header collision during IL2CPP build.");
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[ByesVersionHeaderGuard] Failed to move VERSION before build: {ex.Message}");
            }
        }

        private static void TryRestoreVersionFile()
        {
            var versionPath = ResolveVersionPath();
            var tempPath = ResolveTempPath();

            if (!File.Exists(tempPath))
            {
                return;
            }

            try
            {
                if (File.Exists(versionPath))
                {
                    File.Delete(versionPath);
                }

                File.Move(tempPath, versionPath);
                Debug.Log("[ByesVersionHeaderGuard] Restored VERSION after build.");
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[ByesVersionHeaderGuard] Failed to restore VERSION after build: {ex.Message}");
            }
        }
    }
}
#endif
