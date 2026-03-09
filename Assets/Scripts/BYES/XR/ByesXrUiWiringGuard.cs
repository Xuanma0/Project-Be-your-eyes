using System;
using System.Reflection;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.XR.Interaction.Toolkit.Interactors;
using UnityEngine.XR.Interaction.Toolkit.UI;

namespace BYES.XR
{
    public sealed class ByesXrUiWiringGuard : MonoBehaviour
    {
        private void Start()
        {
            ApplyWiringFixes();
        }

        private static void ApplyWiringFixes()
        {
            var mainCamera = Camera.main;
            var eventSystems = FindObjectsByType<EventSystem>(FindObjectsInactive.Include, FindObjectsSortMode.None);

            var createdXrModules = 0;
            var disabledStandaloneModules = 0;
            var disabledInputSystemModules = 0;
            var updatedUiCameraBindings = 0;

            for (var i = 0; i < eventSystems.Length; i += 1)
            {
                var eventSystem = eventSystems[i];
                if (eventSystem == null)
                {
                    continue;
                }

                var eventSystemGo = eventSystem.gameObject;

                var xrUiModule = eventSystemGo.GetComponent<XRUIInputModule>();
                if (xrUiModule == null)
                {
                    xrUiModule = eventSystemGo.AddComponent<XRUIInputModule>();
                    createdXrModules += 1;
                }

                if (mainCamera != null && TrySetUiCamera(xrUiModule, mainCamera))
                {
                    updatedUiCameraBindings += 1;
                }

                var standalone = eventSystemGo.GetComponent<StandaloneInputModule>();
                if (standalone != null && standalone.enabled)
                {
                    standalone.enabled = false;
                    disabledStandaloneModules += 1;
                }

                var inputSystemUiModuleType = Type.GetType("UnityEngine.InputSystem.UI.InputSystemUIInputModule, Unity.InputSystem");
                if (inputSystemUiModuleType != null)
                {
                    var inputSystemModule = eventSystemGo.GetComponent(inputSystemUiModuleType) as Behaviour;
                    if (inputSystemModule != null && inputSystemModule.enabled)
                    {
                        inputSystemModule.enabled = false;
                        disabledInputSystemModules += 1;
                    }
                }
            }

            var rayInteractors = FindObjectsByType<XRRayInteractor>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            var enabledUiInteractionCount = 0;
            for (var i = 0; i < rayInteractors.Length; i += 1)
            {
                if (TryEnableUiInteraction(rayInteractors[i]))
                {
                    enabledUiInteractionCount += 1;
                }
            }

            Debug.Log(
                $"[ByesXrUiWiringGuard] eventSystems={eventSystems.Length}, xrUiModulesCreated={createdXrModules}, " +
                $"disabledStandalone={disabledStandaloneModules}, disabledInputSystemUi={disabledInputSystemModules}, " +
                $"uiCameraBound={updatedUiCameraBindings}, xrRayInteractors={rayInteractors.Length}, uiInteractionEnabled={enabledUiInteractionCount}"
            );
        }

        private static bool TrySetUiCamera(XRUIInputModule module, Camera camera)
        {
            if (module == null || camera == null)
            {
                return false;
            }

            var moduleType = module.GetType();
            var uiCameraProperty = moduleType.GetProperty("uiCamera", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (uiCameraProperty != null && uiCameraProperty.PropertyType == typeof(Camera) && uiCameraProperty.CanWrite)
            {
                uiCameraProperty.SetValue(module, camera);
                return true;
            }

            var uiCameraField = moduleType.GetField("m_UICamera", BindingFlags.Instance | BindingFlags.NonPublic);
            if (uiCameraField != null && uiCameraField.FieldType == typeof(Camera))
            {
                uiCameraField.SetValue(module, camera);
                return true;
            }

            return false;
        }

        private static bool TryEnableUiInteraction(XRRayInteractor rayInteractor)
        {
            if (rayInteractor == null)
            {
                return false;
            }

            var type = rayInteractor.GetType();

            var property = type.GetProperty("enableUIInteraction", BindingFlags.Instance | BindingFlags.Public);
            if (property != null && property.PropertyType == typeof(bool) && property.CanWrite)
            {
                property.SetValue(rayInteractor, true);
                return true;
            }

            property = type.GetProperty("enableInteractionWithUI", BindingFlags.Instance | BindingFlags.Public);
            if (property != null && property.PropertyType == typeof(bool) && property.CanWrite)
            {
                property.SetValue(rayInteractor, true);
                return true;
            }

            var field = type.GetField("m_EnableUIInteraction", BindingFlags.Instance | BindingFlags.NonPublic);
            if (field != null && field.FieldType == typeof(bool))
            {
                field.SetValue(rayInteractor, true);
                return true;
            }

            field = type.GetField("m_EnableInteractionWithUI", BindingFlags.Instance | BindingFlags.NonPublic);
            if (field != null && field.FieldType == typeof(bool))
            {
                field.SetValue(rayInteractor, true);
                return true;
            }

            return false;
        }
    }
}
