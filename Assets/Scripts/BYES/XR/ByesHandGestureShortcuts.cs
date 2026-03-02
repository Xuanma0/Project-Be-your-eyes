using System;
using System.Collections.Generic;
using BYES.Core;
using BYES.Quest;
using BeYourEyes.Unity.Interaction;
using UnityEngine;
using UnityEngine.XR.Hands;
using UnityEngine.XR.Interaction.Toolkit.Interactors;

namespace BYES.XR
{
    public sealed class ByesHandGestureShortcuts : MonoBehaviour
    {
        public event Action<string> OnShortcutTriggered;

        public enum ShortcutHand
        {
            RightOnly = 0,
            LeftOnly = 1,
            Both = 2,
        }

        public enum ConflictMode
        {
            Safe = 0,
            Advanced = 1,
        }

        [SerializeField] private bool enabledOnAndroidOnly = true;
        [SerializeField] private bool shortcutsEnabled = true;
        [SerializeField] private ShortcutHand shortcutHand = ShortcutHand.RightOnly;
        [SerializeField] private ConflictMode conflictMode = ConflictMode.Safe;
        [SerializeField] private float pinchEnterDistanceM = 0.022f;
        [SerializeField] private float pinchReleaseDistanceM = 0.04f;
        [SerializeField] private float triggerCooldownSec = 0.5f;
        [SerializeField] private float palmFacingCameraDotThreshold = 0.2f;
        [SerializeField] private int triggerHistoryCapacity = 5;

        private static readonly List<XRHandSubsystem> Subsystems = new List<XRHandSubsystem>();
        private static readonly List<string> TriggerHistory = new List<string>(8);

        private XRHandSubsystem _subsystem;
        private ByesQuest3ConnectionPanelMinimal _panel;
        private ScanController _scanController;
        private ByesHandMenuController _handMenu;
        private ByesSmokePanelGrabHandle _grabHandle;

        private bool _middlePinched;
        private bool _ringPinched;
        private bool _pinkyPinched;
        private float _lastTriggerTime = -10f;
        private bool _systemGestureActive;

        public bool ShortcutsEnabled => shortcutsEnabled;
        public ShortcutHand ActiveShortcutHand => shortcutHand;
        public ConflictMode ActiveConflictMode => conflictMode;

        private void Update()
        {
            if (!shortcutsEnabled)
            {
                return;
            }

            if (enabledOnAndroidOnly && Application.platform != RuntimePlatform.Android)
            {
                return;
            }

            ResolveRefs();
            if (!TryResolveSubsystem(out var subsystem))
            {
                return;
            }

            switch (shortcutHand)
            {
                case ShortcutHand.LeftOnly:
                    ProcessHand(subsystem.leftHand);
                    break;
                case ShortcutHand.Both:
                    ProcessHand(subsystem.rightHand);
                    ProcessHand(subsystem.leftHand);
                    break;
                default:
                    ProcessHand(subsystem.rightHand);
                    break;
            }
        }

        public void SetShortcutsEnabled(bool enabled)
        {
            shortcutsEnabled = enabled;
        }

        public void SetShortcutHand(ShortcutHand hand)
        {
            shortcutHand = hand;
        }

        public void SetConflictMode(ConflictMode mode)
        {
            conflictMode = mode;
        }

        public void SetSystemGestureActive(bool active)
        {
            _systemGestureActive = active;
        }

        public string GetRecentTriggersAsText()
        {
            return TriggerHistory.Count == 0 ? "-" : string.Join(" | ", TriggerHistory);
        }

        private void ProcessHand(XRHand hand)
        {
            if (!hand.isTracked)
            {
                _middlePinched = false;
                _ringPinched = false;
                _pinkyPinched = false;
                return;
            }

            if (conflictMode == ConflictMode.Safe && !IsSafeToTrigger(hand))
            {
                _middlePinched = false;
                _ringPinched = false;
                _pinkyPinched = false;
                return;
            }

            if (!TryGetTipDistance(hand, XRHandJointID.MiddleTip, out var middleDistance)
                || !TryGetTipDistance(hand, XRHandJointID.RingTip, out var ringDistance)
                || !TryGetTipDistance(hand, XRHandJointID.LittleTip, out var pinkyDistance))
            {
                return;
            }

            var middleTriggered = UpdatePinchState(middleDistance, ref _middlePinched);
            var ringTriggered = UpdatePinchState(ringDistance, ref _ringPinched);
            var pinkyTriggered = UpdatePinchState(pinkyDistance, ref _pinkyPinched);

            if (Time.unscaledTime - _lastTriggerTime < triggerCooldownSec)
            {
                return;
            }

            var triggerCount = (middleTriggered ? 1 : 0) + (ringTriggered ? 1 : 0) + (pinkyTriggered ? 1 : 0);
            if (triggerCount != 1)
            {
                return;
            }

            if (middleTriggered)
            {
                TriggerScanOnce();
                _lastTriggerTime = Time.unscaledTime;
                RecordTrigger("thumb+middle=scan");
                OnShortcutTriggered?.Invoke("scan");
                return;
            }

            if (ringTriggered)
            {
                TriggerToggleLive();
                _lastTriggerTime = Time.unscaledTime;
                RecordTrigger("thumb+ring=live");
                OnShortcutTriggered?.Invoke("live");
                return;
            }

            if (pinkyTriggered)
            {
                TriggerCycleMode();
                _lastTriggerTime = Time.unscaledTime;
                RecordTrigger("thumb+pinky=mode");
                OnShortcutTriggered?.Invoke("mode");
            }
        }

        private void ResolveRefs()
        {
            _panel ??= FindFirstObjectByType<ByesQuest3ConnectionPanelMinimal>();
            _scanController ??= FindFirstObjectByType<ScanController>();
            _handMenu ??= FindFirstObjectByType<ByesHandMenuController>();
            _grabHandle ??= FindFirstObjectByType<ByesSmokePanelGrabHandle>();
        }

        private bool TryResolveSubsystem(out XRHandSubsystem subsystem)
        {
            if (_subsystem != null && _subsystem.running)
            {
                subsystem = _subsystem;
                return true;
            }

            SubsystemManager.GetSubsystems(Subsystems);
            for (var i = 0; i < Subsystems.Count; i += 1)
            {
                var candidate = Subsystems[i];
                if (candidate == null || !candidate.running)
                {
                    continue;
                }

                _subsystem = candidate;
                subsystem = _subsystem;
                return true;
            }

            subsystem = null;
            return false;
        }

        private bool TryGetTipDistance(XRHand hand, XRHandJointID tipId, out float distance)
        {
            distance = 0f;
            var thumbTip = hand.GetJoint(XRHandJointID.ThumbTip);
            var fingerTip = hand.GetJoint(tipId);
            if (!thumbTip.TryGetPose(out var thumbPose) || !fingerTip.TryGetPose(out var fingerPose))
            {
                return false;
            }

            distance = Vector3.Distance(thumbPose.position, fingerPose.position);
            return !float.IsNaN(distance) && !float.IsInfinity(distance);
        }

        private bool UpdatePinchState(float distance, ref bool state)
        {
            if (!state && distance <= pinchEnterDistanceM)
            {
                state = true;
                return true;
            }

            if (state && distance >= pinchReleaseDistanceM)
            {
                state = false;
            }

            return false;
        }

        private void TriggerScanOnce()
        {
            if (_panel != null)
            {
                _panel.TriggerScanOnceFromUi();
                return;
            }

            _scanController?.ScanOnceFromUi();
        }

        private void TriggerToggleLive()
        {
            if (_panel != null)
            {
                _panel.TriggerToggleLiveFromUi();
                return;
            }

            _scanController?.ToggleLiveFromUi();
        }

        private void TriggerCycleMode()
        {
            if (_panel != null)
            {
                _panel.TriggerCycleMode();
                return;
            }

            var modeManager = ByesModeManager.Instance;
            if (modeManager == null)
            {
                return;
            }

            var current = modeManager.GetMode();
            var next = current switch
            {
                ByesMode.Walk => ByesMode.ReadText,
                ByesMode.ReadText => ByesMode.Inspect,
                _ => ByesMode.Walk,
            };
            modeManager.SetMode(next, "xr");
        }

        private bool IsSafeToTrigger(XRHand hand)
        {
            if (_systemGestureActive)
            {
                return false;
            }

            if (_handMenu != null && (_handMenu.IsMenuVisible() || _handMenu.IsSystemGestureActive()))
            {
                return false;
            }

            if (_grabHandle != null && _grabHandle.IsGrabInProgress)
            {
                return false;
            }

            var rayInteractors = FindObjectsByType<XRRayInteractor>(FindObjectsInactive.Include, FindObjectsSortMode.None);
            for (var i = 0; i < rayInteractors.Length; i += 1)
            {
                var interactor = rayInteractors[i];
                if (interactor == null || !interactor.enabled)
                {
                    continue;
                }

                if (interactor.hasHover || interactor.hasSelection)
                {
                    return false;
                }
            }

            var palmJoint = hand.GetJoint(XRHandJointID.Palm);
            if (!palmJoint.TryGetPose(out var palmPose))
            {
                return false;
            }

            var camera = Camera.main;
            if (camera == null)
            {
                return false;
            }

            var toCamera = (camera.transform.position - palmPose.position).normalized;
            var facingDot = Vector3.Dot(palmPose.forward, toCamera);
            return facingDot >= palmFacingCameraDotThreshold;
        }

        private void RecordTrigger(string label)
        {
            var entry = $"{DateTimeOffset.UtcNow:HH:mm:ss}-{label}";
            TriggerHistory.Add(entry);
            while (TriggerHistory.Count > Mathf.Max(1, triggerHistoryCapacity))
            {
                TriggerHistory.RemoveAt(0);
            }
        }
    }
}
