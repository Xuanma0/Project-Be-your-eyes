using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using BeYourEyes.Adapters.Networking;
using BeYourEyes.Unity.Interaction;

namespace BeYourEyes.Presenters.Audio
{
    public sealed class SpeechOrchestrator : MonoBehaviour
    {
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;

        [Header("Policy")]
        [SerializeField] private int maxHistory = 8;
        [SerializeField] private int cooldownCriticalMs = 1200;
        [SerializeField] private int cooldownConfirmMs = 1500;
        [SerializeField] private int cooldownActionMs = 1200;
        [SerializeField] private int cooldownDialogMs = 2000;
        [SerializeField] private int maxConfirmOptionsSpoken = 3;
        [SerializeField] private int maxCharsPerUtterance = 120;

        [Header("Android TTS")]
        [SerializeField] private float speechRate = 1.0f;
        [SerializeField] private float pitch = 1.0f;

        private ITtsBackend ttsBackend;
        private readonly Dictionary<string, long> cooldownByKindMs = new Dictionary<string, long>();
        private readonly Dictionary<string, long> dedupeByKeyMs = new Dictionary<string, long>();
        private readonly Queue<string> dedupeOrder = new Queue<string>();
        private readonly List<SpeechRecord> history = new List<SpeechRecord>();

        private long lastWarnRiskSeq = -1;
        private string lastWarnRiskCategory = string.Empty;

        public long SpokenCount { get; private set; }
        public long DroppedByCooldownCount { get; private set; }
        public long DroppedByPolicyCount { get; private set; }
        public string LastSpokenKind { get; private set; } = "-";
        public long LastSpokenAtMs { get; private set; } = -1;

        private struct SpeechRecord
        {
            public string Kind;
            public string Text;
            public bool Flush;
            public long SpokenAtMs;
        }

        private void OnEnable()
        {
            EnsureDependencies();
            EnsureBackend();
            BindGatewayEvents();
        }

        private void OnDisable()
        {
            UnbindGatewayEvents();
            ttsBackend?.Shutdown();
            ttsBackend = null;
        }

        private void EnsureDependencies()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
            }
        }

        private void EnsureBackend()
        {
            if (ttsBackend != null)
            {
                return;
            }

            var androidBackend = new AndroidTtsBackend();
            if (androidBackend.Initialize(this, speechRate, pitch))
            {
                ttsBackend = androidBackend;
                return;
            }

            androidBackend.Shutdown();
            var dummy = new DummyTtsBackend();
            dummy.Initialize(this, speechRate, pitch);
            ttsBackend = dummy;
        }

        private void BindGatewayEvents()
        {
            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.OnUiEventAccepted -= HandleAcceptedUiEvent;
            gatewayClient.OnUiEventAccepted += HandleAcceptedUiEvent;
        }

        private void UnbindGatewayEvents()
        {
            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.OnUiEventAccepted -= HandleAcceptedUiEvent;
        }

        public void ReplayLast()
        {
            if (history.Count == 0)
            {
                return;
            }

            var record = history[history.Count - 1];
            ttsBackend?.Speak(record.Text, record.Flush);
        }

        public void SpeakLocalHint(string text, bool flush = false)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            TrySpeak("dialog", $"local_hint:{text}", text, flush, cooldownDialogMs, nowMs);
        }

        private void HandleAcceptedUiEvent(JObject evt)
        {
            if (evt == null)
            {
                return;
            }

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var type = ReadString(evt, "type");
            if (string.IsNullOrWhiteSpace(type))
            {
                return;
            }

            var healthStatus = ResolveHealthStatus(evt);
            var fallbackBlocked = localSafetyFallback != null && !localSafetyFallback.IsOk;
            var safeMode = string.Equals(healthStatus, "SAFE_MODE", StringComparison.OrdinalIgnoreCase);
            var degradedOrThrottled = string.Equals(healthStatus, "DEGRADED", StringComparison.OrdinalIgnoreCase)
                                      || string.Equals(healthStatus, "THROTTLED", StringComparison.OrdinalIgnoreCase);

            var safetyOnly = fallbackBlocked || safeMode;
            if (safetyOnly)
            {
                HandleSafetyOnly(evt, nowMs, healthStatus);
                return;
            }

            switch (type)
            {
                case "risk":
                    HandleRisk(evt, nowMs, degradedOrThrottled);
                    return;
                case "action_plan":
                    HandleActionOrConfirm(evt, nowMs, degradedOrThrottled);
                    return;
                case "confirm":
                    HandleActionOrConfirm(evt, nowMs, degradedOrThrottled);
                    return;
                case "dialog":
                    HandleDialog(evt, nowMs, degradedOrThrottled);
                    return;
                default:
                    return;
            }
        }

        private void HandleSafetyOnly(JObject evt, long nowMs, string healthStatus)
        {
            var type = ReadString(evt, "type");
            if (string.Equals(type, "risk", StringComparison.OrdinalIgnoreCase))
            {
                var riskLevel = ReadString(evt, "riskLevel");
                if (string.Equals(riskLevel, "critical", StringComparison.OrdinalIgnoreCase))
                {
                    var text = ReadString(evt, "riskText");
                    if (string.IsNullOrWhiteSpace(text))
                    {
                        text = ReadString(evt, "summary");
                    }
                    if (string.IsNullOrWhiteSpace(text))
                    {
                        text = "STOP. Critical risk.";
                    }
                    TrySpeak("critical", $"critical:{BuildDedupeSuffix(evt)}", text, true, cooldownCriticalMs, nowMs);
                    return;
                }
            }

            if (string.Equals(type, "health", StringComparison.OrdinalIgnoreCase))
            {
                var message = BuildSafetyMessage(healthStatus);
                TrySpeak("critical", $"health_safety:{healthStatus}", message, true, cooldownCriticalMs, nowMs);
                return;
            }

            DroppedByPolicyCount++;
        }

        private void HandleRisk(JObject evt, long nowMs, bool degradedOrThrottled)
        {
            var riskLevel = ReadString(evt, "riskLevel");
            if (string.IsNullOrWhiteSpace(riskLevel))
            {
                riskLevel = "warn";
            }

            var riskText = ReadString(evt, "riskText");
            if (string.IsNullOrWhiteSpace(riskText))
            {
                riskText = ReadString(evt, "summary");
            }
            if (string.IsNullOrWhiteSpace(riskText))
            {
                return;
            }

            if (string.Equals(riskLevel, "critical", StringComparison.OrdinalIgnoreCase))
            {
                TrySpeak("critical", $"critical:{BuildDedupeSuffix(evt)}", riskText, true, cooldownCriticalMs, nowMs);
                return;
            }

            if (degradedOrThrottled)
            {
                DroppedByPolicyCount++;
                return;
            }

            var seq = ReadLong(evt, "seq");
            var category = ReadString(evt, "hazardKind");
            if (string.IsNullOrWhiteSpace(category))
            {
                category = ReadString(evt, "hazardId");
            }
            if (string.IsNullOrWhiteSpace(category))
            {
                category = riskText;
            }

            var isNew = false;
            if (seq > 0 && seq > lastWarnRiskSeq)
            {
                isNew = true;
            }
            if (!string.IsNullOrWhiteSpace(category) && !string.Equals(category, lastWarnRiskCategory, StringComparison.Ordinal))
            {
                isNew = true;
            }

            lastWarnRiskSeq = Math.Max(lastWarnRiskSeq, seq);
            lastWarnRiskCategory = category;

            if (!isNew)
            {
                DroppedByPolicyCount++;
                return;
            }

            TrySpeak("action", $"warn:{category}:{seq}", riskText, false, cooldownActionMs, nowMs);
        }

        private void HandleActionOrConfirm(JObject evt, long nowMs, bool degradedOrThrottled)
        {
            var confirmId = ReadString(evt, "confirmId");
            if (!string.IsNullOrWhiteSpace(confirmId))
            {
                var prompt = ReadString(evt, "confirmPrompt");
                if (string.IsNullOrWhiteSpace(prompt))
                {
                    prompt = ReadString(evt, "summary");
                }
                if (string.IsNullOrWhiteSpace(prompt))
                {
                    prompt = "Please confirm";
                }

                var options = ReadOptions(evt, maxConfirmOptionsSpoken);
                var text = options.Count > 0 ? $"{prompt}. Options: {string.Join(", ", options)}." : prompt;
                TrySpeak("confirm", $"confirm:{confirmId}", text, true, cooldownConfirmMs, nowMs);
                return;
            }

            if (degradedOrThrottled)
            {
                DroppedByPolicyCount++;
                return;
            }

            var summary = ReadString(evt, "summary");
            if (string.IsNullOrWhiteSpace(summary))
            {
                summary = ReadString(evt, "instruction");
            }
            if (string.IsNullOrWhiteSpace(summary))
            {
                return;
            }

            var stage = ReadString(evt, "stage");
            var stageOne = string.Equals(stage, "1", StringComparison.OrdinalIgnoreCase);
            var keep = stageOne || ContainsStopScan(summary);
            if (!keep)
            {
                DroppedByPolicyCount++;
                return;
            }

            TrySpeak("action", $"action:{BuildDedupeSuffix(evt)}", summary, false, cooldownActionMs, nowMs);
        }

        private void HandleDialog(JObject evt, long nowMs, bool degradedOrThrottled)
        {
            if (degradedOrThrottled)
            {
                DroppedByPolicyCount++;
                return;
            }

            var text = ReadString(evt, "answer");
            if (string.IsNullOrWhiteSpace(text))
            {
                text = ReadString(evt, "summary");
            }
            if (string.IsNullOrWhiteSpace(text))
            {
                return;
            }

            TrySpeak("dialog", $"dialog:{BuildDedupeSuffix(evt)}", text, false, cooldownDialogMs, nowMs);
        }

        private void TrySpeak(string kind, string dedupeKey, string text, bool flush, int cooldownMs, long nowMs)
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return;
            }

            text = SanitizeUtterance(text);
            if (string.IsNullOrWhiteSpace(text))
            {
                return;
            }

            if (IsInCooldown(kind, cooldownMs, nowMs))
            {
                DroppedByCooldownCount++;
                return;
            }

            if (IsDuplicate(dedupeKey, nowMs))
            {
                DroppedByCooldownCount++;
                return;
            }

            ttsBackend?.Speak(text, flush);
            cooldownByKindMs[kind] = nowMs;
            RecordDedupe(dedupeKey, nowMs);
            AddHistory(new SpeechRecord
            {
                Kind = kind,
                Text = text,
                Flush = flush,
                SpokenAtMs = nowMs,
            });

            SpokenCount++;
            LastSpokenKind = kind;
            LastSpokenAtMs = nowMs;
        }

        private bool IsInCooldown(string kind, int cooldownMs, long nowMs)
        {
            if (!cooldownByKindMs.TryGetValue(kind, out var lastMs))
            {
                return false;
            }

            return nowMs - lastMs < Math.Max(0, cooldownMs);
        }

        private bool IsDuplicate(string key, long nowMs)
        {
            if (string.IsNullOrWhiteSpace(key))
            {
                return false;
            }

            if (dedupeByKeyMs.TryGetValue(key, out var lastSeen))
            {
                return nowMs - lastSeen < 10000;
            }

            return false;
        }

        private void RecordDedupe(string key, long nowMs)
        {
            if (string.IsNullOrWhiteSpace(key))
            {
                return;
            }

            dedupeByKeyMs[key] = nowMs;
            dedupeOrder.Enqueue(key);
            while (dedupeOrder.Count > 32)
            {
                var oldest = dedupeOrder.Dequeue();
                if (oldest == key)
                {
                    continue;
                }
                dedupeByKeyMs.Remove(oldest);
            }
        }

        private void AddHistory(SpeechRecord record)
        {
            history.Add(record);
            while (history.Count > Math.Max(1, maxHistory))
            {
                history.RemoveAt(0);
            }
        }

        private static string BuildDedupeSuffix(JObject evt)
        {
            var seq = ReadLong(evt, "seq");
            var hazardId = ReadString(evt, "hazardId");
            var confirmId = ReadString(evt, "confirmId");
            var summary = ReadString(evt, "summary");
            return $"{seq}:{hazardId}:{confirmId}:{summary}";
        }

        private string SanitizeUtterance(string raw)
        {
            var text = raw.Trim();
            if (text.Length > Math.Max(16, maxCharsPerUtterance))
            {
                text = text.Substring(0, Math.Max(16, maxCharsPerUtterance)) + "...";
            }
            return text;
        }

        private string ResolveHealthStatus(JObject evt)
        {
            var status = ReadString(evt, "healthStatus");
            if (string.IsNullOrWhiteSpace(status) && gatewayClient != null)
            {
                status = gatewayClient.LastHealthStatus;
            }
            if (string.IsNullOrWhiteSpace(status))
            {
                status = ParseHealthStatusFromSummary(ReadString(evt, "summary"));
            }
            return status;
        }

        private static string BuildSafetyMessage(string healthStatus)
        {
            if (string.Equals(healthStatus, "SAFE_MODE", StringComparison.OrdinalIgnoreCase))
            {
                return "STOP. Safe mode enabled.";
            }
            return "STOP. Connection unstable.";
        }

        private static bool ContainsStopScan(string text)
        {
            var normalized = text.ToLowerInvariant();
            return normalized.Contains("stop")
                   || normalized.Contains("scan")
                   || normalized.Contains("confirm");
        }

        private static List<string> ReadOptions(JObject evt, int max)
        {
            var list = new List<string>();
            if (evt["confirmOptions"] is JArray options)
            {
                foreach (var token in options)
                {
                    if (list.Count >= Math.Max(1, max))
                    {
                        break;
                    }
                    var text = token?.ToString().Trim();
                    if (!string.IsNullOrWhiteSpace(text))
                    {
                        list.Add(text);
                    }
                }
            }

            return list;
        }

        private static long ReadLong(JObject obj, string key)
        {
            var token = obj[key];
            if (token == null)
            {
                return -1;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<long>();
            }

            return long.TryParse(token.ToString(), out var parsed) ? parsed : -1;
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }

        private static string ParseHealthStatusFromSummary(string summary)
        {
            if (string.IsNullOrWhiteSpace(summary))
            {
                return string.Empty;
            }

            var normalized = summary.Trim().ToLowerInvariant();
            if (normalized.StartsWith("gateway_safe_mode"))
            {
                return "SAFE_MODE";
            }
            if (normalized.StartsWith("gateway_throttled"))
            {
                return "THROTTLED";
            }
            if (normalized.StartsWith("gateway_degraded"))
            {
                return "DEGRADED";
            }
            if (normalized.StartsWith("gateway_normal"))
            {
                return "NORMAL";
            }

            return string.Empty;
        }
    }
}
