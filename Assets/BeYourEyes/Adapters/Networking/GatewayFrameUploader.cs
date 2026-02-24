using System.Collections;
using BeYourEyes.Adapters;
using BYES.Telemetry;
using UnityEngine;
using UnityEngine.Networking;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class GatewayFrameUploader : MonoBehaviour
    {
        public string baseUrl = "http://127.0.0.1:8000";

        public IEnumerator UploadFrame(byte[] jpg, string metaJson = null)
        {
            if (jpg == null || jpg.Length == 0)
            {
                Debug.LogWarning("[Uploader] fail: empty frame");
                yield break;
            }

            var form = new WWWForm();
            form.AddBinaryData("image", jpg, "frame.jpg", "image/jpeg");
            if (!string.IsNullOrEmpty(metaJson))
            {
                form.AddField("meta", metaJson);
            }
            form.AddField("captureTsMs", ByesFrameTelemetry.NowUnixMs().ToString());
            form.AddField("deviceId", ByesFrameTelemetry.DeviceId);
            form.AddField("deviceTimeBase", ByesFrameTelemetry.DeviceTimeBase);

            var url = BuildFrameUrl();
            using (var req = UnityWebRequest.Post(url, form))
            {
                yield return req.SendWebRequest();

                if (req.result == UnityWebRequest.Result.Success)
                {
                    Debug.Log("[Uploader] ok");
                    yield break;
                }

                Debug.LogWarning($"[Uploader] fail: {req.error}");
                AppServices.Init();
                GatewayPoller.PublishSystemHealth("gateway_unreachable", -1, "gateway_uploader");
            }
        }

        private string BuildFrameUrl()
        {
            var normalizedBase = string.IsNullOrWhiteSpace(baseUrl) ? "http://127.0.0.1:8000" : baseUrl.Trim();
            return $"{normalizedBase.TrimEnd('/')}/api/frame";
        }
    }
}
