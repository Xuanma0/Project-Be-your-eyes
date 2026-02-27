using System;
using System.Collections;
using System.Text;
using BYES.Core;
using BYES.Telemetry;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Unity.Interaction;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.SceneManagement;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

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
        [SerializeField] private ScanController scanController;

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
        private bool _versionInFlight;
        private string _lastVersion = "-";
        private string _lastGitSha = "-";
        private string _selfTestStatus = "IDLE";
        private string _selfTestSummary = "-";

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

            if (scanController == null)
            {
                scanController = FindFirstObjectByType<ScanController>();
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
            if (allowKeyboardToggle && WasTogglePressedThisFrame())
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
            var rect = new Rect(10, 10, width, 560);
            GUILayout.BeginArea(rect, GUI.skin.box);
            GUILayout.Label("BYES Quest Connection");
            var httpBaseUrl = gatewayClient != null ? gatewayClient.BaseUrl : BuildBaseUrl();
            GUILayout.Label($"HTTP Base: {httpBaseUrl}");
            GUILayout.Label($"HTTP Link: {(gatewayClient != null && gatewayClient.IsConnected ? "Connected" : "Disconnected")}");
            GUILayout.Label($"WS Link: {(gatewayWsClient != null ? gatewayWsClient.ConnectionState : "missing")}");
            GUILayout.Label($"API Key: {(string.IsNullOrWhiteSpace(_apiKey) ? "not-set" : "set")}");
            GUILayout.Label($"Last RTT: {_lastRttMs} ms");
            GUILayout.Label($"Last Mode: {_lastMode}");
            GUILayout.Label($"Gateway Version: {_lastVersion} (sha: {_lastGitSha})");
            GUILayout.Label($"Last Event Type: {_lastEventType}");
            GUILayout.Label($"SelfTest: {_selfTestStatus}");
            GUILayout.Label($"SelfTest Summary: {_selfTestSummary}");
            GUILayout.Label($"Live: {BuildLiveSummary()}");
            GUILayout.Label($"Last Upload Cost: {BuildUploadCostSummary()}");
            GUILayout.Label($"Last E2E: {BuildE2eSummary()}");
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

            if (GUILayout.Button("Get Version", GUILayout.Width(120)) && !_versionInFlight)
            {
                StartCoroutine(GetVersionRoutine());
            }
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Export Debug Text", GUILayout.Width(160)))
            {
                ExportDebugText();
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

        private string BuildBaseUrl()
        {
            var host = string.IsNullOrWhiteSpace(_host) ? defaultHost : _host.Trim();
            if (!int.TryParse(_portText, out var port) || port <= 0 || port > 65535)
            {
                port = defaultPort;
            }

            var scheme = _useHttps ? "https" : "http";
            return $"{scheme}://{host}:{port}";
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

        private IEnumerator GetVersionRoutine()
        {
            _versionInFlight = true;
            _status = "version...";
            var host = string.IsNullOrWhiteSpace(_host) ? defaultHost : _host.Trim();
            if (!int.TryParse(_portText, out var port) || port <= 0 || port > 65535)
            {
                port = defaultPort;
            }

            var scheme = _useHttps ? "https" : "http";
            var url = $"{scheme}://{host}:{port}/api/version";

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
                        _lastVersion = obj.Value<string>("version") ?? "-";
                        _lastGitSha = obj.Value<string>("gitSha") ?? "-";
                        _status = $"version ok: {_lastVersion}";
                    }
                    catch (Exception ex)
                    {
                        _status = $"version parse failed: {ex.Message}";
                    }
                }
                else
                {
                    _status = $"version failed: {req.error}";
                }
            }
            _versionInFlight = false;
        }

        private string BuildLiveSummary()
        {
            if (scanController == null)
            {
                scanController = FindFirstObjectByType<ScanController>();
            }

            if (scanController == null)
            {
                return "scan-controller missing";
            }

            return $"{(scanController.LiveEnabled ? "on" : "off")} | fps={scanController.LiveFps:0.##} | inflight={scanController.InflightCount}/{scanController.LiveMaxInflight}";
        }

        private string BuildUploadCostSummary()
        {
            if (scanController == null)
            {
                return "n/a";
            }

            if (scanController.LastUploadCostMs < 0)
            {
                return "n/a";
            }

            return $"{scanController.LastUploadCostMs:0} ms";
        }

        private string BuildE2eSummary()
        {
            if (scanController == null)
            {
                return "n/a";
            }

            if (scanController.LastE2eMs < 0)
            {
                return "n/a";
            }

            return $"{scanController.LastE2eMs:0} ms";
        }

        public void SetSelfTestStatus(string status, string summary)
        {
            _selfTestStatus = string.IsNullOrWhiteSpace(status) ? "UNKNOWN" : status.Trim().ToUpperInvariant();
            _selfTestSummary = string.IsNullOrWhiteSpace(summary) ? "-" : summary.Trim();
        }

        public string ComposeDebugText()
        {
            var lines = new StringBuilder(512);
            lines.AppendLine("BYES Quest Debug Snapshot");
            lines.AppendLine($"TimestampUtc: {DateTimeOffset.UtcNow:O}");
            lines.AppendLine($"HTTP Base: {(gatewayClient != null ? gatewayClient.BaseUrl : BuildBaseUrl())}");
            lines.AppendLine($"HTTP Link: {(gatewayClient != null && gatewayClient.IsConnected ? "Connected" : "Disconnected")}");
            lines.AppendLine($"WS Link: {(gatewayWsClient != null ? gatewayWsClient.ConnectionState : "missing")}");
            lines.AppendLine($"API Key Set: {(string.IsNullOrWhiteSpace(_apiKey) ? "no" : "yes")}");
            lines.AppendLine($"Last RTT: {_lastRttMs}");
            lines.AppendLine($"Last Mode: {_lastMode}");
            lines.AppendLine($"Gateway Version: {_lastVersion}");
            lines.AppendLine($"Gateway GitSha: {_lastGitSha}");
            lines.AppendLine($"Last Event Type: {_lastEventType}");
            lines.AppendLine($"SelfTest: {_selfTestStatus}");
            lines.AppendLine($"SelfTest Summary: {_selfTestSummary}");
            lines.AppendLine($"Live: {BuildLiveSummary()}");
            lines.AppendLine($"Last Upload Cost: {BuildUploadCostSummary()}");
            lines.AppendLine($"Last E2E: {BuildE2eSummary()}");
            lines.AppendLine($"Status: {_status}");
            return lines.ToString();
        }

        private void ExportDebugText()
        {
            try
            {
                var text = ComposeDebugText();
                var path = System.IO.Path.Combine(Application.persistentDataPath, "byes_quest_debug.txt");
                System.IO.File.WriteAllText(path, text, Encoding.UTF8);
                _status = $"debug exported: {path}";
            }
            catch (Exception ex)
            {
                _status = $"debug export failed: {ex.Message}";
            }
        }

        private bool WasTogglePressedThisFrame()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb != null)
            {
                switch (toggleKey)
                {
                    case KeyCode.BackQuote:
                        return kb.backquoteKey.wasPressedThisFrame;
                    case KeyCode.Escape:
                        return kb.escapeKey.wasPressedThisFrame;
                }
            }
#endif
#if ENABLE_LEGACY_INPUT_MANAGER
            return Input.GetKeyDown(toggleKey);
#else
            return false;
#endif
        }
    }
}
