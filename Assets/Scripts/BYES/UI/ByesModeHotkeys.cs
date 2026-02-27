using BYES.Core;
using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace BYES.UI
{
    public sealed class ByesModeHotkeys : MonoBehaviour
    {
        private void Update()
        {
            if (WasPressedWalk())
            {
                SwitchMode(ByesMode.Walk);
            }
            else if (WasPressedRead())
            {
                SwitchMode(ByesMode.ReadText);
            }
            else if (WasPressedInspect())
            {
                SwitchMode(ByesMode.Inspect);
            }
        }

        private static bool WasPressedWalk()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb != null && (kb.digit1Key.wasPressedThisFrame || kb.f1Key.wasPressedThisFrame))
            {
                return true;
            }
#endif
#if ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetKeyDown(KeyCode.Alpha1) || Input.GetKeyDown(KeyCode.F1);
#else
            return false;
#endif
        }

        private static bool WasPressedRead()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb != null && (kb.digit2Key.wasPressedThisFrame || kb.f2Key.wasPressedThisFrame))
            {
                return true;
            }
#endif
#if ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetKeyDown(KeyCode.Alpha2) || Input.GetKeyDown(KeyCode.F2);
#else
            return false;
#endif
        }

        private static bool WasPressedInspect()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb != null && (kb.digit3Key.wasPressedThisFrame || kb.f3Key.wasPressedThisFrame))
            {
                return true;
            }
#endif
#if ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetKeyDown(KeyCode.Alpha3) || Input.GetKeyDown(KeyCode.F3);
#else
            return false;
#endif
        }

        private static void SwitchMode(ByesMode mode)
        {
            ByesModeManager.Instance.SetMode(mode, "hotkey");
            Debug.Log("[ByesModeHotkeys] mode=" + ByesModeManager.ToApiMode(mode));
        }
    }
}
