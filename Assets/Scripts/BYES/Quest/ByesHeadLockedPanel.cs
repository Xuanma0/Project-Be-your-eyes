using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesHeadLockedPanel : MonoBehaviour
    {
        public float distance = 0.55f;
        public float yOffset = -0.08f;
        public bool followRotation = true;
        public float smooth = 12f;
        public bool invertFacing = true;
        public bool pinned = false;
        public bool lockToHead = true;

        private Camera _targetCamera;
        private int _cameraRetryFrames;
        private bool _initialized;
        private float _defaultDistance;
        private float _defaultYOffset;
        private bool _temporaryUnlock;

        private void Awake()
        {
            _defaultDistance = distance;
            _defaultYOffset = yOffset;
        }

        public bool IsPinned => pinned;
        public bool IsLockToHeadEnabled => lockToHead;
        public float Distance => distance;
        public float YOffset => yOffset;

        public void SetPinned(bool value)
        {
            pinned = value;
        }

        public void SetLockToHead(bool value)
        {
            lockToHead = value;
            if (lockToHead)
            {
                _initialized = false;
            }
        }

        public void BeginTemporaryUnlock()
        {
            _temporaryUnlock = true;
        }

        public void EndTemporaryUnlock()
        {
            _temporaryUnlock = false;
            if (lockToHead && !pinned)
            {
                _initialized = false;
            }
        }

        public void SetDistance(float value)
        {
            distance = Mathf.Clamp(value, 0.25f, 1.8f);
        }

        public void SetYOffset(float value)
        {
            yOffset = Mathf.Clamp(value, -1f, 1f);
        }

        public void RestoreDefaults()
        {
            distance = _defaultDistance;
            yOffset = _defaultYOffset;
            pinned = false;
            lockToHead = true;
            _temporaryUnlock = false;
            _initialized = false;
        }

        public void SnapToDefault()
        {
            _initialized = false;
            if (lockToHead)
            {
                pinned = false;
            }
        }

        private void LateUpdate()
        {
            if (!TryResolveCamera())
            {
                return;
            }

            if (!lockToHead || pinned || _temporaryUnlock)
            {
                return;
            }

            var targetPosition = _targetCamera.transform.position
                                 + (_targetCamera.transform.forward * distance)
                                 + (_targetCamera.transform.up * yOffset);

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

            if (!followRotation)
            {
                return;
            }

            var toCamera = _targetCamera.transform.position - transform.position;
            if (toCamera.sqrMagnitude < 0.00001f)
            {
                return;
            }

            var facingDirection = invertFacing ? -toCamera.normalized : toCamera.normalized;
            var targetRotation = Quaternion.LookRotation(facingDirection, _targetCamera.transform.up);
            transform.rotation = _initialized
                ? Quaternion.Slerp(transform.rotation, targetRotation, t)
                : targetRotation;
        }

        private bool TryResolveCamera()
        {
            if (_targetCamera != null && _targetCamera.isActiveAndEnabled)
            {
                return true;
            }

            if (_cameraRetryFrames >= 300)
            {
                return false;
            }

            _targetCamera = Camera.main;
            if (_targetCamera == null)
            {
                _targetCamera = FindFirstObjectByType<Camera>();
            }

            _cameraRetryFrames += 1;
            return _targetCamera != null && _targetCamera.isActiveAndEnabled;
        }
    }
}
