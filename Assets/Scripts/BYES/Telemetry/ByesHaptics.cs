using System;
using System.Collections.Generic;
using BYES.Core;
using UnityEngine;
using UnityEngine.XR;

namespace BYES.Telemetry
{
    public enum HapticChannel
    {
        Left = 0,
        Right = 1,
        Both = 2,
    }

    public sealed class ByesHaptics : MonoBehaviour
    {
        private static ByesHaptics _instance;
        private static readonly List<InputDevice> _deviceBuffer = new List<InputDevice>(8);

        private readonly HashSet<string> _sentPulseKeys = new HashSet<string>();

        private InputDevice _leftDevice;
        private InputDevice _rightDevice;
        private float _lastRefreshRealtimeSec;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            _ = EnsureExists();
        }

        public static ByesHaptics Instance => EnsureExists();

        public static ByesHaptics EnsureExists()
        {
            if (_instance != null)
            {
                return _instance;
            }

            var existing = FindFirstObjectByType<ByesHaptics>();
            if (existing != null)
            {
                _instance = existing;
                DontDestroyOnLoad(_instance.gameObject);
                return _instance;
            }

            var root = new GameObject("BYES_Haptics");
            DontDestroyOnLoad(root);
            _instance = root.AddComponent<ByesHaptics>();
            return _instance;
        }

        private void Awake()
        {
            if (_instance != null && _instance != this)
            {
                Destroy(gameObject);
                return;
            }

            _instance = this;
            DontDestroyOnLoad(gameObject);
            RefreshDevices(force: true);
        }

        public bool TrySendPulse(HapticChannel channel, float amplitude, float durationSec)
        {
            return TrySendPulse(channel, amplitude, durationSec, actionId: string.Empty, confirmId: string.Empty);
        }

        public bool TrySendPulse(HapticChannel channel, float amplitude, float durationSec, string actionId, string confirmId)
        {
            var normalizedAmplitude = Mathf.Clamp01(amplitude);
            var normalizedDuration = Mathf.Max(0f, durationSec);
            var dedupeKey = BuildDedupeKey(channel, normalizedAmplitude, normalizedDuration, actionId, confirmId);
            if (_sentPulseKeys.Contains(dedupeKey))
            {
                return false;
            }

            RefreshDevices(force: false);

            var sent = false;
            if (channel == HapticChannel.Left || channel == HapticChannel.Both)
            {
                sent |= TrySendDeviceImpulse(_leftDevice, normalizedAmplitude, normalizedDuration, "left");
            }
            if (channel == HapticChannel.Right || channel == HapticChannel.Both)
            {
                sent |= TrySendDeviceImpulse(_rightDevice, normalizedAmplitude, normalizedDuration, "right");
            }

            if (!sent)
            {
                return false;
            }

            _sentPulseKeys.Add(dedupeKey);
            if (_sentPulseKeys.Count > 4096)
            {
                _sentPulseKeys.Clear();
            }
            return true;
        }

        private void RefreshDevices(bool force)
        {
            var now = Time.realtimeSinceStartup;
            if (!force && now - _lastRefreshRealtimeSec < 1.0f && _leftDevice.isValid && _rightDevice.isValid)
            {
                return;
            }

            _leftDevice = FindDevice(InputDeviceCharacteristics.HeldInHand | InputDeviceCharacteristics.Controller | InputDeviceCharacteristics.Left);
            _rightDevice = FindDevice(InputDeviceCharacteristics.HeldInHand | InputDeviceCharacteristics.Controller | InputDeviceCharacteristics.Right);
            _lastRefreshRealtimeSec = now;
        }

        private static InputDevice FindDevice(InputDeviceCharacteristics characteristics)
        {
            _deviceBuffer.Clear();
            InputDevices.GetDevicesWithCharacteristics(characteristics, _deviceBuffer);
            for (var i = 0; i < _deviceBuffer.Count; i += 1)
            {
                var device = _deviceBuffer[i];
                if (device.isValid)
                {
                    return device;
                }
            }
            return default;
        }

        private static bool TrySendDeviceImpulse(InputDevice device, float amplitude, float durationSec, string side)
        {
            if (!device.isValid)
            {
                return false;
            }

            if (!device.TryGetHapticCapabilities(out var capabilities) || !capabilities.supportsImpulse)
            {
                if (Debug.isDebugBuild)
                {
                    Debug.Log("[ByesHaptics] Haptic impulse unsupported on " + side + " controller.");
                }
                return false;
            }

            try
            {
                var ok = device.SendHapticImpulse(0u, amplitude, durationSec);
                if (!ok && Debug.isDebugBuild)
                {
                    Debug.Log("[ByesHaptics] SendHapticImpulse returned false on " + side + " controller.");
                }
                return ok;
            }
            catch (Exception ex)
            {
                if (Debug.isDebugBuild)
                {
                    Debug.Log("[ByesHaptics] SendHapticImpulse failed on " + side + ": " + ex.Message);
                }
                return false;
            }
        }

        private static string BuildDedupeKey(
            HapticChannel channel,
            float amplitude,
            float durationSec,
            string actionId,
            string confirmId
        )
        {
            var state = ByesSystemState.Instance;
            var runId = state != null ? state.RunId : "unknown-run";
            var frameSeq = state != null ? state.FrameSeq : 1;
            var normalizedRunId = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim();
            var normalizedActionId = string.IsNullOrWhiteSpace(actionId) ? string.Empty : actionId.Trim();
            var normalizedConfirmId = string.IsNullOrWhiteSpace(confirmId) ? string.Empty : confirmId.Trim();
            return normalizedRunId
                   + "|"
                   + Mathf.Max(1, frameSeq)
                   + "|"
                   + channel
                   + "|"
                   + normalizedActionId
                   + "|"
                   + normalizedConfirmId
                   + "|"
                   + amplitude.ToString("0.###")
                   + "|"
                   + durationSec.ToString("0.###");
        }
    }
}
