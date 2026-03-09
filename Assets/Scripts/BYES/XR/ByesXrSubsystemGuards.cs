using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace BYES.XR
{
    [DefaultExecutionOrder(-1000)]
    public sealed class ByesXrSubsystemGuards : MonoBehaviour
    {
        private static bool sLogged;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AutoInstallOnQuestSmokeScene()
        {
            var scene = SceneManager.GetActiveScene();
            if (!string.Equals(scene.name, "Quest3SmokeScene", StringComparison.Ordinal))
            {
                return;
            }

            if (FindFirstObjectByType<ByesXrSubsystemGuards>() != null)
            {
                return;
            }

            var host = new GameObject("BYES_XrSubsystemGuards");
            host.AddComponent<ByesXrSubsystemGuards>();
        }

        private IEnumerator Start()
        {
            yield return null;
            DisableHandTrackingDependentBehaviours();
        }

        private static void DisableHandTrackingDependentBehaviours()
        {
            if (HasRunningHandSubsystem())
            {
                return;
            }

            var modalityType = Type.GetType(
                "UnityEngine.XR.Interaction.Toolkit.Inputs.XRInputModalityManager, Unity.XR.Interaction.Toolkit",
                throwOnError: false
            );
            if (modalityType == null)
            {
                return;
            }

            var objects = Resources.FindObjectsOfTypeAll(modalityType);
            var disabledCount = 0;
            for (var i = 0; i < objects.Length; i += 1)
            {
                if (objects[i] is not Behaviour behaviour)
                {
                    continue;
                }

                if (!behaviour.gameObject.scene.IsValid() || !behaviour.enabled)
                {
                    continue;
                }

                behaviour.enabled = false;
                disabledCount += 1;
            }

            if (disabledCount <= 0 || sLogged)
            {
                return;
            }

            sLogged = true;
            Debug.Log("[ByesXrSubsystemGuards] Disabled XRInputModalityManager because XRHandSubsystem is missing or not running.");
        }

        private static bool HasRunningHandSubsystem()
        {
            var handSubsystemType = Type.GetType("UnityEngine.XR.Hands.XRHandSubsystem, Unity.XR.Hands", throwOnError: false);
            if (handSubsystemType == null)
            {
                return false;
            }

            var listType = typeof(List<>).MakeGenericType(handSubsystemType);
            var subsystemList = Activator.CreateInstance(listType);
            var getSubsystemsGeneric = ResolveGetSubsystemsGenericMethod();
            if (subsystemList == null || getSubsystemsGeneric == null)
            {
                return false;
            }

            var getSubsystemsTyped = getSubsystemsGeneric.MakeGenericMethod(handSubsystemType);
            getSubsystemsTyped.Invoke(null, new[] { subsystemList });

            var runningProperty = handSubsystemType.GetProperty("running", BindingFlags.Instance | BindingFlags.Public);
            if (runningProperty == null || subsystemList is not IEnumerable entries)
            {
                return false;
            }

            foreach (var entry in entries)
            {
                if (entry == null)
                {
                    continue;
                }

                if (runningProperty.GetValue(entry) is bool running && running)
                {
                    return true;
                }
            }

            return false;
        }

        private static MethodInfo ResolveGetSubsystemsGenericMethod()
        {
            var methods = typeof(SubsystemManager).GetMethods(BindingFlags.Public | BindingFlags.Static);
            for (var i = 0; i < methods.Length; i += 1)
            {
                var candidate = methods[i];
                if (!string.Equals(candidate.Name, "GetSubsystems", StringComparison.Ordinal))
                {
                    continue;
                }

                if (!candidate.IsGenericMethodDefinition)
                {
                    continue;
                }

                var parameters = candidate.GetParameters();
                if (parameters.Length != 1)
                {
                    continue;
                }

                var parameterType = parameters[0].ParameterType;
                if (!parameterType.IsGenericType)
                {
                    continue;
                }

                if (parameterType.GetGenericTypeDefinition() == typeof(List<>))
                {
                    return candidate;
                }
            }

            return null;
        }
    }
}
