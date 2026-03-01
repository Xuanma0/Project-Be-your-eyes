using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BYES.Quest
{
    [DefaultExecutionOrder(-900)]
    public sealed class ByesMrTemplateGuideDisabler : MonoBehaviour
    {
        [SerializeField] private bool disableOnStart = true;
        [SerializeField] private bool includeInactiveSearch = true;
        [SerializeField] private bool verboseLog = true;

        private static string _lastSummary = "none";

        public static string LastSummary => _lastSummary;

        private void Start()
        {
            if (!disableOnStart)
            {
                return;
            }

            DisableGuideObjects();
        }

        public void DisableGuideObjects()
        {
            var disabled = new List<string>();
            var scene = SceneManager.GetActiveScene();
            var roots = scene.GetRootGameObjects();
            for (var i = 0; i < roots.Length; i += 1)
            {
                DisableRecursive(roots[i].transform, disabled);
            }

            var sb = new StringBuilder(128);
            sb.Append("disabled=").Append(disabled.Count);
            if (disabled.Count > 0)
            {
                sb.Append(" [");
                for (var i = 0; i < disabled.Count; i += 1)
                {
                    if (i > 0)
                    {
                        sb.Append(", ");
                    }

                    sb.Append(disabled[i]);
                }
                sb.Append(']');
            }

            _lastSummary = sb.ToString();
            if (verboseLog)
            {
                Debug.Log("[ByesMrTemplateGuideDisabler] " + _lastSummary);
            }
        }

        private void DisableRecursive(Transform node, List<string> disabled)
        {
            if (node == null)
            {
                return;
            }

            if (ShouldDisable(node.gameObject))
            {
                if (node.gameObject.activeSelf)
                {
                    node.gameObject.SetActive(false);
                    disabled.Add(node.name);
                }
            }

            for (var i = 0; i < node.childCount; i += 1)
            {
                var child = node.GetChild(i);
                if (child == null)
                {
                    continue;
                }

                if (!includeInactiveSearch && !child.gameObject.activeSelf)
                {
                    continue;
                }

                DisableRecursive(child, disabled);
            }
        }

        private static bool ShouldDisable(GameObject go)
        {
            if (go == null)
            {
                return false;
            }

            var name = go.name ?? string.Empty;
            if (name.StartsWith("BYES_", System.StringComparison.Ordinal))
            {
                return false;
            }

            var lowered = name.ToLowerInvariant();
            return lowered.Contains("coaching")
                   || lowered.Contains("tutorial player")
                   || lowered.Contains("hand menu setup mr template")
                   || lowered.Contains("guide")
                   || lowered.Contains("relaunch coaching")
                   || lowered.Contains("resetcoaching");
        }
    }
}
