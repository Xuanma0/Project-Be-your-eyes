using BeYourEyes.Unity.Interaction;
using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesFrameStreamer : MonoBehaviour
    {
        [SerializeField] private ScanController scanController;

        public bool LiveEnabled => scanController != null && scanController.IsLiveEnabled;
        public float CaptureHz => scanController != null ? scanController.CaptureTargetHz : 0f;
        public int Inflight => scanController != null ? scanController.InflightCount : 0;
        public int MaxInflight => scanController != null ? scanController.LiveMaxInflight : 0;
        public double LastUploadMs => scanController != null ? scanController.LastUploadCostMs : -1d;
        public double LastE2eMs => scanController != null ? scanController.LastE2eMs : -1d;
        public int DroppedFrames => scanController != null ? scanController.DropBusyCount : 0;

        private void Awake()
        {
            if (scanController == null)
            {
                scanController = FindFirstObjectByType<ScanController>();
            }
        }

        public void StartLive()
        {
            scanController?.SetLiveEnabled(true);
        }

        public void StopLive()
        {
            scanController?.SetLiveEnabled(false);
        }

        public void ToggleLive()
        {
            if (scanController == null)
            {
                return;
            }
            scanController.SetLiveEnabled(!scanController.IsLiveEnabled);
        }

        public void ScanOnce()
        {
            scanController?.ScanOnceFromUi();
        }
    }
}
