using System.Collections.Generic;
using BYES.Quest;
using UnityEngine;
using UnityEngine.XR.Hands;

namespace BYES.XR
{
    public sealed class ByesWristMenuAnchor : MonoBehaviour
    {
        [SerializeField] private bool attachToLeftWrist = true;
        [SerializeField] private bool showWhenPalmUpOnly = true;
        [SerializeField] private bool forceVisible;
        [SerializeField] private float smooth = 14f;
        [SerializeField] private float palmUpDotThreshold = 0.35f;
        [SerializeField] private Vector3 wristLocalOffset = new Vector3(0.06f, 0.02f, 0.08f);

        private static readonly List<XRHandSubsystem> Subsystems = new List<XRHandSubsystem>();

        private XRHandSubsystem _subsystem;
        private ByesWristMenuController _menu;
        private Camera _mainCamera;
        private bool _initialized;

        public bool AttachToLeftWrist => attachToLeftWrist;

        private void Awake()
        {
            _menu = GetComponent<ByesWristMenuController>();
        }

        public void ToggleAnchorHand()
        {
            attachToLeftWrist = !attachToLeftWrist;
            _initialized = false;
        }

        public void SetAttachToLeftWrist(bool value)
        {
            attachToLeftWrist = value;
            _initialized = false;
        }

        public void SetForceVisible(bool value)
        {
            forceVisible = value;
        }

        public void ToggleForceVisible()
        {
            forceVisible = !forceVisible;
        }

        private void Update()
        {
            if (_menu == null)
            {
                _menu = GetComponent<ByesWristMenuController>();
                if (_menu == null)
                {
                    return;
                }
            }

            if (_mainCamera == null || !_mainCamera.isActiveAndEnabled)
            {
                _mainCamera = Camera.main;
            }

            if (!TryResolveSubsystem(out var subsystem))
            {
                _menu.SetVisible(forceVisible || !showWhenPalmUpOnly);
                return;
            }

            var hand = attachToLeftWrist ? subsystem.leftHand : subsystem.rightHand;
            if (!hand.isTracked)
            {
                _menu.SetVisible(forceVisible || !showWhenPalmUpOnly);
                return;
            }

            var wrist = hand.GetJoint(XRHandJointID.Wrist);
            var palm = hand.GetJoint(XRHandJointID.Palm);
            if (!wrist.TryGetPose(out var wristPose) || !palm.TryGetPose(out var palmPose))
            {
                _menu.SetVisible(forceVisible || !showWhenPalmUpOnly);
                return;
            }

            var targetPosition = wristPose.position + (wristPose.rotation * wristLocalOffset);
            var t = smooth > 0f
                ? 1f - Mathf.Exp(-smooth * Time.unscaledDeltaTime)
                : 1f;

            if (!_initialized)
            {
                transform.position = targetPosition;
                _initialized = true;
            }
            else
            {
                transform.position = Vector3.Lerp(transform.position, targetPosition, t);
            }

            if (_mainCamera != null)
            {
                var toCamera = _mainCamera.transform.position - transform.position;
                if (toCamera.sqrMagnitude > 0.0001f)
                {
                    var look = Quaternion.LookRotation(toCamera.normalized, Vector3.up);
                    transform.rotation = Quaternion.Slerp(transform.rotation, look, t);
                }
            }

            var palmUp = Vector3.Dot(palmPose.up, Vector3.up) >= palmUpDotThreshold;
            var visible = forceVisible || !showWhenPalmUpOnly || palmUp;
            _menu.SetVisible(visible);
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
    }
}
