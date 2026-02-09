using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace BeYourEyes.Adapters.Networking
{
    [Serializable]
    public struct DevApiResult
    {
        public bool ok;
        public long statusCode;
        public long latencyMs;
        public string body;
        public string error;
    }

    public sealed class GatewayDevApi : MonoBehaviour
    {
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private string baseUrl = "http://127.0.0.1:8000";
        [SerializeField] private int timeoutSec = 3;

        public string BaseUrl => NormalizeBaseUrl(baseUrl);
        public int TimeoutSec => Mathf.Max(1, timeoutSec);

        private void Awake()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }

            if (string.IsNullOrWhiteSpace(baseUrl) && gatewayClient != null)
            {
                baseUrl = gatewayClient.BaseUrl;
            }
        }

        public void SetBaseUrl(string value)
        {
            baseUrl = NormalizeBaseUrl(value);
        }

        public string UseBaseUrlFromGatewayClient()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }

            if (gatewayClient != null)
            {
                baseUrl = gatewayClient.BaseUrl;
            }

            return BaseUrl;
        }

        public IEnumerator SendGet(string path, Action<DevApiResult> onDone)
        {
            yield return SendRequest("GET", path, null, onDone);
        }

        public IEnumerator SendPostJson(string path, string jsonBody, Action<DevApiResult> onDone)
        {
            yield return SendRequest("POST", path, jsonBody, onDone);
        }

        private IEnumerator SendRequest(string method, string path, string jsonBody, Action<DevApiResult> onDone)
        {
            var startedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var result = new DevApiResult
            {
                ok = false,
                statusCode = -1,
                latencyMs = -1,
                body = string.Empty,
                error = string.Empty,
            };

            UnityWebRequest req = null;
            try
            {
                var url = BuildUrl(path);
                if (string.Equals(method, "GET", StringComparison.OrdinalIgnoreCase))
                {
                    req = UnityWebRequest.Get(url);
                }
                else
                {
                    req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST);
                    var bodyBytes = Encoding.UTF8.GetBytes(string.IsNullOrWhiteSpace(jsonBody) ? "{}" : jsonBody);
                    req.uploadHandler = new UploadHandlerRaw(bodyBytes);
                    req.SetRequestHeader("Content-Type", "application/json");
                }

                req.downloadHandler = new DownloadHandlerBuffer();
                req.timeout = TimeoutSec;
            }
            catch (Exception ex)
            {
                var finishedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                result.latencyMs = Math.Max(0, finishedAtMs - startedAtMs);
                result.statusCode = -1;
                result.error = ex.Message;
                result.ok = false;
                onDone?.Invoke(result);
                yield break;
            }

            try
            {
                yield return req.SendWebRequest();

                var finishedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                result.latencyMs = Math.Max(0, finishedAtMs - startedAtMs);
                result.statusCode = (long)req.responseCode;
                result.body = req.downloadHandler != null ? req.downloadHandler.text ?? string.Empty : string.Empty;
                result.error = req.error ?? string.Empty;
                result.ok = req.responseCode >= 200 && req.responseCode < 300;
            }
            finally
            {
                req.Dispose();
            }

            onDone?.Invoke(result);
        }

        private string BuildUrl(string path)
        {
            var normalizedPath = string.IsNullOrWhiteSpace(path) ? "/" : path.Trim();
            if (!normalizedPath.StartsWith("/"))
            {
                normalizedPath = "/" + normalizedPath;
            }

            return $"{BaseUrl.TrimEnd('/')}{normalizedPath}";
        }

        private static string NormalizeBaseUrl(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "http://127.0.0.1:8000";
            }

            return value.Trim().TrimEnd('/');
        }
    }
}
