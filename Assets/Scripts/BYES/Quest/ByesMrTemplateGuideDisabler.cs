using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BYES.Quest
{
    [DefaultExecutionOrder(-2200)]
    public sealed class ByesMrTemplateGuideDisabler : MonoBehaviour
    {
        [SerializeField] private bool disableOnStart = true;
        [SerializeField] private bool includeInactiveSearch = true;
        [SerializeField] private bool verboseLog = true;
        [SerializeField] private bool repeatForFirstSeconds = true;
        [SerializeField] private float repeatDurationSec = 5f;
        [SerializeField] private float repeatIntervalSec = 0.5f;

        private static string _lastSummary = "none";
        private Coroutine _repeatCoroutine;

        public static string LastSummary => _lastSummary;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AutoInstallOnQuest3Scene()
        {
            var scene = SceneManager.GetActiveScene();
            if (!string.Equals(scene.name, "Quest3SmokeScene", System.StringComparison.Ordinal))
            {
                return;
            }

            var disabler = FindFirstObjectByType<ByesMrTemplateGuideDisabler>(FindObjectsInactive.Include);
            if (disabler != null)
            {
                if (!disabler.gameObject.activeSelf)
                {
                    disabler.gameObject.SetActive(true);
                }

                disabler.DisableGuideObjects();
                return;
            }

            var host = new GameObject("BYES_MrTemplateGuideDisabler_Auto");
            host.AddComponent<ByesMrTemplateGuideDisabler>();
        }

        private void Awake()
        {
            if (disableOnStart)
            {
                DisableGuideObjects();
            }
        }

        private void OnEnable()
        {
            if (disableOnStart && repeatForFirstSeconds && _repeatCoroutine == null)
            {
                _repeatCoroutine = StartCoroutine(RepeatDisable());
            }
        }

        private void OnDisable()
        {
            if (_repeatCoroutine != null)
            {
                StopCoroutine(_repeatCoroutine);
                _repeatCoroutine = null;
            }
        }

        private void Start()
        {
            if (!disableOnStart)
            {
                return;
            }

            DisableGuideObjects();
        }

        private System.Collections.IEnumerator RepeatDisable()
        {
            var endTs = Time.unscaledTime + Mathf.Max(0f, repeatDurationSec);
            while (Time.unscaledTime < endTs)
            {
                DisableGuideObjects();
                yield return new WaitForSecondsRealtime(Mathf.Max(0.2f, repeatIntervalSec));
            }

            _repeatCoroutine = null;
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

            var components = go.GetComponents<Component>();
            for (var i = 0; i < components.Length; i += 1)
            {
                var component = components[i];
                if (component == null)
                {
                    continue;
                }

                var fullName = component.GetType().FullName ?? string.Empty;
                // Disable only known onboarding/guide components.
                // Avoid broad "disable all MR template components" to prevent breaking core XR/camera objects.
                if (string.Equals(fullName, "UnityEngine.XR.Templates.MR.GoalManager", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.GazeTooltips", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.DebugInfoDisplayController", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.BooleanToggleVisualsController", System.StringComparison.Ordinal))
                {
                    return true;
                }
            }

            if (name.StartsWith("BYES_", System.StringComparison.Ordinal))
            {
                return false;
            }

            var lowered = name.ToLowerInvariant();
            if (lowered.Contains("coaching")
                   || lowered.Contains("tutorial player")
                   || lowered.Contains("hand menu setup mr template")
                   || lowered.Contains("mr interaction setup")
                   || lowered.Contains("player setting")
                   || lowered.Contains("guide")
                   || lowered.Contains("relaunch coaching")
                   || lowered.Contains("resetcoaching"))
            {
                return true;
            }

            return ContainsPlayerSettingsLabel(go);
        }

        private static bool ContainsPlayerSettingsLabel(GameObject root)
        {
            var components = root.GetComponentsInChildren<Component>(true);
            for (var i = 0; i < components.Length; i += 1)
            {
                var component = components[i];
                if (component == null)
                {
                    continue;
                }

                var type = component.GetType();
                var fullName = type.FullName ?? string.Empty;
                var isTextLike = fullName == "UnityEngine.UI.Text"
                                 || fullName == "TMPro.TextMeshProUGUI"
                                 || fullName == "TMPro.TMP_Text";
                if (!isTextLike)
                {
                    continue;
                }

                var textProperty = type.GetProperty("text");
                if (textProperty == null)
                {
                    continue;
                }

                var value = textProperty.GetValue(component, null) as string;
                if (string.IsNullOrWhiteSpace(value))
                {
                    continue;
                }

                if (value.IndexOf("player setting", System.StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }

            return false;
        }
    }
}
