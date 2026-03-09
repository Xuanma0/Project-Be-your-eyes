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
        private int _consecutiveNoopPasses;

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
                if (_consecutiveNoopPasses >= 2)
                {
                    break;
                }
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
            if (disabled.Count == 0)
            {
                _consecutiveNoopPasses += 1;
            }
            else
            {
                _consecutiveNoopPasses = 0;
            }
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

            DisableKnownGuideComponents(node.gameObject, disabled);

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
            if (IsCoreXrRigObject(go))
            {
                return false;
            }

            if (name.StartsWith("BYES_", System.StringComparison.Ordinal))
            {
                return false;
            }

            var lowered = name.ToLowerInvariant();
            // Keep name rules strict to avoid disabling core XR rig objects.
            if (string.Equals(lowered, "goal manager", System.StringComparison.Ordinal)
                   || string.Equals(lowered, "hand menu setup mr template variant", System.StringComparison.Ordinal)
                   || string.Equals(lowered, "player settings", System.StringComparison.Ordinal)
                   || string.Equals(lowered, "coaching", System.StringComparison.Ordinal)
                   || string.Equals(lowered, "coaching ui", System.StringComparison.Ordinal)
                   || string.Equals(lowered, "relaunch coaching", System.StringComparison.Ordinal)
                   || string.Equals(lowered, "resetcoaching", System.StringComparison.Ordinal)
                   || string.Equals(lowered, "tutorial player", System.StringComparison.Ordinal))
            {
                return true;
            }

            return ContainsPlayerSettingsLabel(go);
        }

        private static void DisableKnownGuideComponents(GameObject go, List<string> disabled)
        {
            if (go == null)
            {
                return;
            }

            var components = go.GetComponents<Component>();
            for (var i = 0; i < components.Length; i += 1)
            {
                var component = components[i];
                if (component == null)
                {
                    continue;
                }

                var fullName = component.GetType().FullName ?? string.Empty;
                if (string.Equals(fullName, "UnityEngine.XR.Templates.MR.GoalManager", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.GazeTooltips", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.DebugInfoDisplayController", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.BooleanToggleVisualsController", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.OcclusionManager", System.StringComparison.Ordinal)
                    || string.Equals(fullName, "UnityEngine.XR.Templates.MR.SpawnedObjectsManager", System.StringComparison.Ordinal))
                {
                    if (component is Behaviour behaviour && behaviour.enabled)
                    {
                        behaviour.enabled = false;
                        disabled.Add(go.name + "::" + component.GetType().Name);
                    }
                }
            }
        }

        private static bool IsCoreXrRigObject(GameObject go)
        {
            var components = go.GetComponents<Component>();
            for (var i = 0; i < components.Length; i += 1)
            {
                var component = components[i];
                if (component == null)
                {
                    continue;
                }

                var fullName = component.GetType().FullName ?? string.Empty;
                if (fullName == "Unity.XR.CoreUtils.XROrigin"
                    || fullName == "UnityEngine.Camera"
                    || fullName == "UnityEngine.XR.Interaction.Toolkit.XRInteractionManager"
                    || fullName == "UnityEngine.XR.Interaction.Toolkit.UI.XRUIInputModule"
                    || fullName == "UnityEngine.XR.Interaction.Toolkit.Inputs.XRInputModalityManager"
                    || fullName.Contains("OpenXR", System.StringComparison.Ordinal))
                {
                    return true;
                }
            }

            return false;
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
