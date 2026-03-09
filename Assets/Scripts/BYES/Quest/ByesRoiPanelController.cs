using System;
using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesRoiPanelController : MonoBehaviour
    {
        [SerializeField] private bool autoCreateOnQuestScene = true;
        [SerializeField] private bool visibleOnStart;

        private Rect _roiNorm = new Rect(0.35f, 0.35f, 0.3f, 0.3f);
        private bool _visible;

        public bool HasSelection { get; private set; }
        public Rect SelectedRoiNorm => _roiNorm;

        public event Action<Rect> OnConfirm;
        public event Action OnCancel;

        private void Awake()
        {
            _visible = visibleOnStart;
            gameObject.SetActive(_visible);
        }

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AutoBootstrap()
        {
            if (!string.Equals(UnityEngine.SceneManagement.SceneManager.GetActiveScene().name, "Quest3SmokeScene", StringComparison.Ordinal))
            {
                return;
            }

            if (FindFirstObjectByType<ByesRoiPanelController>() != null)
            {
                return;
            }

            var host = new GameObject("BYES_RoiPanelController");
            var ctrl = host.AddComponent<ByesRoiPanelController>();
            ctrl.autoCreateOnQuestScene = true;
        }

        public void ShowDefaultRoi()
        {
            _roiNorm = new Rect(0.35f, 0.35f, 0.3f, 0.3f);
            _visible = true;
            HasSelection = true;
            gameObject.SetActive(true);
        }

        public void SetRoiNorm(float x, float y, float w, float h)
        {
            var nx = Mathf.Clamp01(x);
            var ny = Mathf.Clamp01(y);
            var nw = Mathf.Clamp(w, 0.05f, 1f);
            var nh = Mathf.Clamp(h, 0.05f, 1f);
            if (nx + nw > 1f)
            {
                nx = 1f - nw;
            }
            if (ny + nh > 1f)
            {
                ny = 1f - nh;
            }
            _roiNorm = new Rect(nx, ny, nw, nh);
            HasSelection = true;
        }

        public void Confirm()
        {
            HasSelection = true;
            OnConfirm?.Invoke(_roiNorm);
            Hide();
        }

        public void Cancel()
        {
            OnCancel?.Invoke();
            Hide();
        }

        public void Hide()
        {
            _visible = false;
            gameObject.SetActive(false);
        }
    }
}
