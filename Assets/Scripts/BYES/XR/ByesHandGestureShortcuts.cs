using System;
using System.Collections.Generic;
using BYES.Core;
using BYES.Quest;
using BeYourEyes.Unity.Interaction;
using UnityEngine;
using UnityEngine.XR.Hands;

namespace BYES.XR
{
    public sealed class ByesHandGestureShortcuts : MonoBehaviour
    {
        [SerializeField] private bool enabledOnAndroidOnly = true;
        [SerializeField] private float pinchEnterDistanceM = 0.025f;
        [SerializeField] private float pinchReleaseDistanceM = 0.04f;
        [SerializeField] private float triggerCooldownSec = 0.5f;
        [SerializeField] private bool requireOnlyOnePinchAtATime = true;

        private static readonly List<XRHandSubsystem> Subsystems = new List<XRHandSubsystem>();

        private XRHandSubsystem _subsystem;
        private ByesQuest3ConnectionPanelMinimal _panel;
        private ScanController _scanController;

        private bool _indexPinched;
        private bool _middlePinched;
        private bool _ringPinched;
        private float _lastTriggerTime = -10f;

        private void Update()
        {
            if (enabledOnAndroidOnly && Application.platform != RuntimePlatform.Android)
            {
                return;
            }

            ResolveRefs();
            if (!TryResolveSubsystem(out var subsystem))
            {
                return;
            }

            var hand = subsystem.rightHand;
            if (!hand.isTracked)
            {
                _indexPinched = false;
                _middlePinched = false;
                _ringPinched = false;
                return;
            }

            if (!TryGetTipDistance(hand, XRHandJointID.IndexTip, out var indexDistance)
                || !TryGetTipDistance(hand, XRHandJointID.MiddleTip, out var middleDistance)
                || !TryGetTipDistance(hand, XRHandJointID.RingTip, out var ringDistance))
            {
                return;
            }

            var indexTriggered = UpdatePinchState(indexDistance, ref _indexPinched);
            var middleTriggered = UpdatePinchState(middleDistance, ref _middlePinched);
            var ringTriggered = UpdatePinchState(ringDistance, ref _ringPinched);

            if (Time.unscaledTime - _lastTriggerTime < triggerCooldownSec)
            {
                return;
            }

            if (requireOnlyOnePinchAtATime)
            {
                var triggeredCount = (indexTriggered ? 1 : 0) + (middleTriggered ? 1 : 0) + (ringTriggered ? 1 : 0);
                if (triggeredCount != 1)
                {
                    return;
                }
            }

            if (indexTriggered)
            {
                TriggerScanOnce();
                _lastTriggerTime = Time.unscaledTime;
                return;
            }

            if (middleTriggered)
            {
                TriggerToggleLive();
                _lastTriggerTime = Time.unscaledTime;
                return;
            }

            if (ringTriggered)
            {
                TriggerCycleMode();
                _lastTriggerTime = Time.unscaledTime;
            }
        }

        private void ResolveRefs()
        {
            if (_panel == null)
            {
                _panel = FindFirstObjectByType<ByesQuest3ConnectionPanelMinimal>();
            }

            if (_scanController == null)
            {
                _scanController = FindFirstObjectByType<ScanController>();
            }
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

            if (_scanController != null)
            {
                _scanController.ScanOnceFromUi();
            }
        }

        private void TriggerToggleLive()
        {
            if (_panel != null)
            {
                _panel.TriggerToggleLiveFromUi();
                return;
            }

            if (_scanController != null)
            {
                _scanController.ToggleLiveFromUi();
            }
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
    }
}
