using System.Collections.Generic;
using UnityEngine;

namespace BYES.UI
{
    public sealed class ByesOverlayAckThrottler : MonoBehaviour
    {
        private static ByesOverlayAckThrottler _instance;
        private readonly Dictionary<string, int> _lastAckedFrameByKind = new Dictionary<string, int>();

        public static ByesOverlayAckThrottler Instance => EnsureExists();

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void Bootstrap()
        {
            _ = EnsureExists();
        }

        public static ByesOverlayAckThrottler EnsureExists()
        {
            if (_instance != null)
            {
                return _instance;
            }

            var existing = FindFirstObjectByType<ByesOverlayAckThrottler>();
            if (existing != null)
            {
                _instance = existing;
                DontDestroyOnLoad(_instance.gameObject);
                return _instance;
            }

            var root = new GameObject("BYES_OverlayAckThrottler");
            DontDestroyOnLoad(root);
            _instance = root.AddComponent<ByesOverlayAckThrottler>();
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
        }

        public bool TryMark(string runId, int frameSeq, string kind)
        {
            var normalizedRunId = string.IsNullOrWhiteSpace(runId) ? "unknown-run" : runId.Trim();
            var normalizedKind = string.IsNullOrWhiteSpace(kind) ? "any" : kind.Trim().ToLowerInvariant();
            var normalizedFrameSeq = Mathf.Max(1, frameSeq);
            var key = normalizedRunId + "|" + normalizedKind;
            if (_lastAckedFrameByKind.TryGetValue(key, out var seenSeq) && seenSeq == normalizedFrameSeq)
            {
                return false;
            }

            _lastAckedFrameByKind[key] = normalizedFrameSeq;
            if (_lastAckedFrameByKind.Count > 512)
            {
                _lastAckedFrameByKind.Clear();
            }
            return true;
        }
    }
}
