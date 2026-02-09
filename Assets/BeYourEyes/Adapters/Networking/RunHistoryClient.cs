using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class RunHistoryClient : MonoBehaviour
    {
        [SerializeField] private GatewayDevApi gatewayDevApi;
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private string baseUrl = "http://127.0.0.1:8000";
        [SerializeField] private int timeoutSec = 3;

        public string BaseUrl => NormalizeBaseUrl(baseUrl);

        private void Awake()
        {
            EnsureDependencies();
        }

        public void SetBaseUrl(string value)
        {
            baseUrl = NormalizeBaseUrl(value);
            if (gatewayDevApi != null)
            {
                gatewayDevApi.SetBaseUrl(baseUrl);
            }
        }

        public IEnumerator ListRuns(int limit, Action<bool, List<JObject>, string> onDone)
        {
            EnsureDependencies();
            var safeLimit = Mathf.Clamp(limit, 1, 200);
            var path = $"/api/run_packages?limit={safeLimit}";
            var completed = false;
            var ok = false;
            var error = string.Empty;
            var rows = new List<JObject>();
            yield return SendGet(path, result =>
            {
                completed = true;
                ok = result.ok;
                if (!result.ok)
                {
                    error = string.IsNullOrWhiteSpace(result.error) ? $"http_{result.statusCode}" : result.error;
                    return;
                }
                try
                {
                    var payload = JObject.Parse(string.IsNullOrWhiteSpace(result.body) ? "{}" : result.body);
                    var items = payload["items"] as JArray;
                    if (items != null)
                    {
                        for (var i = 0; i < items.Count; i++)
                        {
                            if (items[i] is JObject obj)
                            {
                                rows.Add(obj);
                            }
                        }
                    }
                }
                catch (Exception ex)
                {
                    ok = false;
                    error = $"parse_failed:{ex.Message}";
                }
            });
            if (!completed)
            {
                onDone?.Invoke(false, rows, "request_not_finished");
                yield break;
            }
            onDone?.Invoke(ok, rows, error);
        }

        public IEnumerator GetSummary(string runId, Action<bool, JObject, string> onDone)
        {
            EnsureDependencies();
            if (string.IsNullOrWhiteSpace(runId))
            {
                onDone?.Invoke(false, null, "run_id_empty");
                yield break;
            }
            var path = $"/api/run_packages/{UnityWebRequest.EscapeURL(runId.Trim())}/summary";
            var completed = false;
            var ok = false;
            var error = string.Empty;
            JObject summary = null;
            yield return SendGet(path, result =>
            {
                completed = true;
                ok = result.ok;
                if (!result.ok)
                {
                    error = string.IsNullOrWhiteSpace(result.error) ? $"http_{result.statusCode}" : result.error;
                    return;
                }
                try
                {
                    summary = JObject.Parse(string.IsNullOrWhiteSpace(result.body) ? "{}" : result.body);
                }
                catch (Exception ex)
                {
                    ok = false;
                    error = $"parse_failed:{ex.Message}";
                }
            });
            if (!completed)
            {
                onDone?.Invoke(false, null, "request_not_finished");
                yield break;
            }
            onDone?.Invoke(ok, summary, error);
        }

        public string GetReportUrl(string runId)
        {
            if (string.IsNullOrWhiteSpace(runId))
            {
                return string.Empty;
            }
            return $"{BaseUrl.TrimEnd('/')}/api/run_packages/{UnityWebRequest.EscapeURL(runId.Trim())}/report";
        }

        private IEnumerator SendGet(string path, Action<DevApiResult> onDone)
        {
            if (gatewayDevApi != null)
            {
                gatewayDevApi.SetBaseUrl(BaseUrl);
                yield return gatewayDevApi.SendGet(path, onDone);
                yield break;
            }

            var result = new DevApiResult
            {
                ok = false,
                statusCode = -1,
                latencyMs = -1,
                body = string.Empty,
                error = string.Empty,
            };
            var startedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            using (var req = UnityWebRequest.Get($"{BaseUrl.TrimEnd('/')}{path}"))
            {
                req.timeout = Mathf.Clamp(timeoutSec, 1, 30);
                req.downloadHandler = new DownloadHandlerBuffer();
                yield return req.SendWebRequest();
                var finishedAtMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                result.latencyMs = Math.Max(0, finishedAtMs - startedAtMs);
                result.statusCode = (long)req.responseCode;
                result.ok = req.responseCode >= 200 && req.responseCode < 300;
                result.body = req.downloadHandler != null ? req.downloadHandler.text ?? string.Empty : string.Empty;
                result.error = req.error ?? string.Empty;
            }
            onDone?.Invoke(result);
        }

        private void EnsureDependencies()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }
            if (gatewayDevApi == null)
            {
                gatewayDevApi = GetComponent<GatewayDevApi>();
                if (gatewayDevApi == null)
                {
                    gatewayDevApi = FindFirstObjectByType<GatewayDevApi>();
                }
            }
            if (gatewayClient != null && string.IsNullOrWhiteSpace(baseUrl))
            {
                baseUrl = gatewayClient.BaseUrl;
            }
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

