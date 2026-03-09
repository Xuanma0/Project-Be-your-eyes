using System.Collections;
using System;
using BeYourEyes.Adapters;
using UnityEngine;
using UnityEngine.Networking;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class GatewayFrameUploader : MonoBehaviour
    {
        public string baseUrl = "http://127.0.0.1:8000";
        [SerializeField] private string apiKey = "";

        public void SetApiKey(string value)
        {
            apiKey = string.IsNullOrWhiteSpace(value) ? string.Empty : value.Trim();
        }

        public IEnumerator UploadFrame(byte[] jpg, string metaJson = null, Action<bool, long> onCompleted = null)
        {
            if (jpg == null || jpg.Length == 0)
            {
                Debug.LogWarning("[Uploader] fail: empty frame");
                onCompleted?.Invoke(false, 0);
                yield break;
            }

            var startedAtMs = GatewayRuntimeContext.NowUnixMs();
            var form = new WWWForm();
            form.AddBinaryData("image", jpg, "frame.jpg", "image/jpeg");
            if (!string.IsNullOrEmpty(metaJson))
            {
                form.AddField("meta", metaJson);
            }
            form.AddField("captureTsMs", GatewayRuntimeContext.NowUnixMs().ToString());
            form.AddField("deviceId", GatewayRuntimeContext.DeviceId);
            form.AddField("deviceTimeBase", GatewayRuntimeContext.DeviceTimeBase);

            var url = BuildFrameUrl();
            using (var req = UnityWebRequest.Post(url, form))
            {
                if (!string.IsNullOrWhiteSpace(apiKey))
                {
                    req.SetRequestHeader("X-BYES-API-Key", apiKey.Trim());
                }

                yield return req.SendWebRequest();
                var elapsedMs = Math.Max(0, GatewayRuntimeContext.NowUnixMs() - startedAtMs);

                if (req.result == UnityWebRequest.Result.Success)
                {
                    Debug.Log("[Uploader] ok");
                    onCompleted?.Invoke(true, elapsedMs);
                    yield break;
                }

                Debug.LogWarning($"[Uploader] fail: {req.error}");
                AppServices.Init();
                GatewayPoller.PublishSystemHealth("gateway_unreachable", -1, "gateway_uploader");
                onCompleted?.Invoke(false, elapsedMs);
            }
        }

        private string BuildFrameUrl()
        {
            var normalizedBase = string.IsNullOrWhiteSpace(baseUrl) ? "http://127.0.0.1:8000" : baseUrl.Trim();
            return $"{normalizedBase.TrimEnd('/')}/api/frame";
        }
    }
}
