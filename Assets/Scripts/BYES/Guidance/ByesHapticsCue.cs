using BYES.Telemetry;
using UnityEngine;

namespace BYES.Guidance
{
    public sealed class ByesHapticsCue : MonoBehaviour
    {
        [SerializeField] private float cooldownSec = 0.4f;
        [SerializeField] private float baseAmplitude = 0.45f;
        [SerializeField] private float durationSec = 0.07f;

        private float _lastPulseAt;

        public void Pulse(GuidanceOutput output)
        {
            if (Time.unscaledTime - _lastPulseAt < Mathf.Max(0.05f, cooldownSec))
            {
                return;
            }

            var haptics = ByesHaptics.Instance;
            if (haptics == null)
            {
                return;
            }

            var amp = Mathf.Clamp01(baseAmplitude * Mathf.Lerp(0.6f, 1f, output.Strength));
            var channel = output.Direction switch
            {
                GuidanceDirection.Left => HapticChannel.Left,
                GuidanceDirection.Right => HapticChannel.Right,
                GuidanceDirection.Stop => HapticChannel.Both,
                _ => HapticChannel.Both,
            };
            if (haptics.TrySendPulse(channel, amp, Mathf.Max(0.03f, durationSec), "guidance", output.Direction.ToString()))
            {
                _lastPulseAt = Time.unscaledTime;
            }
        }
    }
}
