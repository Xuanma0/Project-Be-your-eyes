#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace BYES.Editor
{
    /// <summary>
    /// Workaround for occasional non-deterministic serialization order in OpenXR package settings.
    /// It keeps Keys/Values sorted by BuildTargetGroup int value to avoid importer "inconsistent result" churn.
    /// </summary>
    [InitializeOnLoad]
    public static class ByesOpenXRSettingsStabilizer
    {
        private const string AssetPath = "Assets/XR/Settings/OpenXRPackageSettings.asset";
        private const string SessionFlag = "BYES.OpenXRSettingsStabilizer.Done";

        static ByesOpenXRSettingsStabilizer()
        {
            EditorApplication.delayCall += StabilizeOncePerSession;
        }

        [MenuItem("BYES/Tools/Stabilize OpenXR Package Settings")]
        public static void StabilizeFromMenu()
        {
            TryStabilize(forceLog: true);
        }

        // Used by CI/batch if needed: -executeMethod BYES.Editor.ByesOpenXRSettingsStabilizer.StabilizeFromBatch
        public static void StabilizeFromBatch()
        {
            try
            {
                TryStabilize(forceLog: true);
                EditorApplication.Exit(0);
            }
            catch (Exception ex)
            {
                Debug.LogError($"[ByesOpenXRSettingsStabilizer] batch failed: {ex}");
                EditorApplication.Exit(1);
            }
        }

        private static void StabilizeOncePerSession()
        {
            if (SessionState.GetBool(SessionFlag, false))
            {
                return;
            }

            SessionState.SetBool(SessionFlag, true);
            TryStabilize(forceLog: false);
        }

        private static bool TryStabilize(bool forceLog)
        {
            var settingsObject = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(AssetPath);
            if (settingsObject == null)
            {
                if (forceLog)
                {
                    Debug.LogWarning($"[ByesOpenXRSettingsStabilizer] asset not found: {AssetPath}");
                }
                return false;
            }

            var settingsType = settingsObject.GetType();
            var keysField = settingsType.GetField("Keys", BindingFlags.Instance | BindingFlags.NonPublic);
            var valuesField = settingsType.GetField("Values", BindingFlags.Instance | BindingFlags.NonPublic);
            var dictField = settingsType.GetField("Settings", BindingFlags.Instance | BindingFlags.NonPublic);
            if (keysField == null || valuesField == null)
            {
                if (forceLog)
                {
                    Debug.LogWarning("[ByesOpenXRSettingsStabilizer] Reflection fields not found (Keys/Values). OpenXR package format may have changed.");
                }
                return false;
            }

            if (keysField.GetValue(settingsObject) is not System.Collections.IList keysList ||
                valuesField.GetValue(settingsObject) is not System.Collections.IList valuesList)
            {
                if (forceLog)
                {
                    Debug.LogWarning("[ByesOpenXRSettingsStabilizer] Keys/Values are not IList at runtime.");
                }
                return false;
            }

            var count = Mathf.Min(keysList.Count, valuesList.Count);
            if (count <= 1)
            {
                return false;
            }

            var entries = new List<Entry>(count);
            for (var i = 0; i < count; i += 1)
            {
                var keyValue = keysList[i];
                var keyInt = Convert.ToInt32(keyValue);
                var valueObj = valuesList[i] as UnityEngine.Object;
                entries.Add(new Entry
                {
                    KeyEnumValue = keyValue,
                    Key = keyInt,
                    Value = valueObj,
                });
            }

            entries.Sort((a, b) =>
            {
                var byKey = a.Key.CompareTo(b.Key);
                if (byKey != 0)
                {
                    return byKey;
                }
                var aName = a.Value != null ? a.Value.name : string.Empty;
                var bName = b.Value != null ? b.Value.name : string.Empty;
                return string.CompareOrdinal(aName, bName);
            });

            var changed = false;
            for (var i = 0; i < count; i += 1)
            {
                if (!Equals(keysList[i], entries[i].KeyEnumValue))
                {
                    keysList[i] = entries[i].KeyEnumValue;
                    changed = true;
                }

                if (!ReferenceEquals(valuesList[i], entries[i].Value))
                {
                    valuesList[i] = entries[i].Value;
                    changed = true;
                }
            }

            if (!changed)
            {
                return false;
            }

            if (dictField != null)
            {
                var dictType = dictField.FieldType;
                if (Activator.CreateInstance(dictType) is System.Collections.IDictionary newDict)
                {
                    foreach (var entry in entries)
                    {
                        newDict.Add(entry.KeyEnumValue, entry.Value);
                    }
                    dictField.SetValue(settingsObject, newDict);
                }
            }

            EditorUtility.SetDirty(settingsObject);
            AssetDatabase.ForceReserializeAssets(new[] { AssetPath });
            AssetDatabase.SaveAssetIfDirty(settingsObject);
            AssetDatabase.ImportAsset(AssetPath, ImportAssetOptions.ForceUpdate);

            if (forceLog)
            {
                Debug.Log("[ByesOpenXRSettingsStabilizer] OpenXRPackageSettings keys/values reordered to deterministic order.");
            }

            return true;
        }

        private struct Entry
        {
            public object KeyEnumValue;
            public int Key;
            public UnityEngine.Object Value;
        }
    }
}
#endif
