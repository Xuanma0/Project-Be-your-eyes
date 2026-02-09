using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Presenters.Audio;

namespace BeYourEyes.Unity.Interaction
{
    public enum LocalIntentKind
    {
        None,
        ScanText,
        Ask,
    }

    public sealed class LocalIntentController : MonoBehaviour
    {
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;
        [SerializeField] private SpeechOrchestrator speechOrchestrator;

        [Header("Thresholds")]
        [SerializeField] private int doubleTapWindowMs = 350;
        [SerializeField] private int longPressMs = 550;
        [SerializeField] private int triggerCooldownMs = 800;
        [SerializeField] private int askAutoReturnMs = 1200;

        [Header("Feedback")]
        [SerializeField] private bool enableHaptics = true;
        [SerializeField] private bool enableBlockedBeep = true;
        [SerializeField] private float hapticAmplitude = 0.35f;
        [SerializeField] private float hapticDurationSec = 0.03f;
        [SerializeField] private float blockedBeepFrequencyHz = 640f;
        [SerializeField] private float blockedBeepDurationSec = 0.08f;
        [SerializeField] private float blockedBeepVolume = 0.18f;

        private LocalIntentKind currentIntent = LocalIntentKind.None;
        private long lastIntentChangeMs = -1;
        private string intentHint = string.Empty;
        private long intentHintUntilMs = -1;
        private string lastBlockedReason = string.Empty;
        private long lastTriggerAtMs = long.MinValue;
        private long askTriggeredAtMs = -1;

        private long scanEnterCount;
        private long scanExitCount;
        private long askTriggerCount;
        private long blockedCount;

        private long lastQTapMs = long.MinValue;
        private bool prevXrPrimaryPressed;
        private bool prevXrSecondaryPressed;
        private long xrPrimaryDownAtMs = -1;
        private bool xrPrimaryLongHoldActive;
        private float nextXrDeviceLookupAt;
        private InputDevice rightHandDevice;

        private AudioSource beepSource;
        private AudioClip blockedBeepClip;

        public LocalIntentKind CurrentIntent => currentIntent;
        public long ScanEnterCount => scanEnterCount;
        public long ScanExitCount => scanExitCount;
        public long AskTriggerCount => askTriggerCount;
        public long BlockedCount => blockedCount;
        public long LastIntentChangeMs => lastIntentChangeMs;
        public string LastBlockedReason => string.IsNullOrWhiteSpace(lastBlockedReason) ? "-" : lastBlockedReason;
        public string HintText => string.IsNullOrWhiteSpace(intentHint) ? "-" : intentHint;

        private void OnEnable()
        {
            EnsureDependencies();
            EnsureAudio();
            TransitionIntent(LocalIntentKind.None, "init");
        }

        private void Update()
        {
            EnsureDependencies();
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            HandleKeyboard(nowMs);
            HandleXr(nowMs);
            HandleAskAutoReturn(nowMs);
            ExpireHint(nowMs);
        }

        private void EnsureDependencies()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
            }
            if (speechOrchestrator == null)
            {
                speechOrchestrator = FindFirstObjectByType<SpeechOrchestrator>();
            }
        }

        private void HandleKeyboard(long nowMs)
        {
            var tHeld = false;
            var qDown = false;
            var escDown = false;

#if ENABLE_INPUT_SYSTEM
            var keyboard = UnityEngine.InputSystem.Keyboard.current;
            if (keyboard != null)
            {
                tHeld = keyboard.tKey.isPressed;
                qDown = keyboard.qKey.wasPressedThisFrame;
                escDown = keyboard.escapeKey.wasPressedThisFrame;
            }
#elif ENABLE_LEGACY_INPUT_MANAGER
            tHeld = Input.GetKey(KeyCode.T);
            qDown = Input.GetKeyDown(KeyCode.Q);
            escDown = Input.GetKeyDown(KeyCode.Escape);
#endif

            if (escDown)
            {
                ForceIntentNone("keyboard_escape");
                return;
            }

            if (qDown)
            {
                if (nowMs - lastQTapMs <= Math.Max(100, doubleTapWindowMs))
                {
                    lastQTapMs = long.MinValue;
                    TryTriggerAsk(nowMs, "keyboard_q_double_tap");
                }
                else
                {
                    lastQTapMs = nowMs;
                }
            }

            ApplyScanHoldState(tHeld, nowMs, "keyboard_t_hold");
        }

        private void HandleXr(long nowMs)
        {
            if (!rightHandDevice.isValid && Time.unscaledTime >= nextXrDeviceLookupAt)
            {
                nextXrDeviceLookupAt = Time.unscaledTime + 1f;
                rightHandDevice = InputDevices.GetDeviceAtXRNode(XRNode.RightHand);
                if (!rightHandDevice.isValid)
                {
                    var devices = new List<InputDevice>();
                    InputDevices.GetDevicesWithCharacteristics(
                        InputDeviceCharacteristics.Controller | InputDeviceCharacteristics.Right,
                        devices
                    );
                    if (devices.Count > 0)
                    {
                        rightHandDevice = devices[0];
                    }
                }
            }

            if (!rightHandDevice.isValid)
            {
                prevXrPrimaryPressed = false;
                prevXrSecondaryPressed = false;
                xrPrimaryLongHoldActive = false;
                xrPrimaryDownAtMs = -1;
                return;
            }

            var hasPrimary = rightHandDevice.TryGetFeatureValue(CommonUsages.primaryButton, out var primaryPressed);
            if (!hasPrimary)
            {
                primaryPressed = false;
            }
            var hasSecondary = rightHandDevice.TryGetFeatureValue(CommonUsages.secondaryButton, out var secondaryPressed);
            if (!hasSecondary)
            {
                secondaryPressed = false;
            }

            var primaryDownEdge = primaryPressed && !prevXrPrimaryPressed;
            var primaryUpEdge = !primaryPressed && prevXrPrimaryPressed;
            if (primaryDownEdge)
            {
                xrPrimaryDownAtMs = nowMs;
                xrPrimaryLongHoldActive = false;
            }
            if (primaryPressed && xrPrimaryDownAtMs > 0 && !xrPrimaryLongHoldActive &&
                nowMs - xrPrimaryDownAtMs >= Math.Max(100, longPressMs))
            {
                xrPrimaryLongHoldActive = true;
            }
            if (primaryUpEdge)
            {
                xrPrimaryDownAtMs = -1;
                xrPrimaryLongHoldActive = false;
            }
            prevXrPrimaryPressed = primaryPressed;

            ApplyScanHoldState(xrPrimaryLongHoldActive, nowMs, "xr_primary_long_press");

            var secondaryDownEdge = secondaryPressed && !prevXrSecondaryPressed;
            if (secondaryDownEdge)
            {
                if (nowMs - lastQTapMs <= Math.Max(100, doubleTapWindowMs))
                {
                    lastQTapMs = long.MinValue;
                    TryTriggerAsk(nowMs, "xr_secondary_double_tap");
                }
                else
                {
                    lastQTapMs = nowMs;
                }
            }
            prevXrSecondaryPressed = secondaryPressed;
        }

        private void ApplyScanHoldState(bool shouldHold, long nowMs, string source)
        {
            if (currentIntent == LocalIntentKind.Ask)
            {
                return;
            }

            if (shouldHold)
            {
                if (currentIntent != LocalIntentKind.ScanText)
                {
                    TryEnterScanText(nowMs, source);
                }
            }
            else if (currentIntent == LocalIntentKind.ScanText)
            {
                ExitScanText(nowMs, $"{source}_release");
            }
        }

        private void TryEnterScanText(long nowMs, string source)
        {
            if (!CanTrigger(nowMs, isAsk: false, out var blockedReason))
            {
                BlockIntent(blockedReason, nowMs);
                return;
            }

            lastTriggerAtMs = nowMs;
            TransitionIntent(LocalIntentKind.ScanText, source);
            scanEnterCount++;
            SetHint("SCAN TEXT", nowMs, 1000);
            TryPulseHaptics();
            gatewayClient?.SetIntentScanText(true, (ok, _) =>
            {
                if (!ok)
                {
                    BlockIntent("intent_post_failed", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    TransitionIntent(LocalIntentKind.None, "scan_post_failed");
                }
            });
        }

        private void ExitScanText(long nowMs, string source)
        {
            lastTriggerAtMs = nowMs;
            TransitionIntent(LocalIntentKind.None, source);
            scanExitCount++;
            SetHint(string.Empty, nowMs, 0);
            TryPulseHaptics();
            gatewayClient?.SetIntentScanText(false, null);
        }

        private void TryTriggerAsk(long nowMs, string source)
        {
            if (!CanTrigger(nowMs, isAsk: true, out var blockedReason))
            {
                BlockIntent(blockedReason, nowMs);
                return;
            }

            lastTriggerAtMs = nowMs;
            askTriggeredAtMs = nowMs;
            askTriggerCount++;
            TransitionIntent(LocalIntentKind.Ask, source);
            SetHint("ASK", nowMs, askAutoReturnMs);
            TryPulseHaptics();
            speechOrchestrator?.SpeakLocalHint("Asking", flush: false);

            var question = gatewayClient != null ? gatewayClient.CurrentQuestion : "What is in front of me?";
            gatewayClient?.TriggerAskOnce(question, (ok, _) =>
            {
                if (!ok)
                {
                    BlockIntent("intent_post_failed", DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    TransitionIntent(LocalIntentKind.None, "ask_post_failed");
                }
            });
        }

        private void HandleAskAutoReturn(long nowMs)
        {
            if (currentIntent != LocalIntentKind.Ask || askTriggeredAtMs <= 0)
            {
                return;
            }

            if (nowMs - askTriggeredAtMs < Math.Max(100, askAutoReturnMs))
            {
                return;
            }

            ForceIntentNone("ask_auto_return");
        }

        private void ForceIntentNone(string reason)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (currentIntent == LocalIntentKind.ScanText)
            {
                scanExitCount++;
            }

            askTriggeredAtMs = -1;
            TransitionIntent(LocalIntentKind.None, reason);
            SetHint(string.Empty, nowMs, 0);
            gatewayClient?.SetIntentScanText(false, null);
        }

        private bool CanTrigger(long nowMs, bool isAsk, out string blockedReason)
        {
            blockedReason = string.Empty;
            if (gatewayClient == null)
            {
                blockedReason = "gateway_missing";
                return false;
            }

            if (localSafetyFallback != null && !localSafetyFallback.IsOk)
            {
                blockedReason = $"fallback_{localSafetyFallback.CurrentState}";
                return false;
            }

            var status = (gatewayClient.LastHealthStatus ?? string.Empty).Trim().ToUpperInvariant();
            if (status == "SAFE_MODE")
            {
                blockedReason = "safe_mode";
                return false;
            }

            var cooldown = Math.Max(100, triggerCooldownMs);
            if (isAsk && (status == "THROTTLED" || status == "DEGRADED"))
            {
                cooldown *= 2;
            }

            if (nowMs - lastTriggerAtMs < cooldown)
            {
                blockedReason = "trigger_cooldown";
                return false;
            }

            return true;
        }

        private void BlockIntent(string reason, long nowMs)
        {
            blockedCount++;
            lastBlockedReason = string.IsNullOrWhiteSpace(reason) ? "blocked" : reason;
            SetHint("INTENT BLOCKED", nowMs, 1200);
            if (enableBlockedBeep)
            {
                PlayBlockedBeep();
            }
        }

        private void TransitionIntent(LocalIntentKind next, string source)
        {
            if (currentIntent == next)
            {
                return;
            }

            currentIntent = next;
            lastIntentChangeMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (next != LocalIntentKind.Ask)
            {
                askTriggeredAtMs = -1;
            }

            if (source == null)
            {
                return;
            }
        }

        private void SetHint(string text, long nowMs, int durationMs)
        {
            intentHint = text ?? string.Empty;
            if (string.IsNullOrWhiteSpace(intentHint) || durationMs <= 0)
            {
                intentHintUntilMs = -1;
                return;
            }

            intentHintUntilMs = nowMs + durationMs;
        }

        private void ExpireHint(long nowMs)
        {
            if (intentHintUntilMs <= 0 || nowMs <= intentHintUntilMs)
            {
                return;
            }

            intentHint = string.Empty;
            intentHintUntilMs = -1;
        }

        private void EnsureAudio()
        {
            if (beepSource == null)
            {
                beepSource = GetComponent<AudioSource>();
                if (beepSource == null)
                {
                    beepSource = gameObject.AddComponent<AudioSource>();
                }
                beepSource.playOnAwake = false;
                beepSource.loop = false;
            }

            if (blockedBeepClip != null)
            {
                return;
            }

            var sampleRate = 44100;
            var sampleCount = Mathf.Clamp(Mathf.CeilToInt(sampleRate * Mathf.Clamp(blockedBeepDurationSec, 0.02f, 0.4f)), 1, sampleRate);
            blockedBeepClip = AudioClip.Create("ByesIntentBlockedBeep", sampleCount, 1, sampleRate, false);
            var data = new float[sampleCount];
            var volume = Mathf.Clamp01(blockedBeepVolume);
            for (var i = 0; i < sampleCount; i++)
            {
                var t = i / (float)sampleRate;
                data[i] = Mathf.Sin(2f * Mathf.PI * Mathf.Max(100f, blockedBeepFrequencyHz) * t) * volume;
            }
            blockedBeepClip.SetData(data, 0);
        }

        private void PlayBlockedBeep()
        {
            EnsureAudio();
            if (beepSource == null || blockedBeepClip == null)
            {
                return;
            }

            beepSource.clip = blockedBeepClip;
            beepSource.Play();
        }

        private void TryPulseHaptics()
        {
            if (!enableHaptics)
            {
                return;
            }

            try
            {
                var devices = new List<InputDevice>();
                InputDevices.GetDevices(devices);
                foreach (var device in devices)
                {
                    if (!device.isValid)
                    {
                        continue;
                    }

                    if (!device.TryGetHapticCapabilities(out var caps))
                    {
                        continue;
                    }

                    if (!caps.supportsImpulse)
                    {
                        continue;
                    }

                    device.SendHapticImpulse(0u, Mathf.Clamp01(hapticAmplitude), Mathf.Clamp(hapticDurationSec, 0.01f, 0.3f));
                }
            }
            catch
            {
            }
        }
    }
}
