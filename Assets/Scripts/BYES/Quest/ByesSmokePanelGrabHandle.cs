using UnityEngine;
using UnityEngine.XR.Interaction.Toolkit;
using UnityEngine.XR.Interaction.Toolkit.Interactables;

namespace BYES.Quest
{
    [DisallowMultipleComponent]
    public sealed class ByesSmokePanelGrabHandle : MonoBehaviour
    {
        [SerializeField] private bool autoConfigure = true;
        [SerializeField] private Vector3 colliderCenter = new Vector3(0f, 0f, 0.01f);
        [SerializeField] private Vector3 colliderSize = new Vector3(0.48f, 0.34f, 0.04f);
        [SerializeField] private bool keepUnpinnedOnRelease = true;

        private XRGrabInteractable _grab;
        private ByesHeadLockedPanel _headLockedPanel;

        private void Awake()
        {
            if (autoConfigure)
            {
                EnsureGrabSetup();
            }
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

            var boxCollider = GetComponent<BoxCollider>();
            if (boxCollider == null)
            {
                boxCollider = gameObject.AddComponent<BoxCollider>();
            }
            boxCollider.center = colliderCenter;
            boxCollider.size = colliderSize;
            boxCollider.isTrigger = false;

            _grab = GetComponent<XRGrabInteractable>();
            if (_grab == null)
            {
                _grab = gameObject.AddComponent<XRGrabInteractable>();
            }

            _grab.throwOnDetach = false;
            _grab.trackPosition = true;
            _grab.trackRotation = true;
            _grab.movementType = XRBaseInteractable.MovementType.Instantaneous;
        }

        private void OnSelectEntered(SelectEnterEventArgs _)
        {
            _headLockedPanel?.SetPinned(false);
        }

        private void OnSelectExited(SelectExitEventArgs _)
        {
            if (!keepUnpinnedOnRelease)
            {
                _headLockedPanel?.SetPinned(true);
            }
        }
    }
}
