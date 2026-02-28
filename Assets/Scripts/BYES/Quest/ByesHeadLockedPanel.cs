using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesHeadLockedPanel : MonoBehaviour
    {
        public float distance = 1.2f;
        public float yOffset = -0.15f;
        public bool followRotation = true;
        public float smooth = 12f;

        private Camera _targetCamera;
        private int _cameraRetryFrames;
        private bool _initialized;

        private void LateUpdate()
        {
            if (!TryResolveCamera())
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

            var targetRotation = Quaternion.LookRotation(toCamera.normalized, _targetCamera.transform.up);
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
