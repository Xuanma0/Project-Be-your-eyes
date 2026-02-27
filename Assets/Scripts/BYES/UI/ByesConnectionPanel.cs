using System;
using System.Collections;
using System.Text;
using BYES.Core;
using BYES.Telemetry;
using BeYourEyes.Adapters.Networking;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;

namespace BYES.UI
{
    public sealed class ByesConnectionPanel : MonoBehaviour
    {
        private const string PrefHost = "byes.connection.host";
        private const string PrefPort = "byes.connection.port";
        private const string PrefUseHttps = "byes.connection.https";
        private const string PrefApiKey = "byes.connection.api_key";

        [SerializeField] private bool showOnStart = true;
        [SerializeField] private bool allowKeyboardToggle = true;
        [SerializeField] private KeyCode toggleKey = KeyCode.BackQuote;
        [SerializeField] private string defaultHost = "127.0.0.1";
        [SerializeField] private int defaultPort = 8000;
        [SerializeField] private bool defaultUseHttps = false;
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private GatewayWsClient gatewayWsClient;

        private bool _visible;
        private string _host;
        private string _portText;
        private bool _useHttps;
        private string _apiKey;
        private string _status = "idle";
        private string _lastMode = "-";
        private string _lastEventType = "-";
        private int _lastRttMs = -1;
        private int _pingSeq = 0;
        private bool _pingInFlight;
        private bool _modeInFlight;

        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void AutoInstallOnQuestSmokeScene()
        {
            var scene = SceneManager.GetActiveScene();
            if (!string.Equals(scene.name, "Quest3SmokeScene", StringComparison.Ordinal))
            {
                return;
            }

            if (FindFirstObjectByType<ByesConnectionPanel>() == null)
            {
                var host = new GameObject("BYES_Quest3ConnectionPanel");
                host.AddComponent<ByesConnectionPanel>();
            }
        }

        private void Awake()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }

            if (gatewayWsClient == null)
            {
                gatewayWsClient = FindFirstObjectByType<GatewayWsClient>();
            }

            _host = PlayerPrefs.GetString(PrefHost, defaultHost).Trim();
            _portText = PlayerPrefs.GetString(PrefPort, defaultPort.ToString()).Trim();
            _useHttps = PlayerPrefs.GetInt(PrefUseHttps, defaultUseHttps ? 1 : 0) == 1;
            _apiKey = PlayerPrefs.GetString(PrefApiKey, string.Empty);
            _visible = showOnStart;
        }

        private void OnEnable()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnGatewayEvent += HandleGatewayEvent;
            }
        }

        private void OnDisable()
        {
            if (gatewayClient != null)
            {
                gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            }
        }

        private void Update()
        {
            if (allowKeyboardToggle && Input.GetKeyDown(toggleKey))
            {
                _visible = !_visible;
            }
        }

        private void HandleGatewayEvent(JObject evt)
        {
            if (evt == null)
            {
                return;
            }

            var type = evt.Value<string>("type");
            _lastEventType = string.IsNullOrWhiteSpace(type) ? "-" : type.Trim();
        }

        private void OnGUI()
        {
            if (!_visible)
            {
                return;
            }

            GUI.depth = -999;
            var width = Mathf.Min(Screen.width - 20, 640);
            var rect = new Rect(10, 10, width, 460);
            GUILayout.BeginArea(rect, GUI.skin.box);
            GUILayout.Label("BYES Quest Connection");
            GUILayout.Label($"GatewayClient: {(gatewayClient != null && gatewayClient.IsConnected ? "Connected" : "Disconnected")}");
            GUILayout.Label($"GatewayWsClient: {(gatewayWsClient != null ? gatewayWsClient.ConnectionState : "missing")}");
            GUILayout.Label($"Last RTT: {_lastRttMs} ms");
            GUILayout.Label($"Last Mode: {_lastMode}");
            GUILayout.Label($"Last Event Type: {_lastEventType}");
            GUILayout.Label($"Status: {_status}");
            GUILayout.Space(8);

            GUILayout.BeginHorizontal();
            GUILayout.Label("Host", GUILayout.Width(80));
            _host = GUILayout.TextField(_host ?? string.Empty, GUILayout.Width(220));
            GUILayout.Label("Port", GUILayout.Width(50));
            _portText = GUILayout.TextField(_portText ?? string.Empty, GUILayout.Width(80));
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            _useHttps = GUILayout.Toggle(_useHttps, "Use HTTPS / WSS");
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            GUILayout.Label("API Key", GUILayout.Width(80));
            _apiKey = GUILayout.TextField(_apiKey ?? string.Empty, GUILayout.Width(360));
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Save + Connect", GUILayout.Width(160)))
            {
                ApplyAndReconnect();
            }

            if (GUILayout.Button("Test Ping", GUILayout.Width(120)) && !_pingInFlight)
            {
                StartCoroutine(PingRoutine());
            }

            if (GUILayout.Button("Read Mode", GUILayout.Width(120)) && !_modeInFlight)
            {
                StartCoroutine(ReadModeRoutine());
            }
            GUILayout.EndHorizontal();

            GUILayout.Space(6);
            GUILayout.Label("Mode Controls");
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Walk", GUILayout.Width(100)))
            {
                SetMode(ByesMode.Walk);
            }

            if (GUILayout.Button("Read", GUILayout.Width(100)))
            {
                SetMode(ByesMode.ReadText);
            }

            if (GUILayout.Button("Inspect", GUILayout.Width(100)))
            {
                SetMode(ByesMode.Inspect);
            }
            GUILayout.EndHorizontal();
            GUILayout.EndArea();
        }

        private void SetMode(ByesMode mode)
        {
            ByesModeManager.Instance.SetMode(mode, "system");
        }

        private void ApplyAndReconnect()
        {
            var host = string.IsNullOrWhiteSpace(_host) ? defaultHost : _host.Trim();
            if (!int.TryParse(_portText, out var port) || port <= 0 || port > 65535)
            {
                port = defaultPort;
                _portText = port.ToString();
            }

            var scheme = _useHttps ? "https" : "http";
            var wsScheme = _useHttps ? "wss" : "ws";
            var baseUrl = $"{scheme}://{host}:{port}";
            var wsUrl = $"{wsScheme}://{host}:{port}/ws/events";

            PlayerPrefs.SetString(PrefHost, host);
            PlayerPrefs.SetString(PrefPort, port.ToString());
            PlayerPrefs.SetInt(PrefUseHttps, _useHttps ? 1 : 0);
            PlayerPrefs.SetString(PrefApiKey, _apiKey ?? string.Empty);
            PlayerPrefs.Save();

            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }

            if (gatewayWsClient == null)
            {
                gatewayWsClient = FindFirstObjectByType<GatewayWsClient>();
            }

            if (gatewayClient != null)
            {
                gatewayClient.SetApiKey(_apiKey, reconnect: false);
                gatewayClient.SetGatewayEndpoints(baseUrl, wsUrl, reconnect: true);
            }

            if (gatewayWsClient != null)
            {
                gatewayWsClient.SetConnectionConfig(wsUrl, _apiKey, reconnect: true);
            }

            _status = $"connected to {baseUrl}";
        }

        private IEnumerator PingRoutine()
        {
            _pingInFlight = true;
            _status = "ping...";
            var started = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var host = string.IsNullOrWhiteSpace(_host) ? defaultHost : _host.Trim();
            if (!int.TryParse(_portText, out var port) || port <= 0 || port > 65535)
            {
                port = defaultPort;
            }

            var scheme = _useHttps ? "https" : "http";
            var url = $"{scheme}://{host}:{port}/api/ping";
            var seq = ++_pingSeq;
            var payload = new JObject
            {
                ["deviceId"] = ByesFrameTelemetry.DeviceId,
                ["seq"] = seq,
                ["clientSendTsMs"] = started,
            };
            var bytes = Encoding.UTF8.GetBytes(payload.ToString());
            using (var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
            {
                req.uploadHandler = new UploadHandlerRaw(bytes);
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                if (!string.IsNullOrWhiteSpace(_apiKey))
                {
                    req.SetRequestHeader("X-BYES-API-Key", _apiKey.Trim());
                }

                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success)
                {
                    var done = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    _lastRttMs = (int)Mathf.Clamp((int)(done - started), 0, 60000);
                    _status = $"ping ok ({_lastRttMs} ms)";
                }
                else
                {
                    _status = $"ping failed: {req.error}";
                }
            }
            _pingInFlight = false;
        }

        private IEnumerator ReadModeRoutine()
        {
            _modeInFlight = true;
            _status = "read mode...";
            var host = string.IsNullOrWhiteSpace(_host) ? defaultHost : _host.Trim();
            if (!int.TryParse(_portText, out var port) || port <= 0 || port > 65535)
            {
                port = defaultPort;
            }

            var scheme = _useHttps ? "https" : "http";
            var deviceId = UnityWebRequest.EscapeURL(ByesFrameTelemetry.DeviceId);
            var url = $"{scheme}://{host}:{port}/api/mode?deviceId={deviceId}";

            using (var req = UnityWebRequest.Get(url))
            {
                req.downloadHandler = new DownloadHandlerBuffer();
                if (!string.IsNullOrWhiteSpace(_apiKey))
                {
                    req.SetRequestHeader("X-BYES-API-Key", _apiKey.Trim());
                }

                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success)
                {
                    try
                    {
                        var obj = JObject.Parse(req.downloadHandler.text ?? "{}");
                        _lastMode = obj.Value<string>("mode") ?? "-";
                        _status = $"mode ok: {_lastMode}";
                    }
                    catch (Exception ex)
                    {
                        _status = $"mode parse failed: {ex.Message}";
                    }
                }
                else
                {
                    _status = $"mode failed: {req.error}";
                }
            }
            _modeInFlight = false;
        }
    }
}
