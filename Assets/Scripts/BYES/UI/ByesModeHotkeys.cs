using BYES.Core;
using UnityEngine;

namespace BYES.UI
{
    public sealed class ByesModeHotkeys : MonoBehaviour
    {
        private void Update()
        {
            if (Input.GetKeyDown(KeyCode.Alpha1) || Input.GetKeyDown(KeyCode.F1))
            {
                SwitchMode(ByesMode.Explore);
            }
            else if (Input.GetKeyDown(KeyCode.Alpha2) || Input.GetKeyDown(KeyCode.F2))
            {
                SwitchMode(ByesMode.Navigate);
            }
            else if (Input.GetKeyDown(KeyCode.Alpha3) || Input.GetKeyDown(KeyCode.F3))
            {
                SwitchMode(ByesMode.ReadText);
            }
            else if (Input.GetKeyDown(KeyCode.Alpha4) || Input.GetKeyDown(KeyCode.F4))
            {
                SwitchMode(ByesMode.Debug);
            }
        }

        private static void SwitchMode(ByesMode mode)
        {
            var state = ByesSystemState.Instance;
            if (state == null)
            {
                return;
            }
            state.SetMode(mode);
            Debug.Log("[ByesModeHotkeys] mode=" + mode);
        }
    }
}
