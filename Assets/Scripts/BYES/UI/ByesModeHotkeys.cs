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
                SwitchMode(ByesMode.Walk);
            }
            else if (Input.GetKeyDown(KeyCode.Alpha2) || Input.GetKeyDown(KeyCode.F2))
            {
                SwitchMode(ByesMode.ReadText);
            }
            else if (Input.GetKeyDown(KeyCode.Alpha3) || Input.GetKeyDown(KeyCode.F3))
            {
                SwitchMode(ByesMode.Inspect);
            }
        }

        private static void SwitchMode(ByesMode mode)
        {
            ByesModeManager.Instance.SetMode(mode, "hotkey");
            Debug.Log("[ByesModeHotkeys] mode=" + ByesModeManager.ToApiMode(mode));
        }
    }
}
