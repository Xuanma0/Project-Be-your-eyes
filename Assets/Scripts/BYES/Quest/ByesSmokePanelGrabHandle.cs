using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Interactables;

namespace BYES.Quest
{
    [DisallowMultipleComponent]
    public sealed class ByesSmokePanelGrabHandle : MonoBehaviour
    {
        [SerializeField] private bool autoConfigure = true;
        [SerializeField] private bool moveResizeEnabled;
        [SerializeField] private Vector3 colliderCenter = new Vector3(0f, 0f, 0.01f);
        [SerializeField] private Vector3 colliderSize = new Vector3(0.48f, 0.34f, 0.04f);
        [SerializeField] private bool keepUnpinnedOnRelease = true;
        [SerializeField] private bool keepFacingCameraOnGrab = true;
        [SerializeField] private bool rotateOnlyYaw = true;
        [SerializeField] private bool restoreHeadLockAfterRelease = true;

        private XRGrabInteractable _grab;
        private BoxCollider _boxCollider;
        private ByesHeadLockedPanel _headLockedPanel;
        private bool _grabStartedWithHeadLock;
        private bool _isGrabInProgress;

        public bool IsMoveResizeEnabled => moveResizeEnabled;
        public bool IsGrabInProgress => _isGrabInProgress;

        private void Awake()
        {
            if (autoConfigure)
            {
                EnsureGrabSetup();
            }

            ApplyMoveResizeState();
        }

        private void OnEnable()
        {
            EnsureGrabSetup();
            if (_grab == null)
            {
                return;
            }

            _grab.selectEntered.AddListener(OnSelectEntered);
            _grab.selectExited.AddListener(OnSelectExited);
        }

        private void OnDisable()
        {
            if (_grab == null)
            {
                return;
            }

            _grab.selectEntered.RemoveListener(OnSelectEntered);
            _grab.selectExited.RemoveListener(OnSelectExited);
            _isGrabInProgress = false;
        }

        private void EnsureGrabSetup()
        {
            if (_headLockedPanel == null)
            {
                _headLockedPanel = GetComponent<ByesHeadLockedPanel>();
            }

            var rb = GetComponent<Rigidbody>();
            if (rb == null)
            {
                rb = gameObject.AddComponent<Rigidbody>();
            }
            rb.isKinematic = true;
            rb.useGravity = false;

            _boxCollider = GetComponent<BoxCollider>();
            if (_boxCollider == null)
            {
                _boxCollider = gameObject.AddComponent<BoxCollider>();
            }
            _boxCollider.center = colliderCenter;
            _boxCollider.size = colliderSize;
            _boxCollider.isTrigger = false;

            _grab = GetComponent<XRGrabInteractable>();
            if (_grab == null)
            {
                _grab = gameObject.AddComponent<XRGrabInteractable>();
            }

            _grab.throwOnDetach = false;
            _grab.trackPosition = true;
            _grab.trackRotation = true;
            _grab.movementType = XRBaseInteractable.MovementType.Instantaneous;
            ApplyMoveResizeState();
        }

        public void SetMoveResizeEnabled(bool enabled)
        {
            moveResizeEnabled = enabled;
            if (!moveResizeEnabled)
            {
                _isGrabInProgress = false;
            }
            ApplyMoveResizeState();
        }

        public void ToggleMoveResizeEnabled()
        {
            SetMoveResizeEnabled(!moveResizeEnabled);
        }

        private void ApplyMoveResizeState()
        {
            if (_grab != null)
            {
                _grab.enabled = moveResizeEnabled;
            }

            if (_boxCollider != null)
            {
                _boxCollider.enabled = moveResizeEnabled;
            }
        }

        private void LateUpdate()
        {
            if (!moveResizeEnabled || !_isGrabInProgress || !keepFacingCameraOnGrab)
            {
                return;
            }

            var cameraTransform = Camera.main != null ? Camera.main.transform : null;
            if (cameraTransform == null)
            {
                return;
            }

            var toCamera = cameraTransform.position - transform.position;
            if (toCamera.sqrMagnitude < 0.0001f)
            {
                return;
            }

            if (rotateOnlyYaw)
            {
                toCamera.y = 0f;
                if (toCamera.sqrMagnitude < 0.0001f)
                {
                    return;
                }
            }

            var targetRotation = Quaternion.LookRotation(toCamera.normalized, Vector3.up);
            transform.rotation = Quaternion.Slerp(transform.rotation, targetRotation, Time.unscaledDeltaTime * 16f);
        }

        private void OnSelectEntered(SelectEnterEventArgs _)
        {
            _isGrabInProgress = true;
            if (_headLockedPanel == null)
            {
                return;
            }

            _grabStartedWithHeadLock = _headLockedPanel.IsLockToHeadEnabled;
            if (_grabStartedWithHeadLock)
            {
                _headLockedPanel.BeginTemporaryUnlock();
            }
            _headLockedPanel.SetPinned(false);
        }

        private void OnSelectExited(SelectExitEventArgs _)
        {
            _isGrabInProgress = false;
            if (!keepUnpinnedOnRelease)
            {
                _headLockedPanel?.SetPinned(true);
            }

            if (_headLockedPanel != null && restoreHeadLockAfterRelease && _grabStartedWithHeadLock)
            {
                _headLockedPanel.EndTemporaryUnlock();
            }
            _grabStartedWithHeadLock = false;
        }
    }
}
