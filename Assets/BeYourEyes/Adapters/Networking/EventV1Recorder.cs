using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace BeYourEyes.Adapters.Networking
{
    internal sealed class EventV1Recorder
    {
        private const string SchemaVersion = "byes.event.v1";
        private static readonly Regex FrameRegex = new Regex(@"(?:frame[_-]?|seq[_-]?)(\d+)", RegexOptions.IgnoreCase | RegexOptions.Compiled);
        private static readonly Regex NumberRegex = new Regex(@"(\d+)", RegexOptions.Compiled);

        private StreamWriter writer;

        public bool IsRecording => writer != null;

        public bool Start(string runDirectory, string eventsDirName, string fileName, out string error)
        {
            error = string.Empty;
            Stop();
            try
            {
                var eventsDir = Path.Combine(runDirectory, string.IsNullOrWhiteSpace(eventsDirName) ? "events" : eventsDirName);
                Directory.CreateDirectory(eventsDir);
                var outputPath = Path.Combine(eventsDir, string.IsNullOrWhiteSpace(fileName) ? "events_v1.jsonl" : fileName);
                writer = new StreamWriter(outputPath, false, new UTF8Encoding(false))
                {
                    AutoFlush = true,
                };
                return true;
            }
            catch (Exception ex)
            {
                writer = null;
                error = ex.Message;
                return false;
            }
        }

        public void Stop()
        {
            if (writer == null)
            {
                return;
            }

            writer.Flush();
            writer.Dispose();
            writer = null;
        }

        public bool RecordAcceptedEvent(JObject evt, long receivedAtMs, int ttlMs, out string error)
        {
            error = string.Empty;
            if (writer == null || evt == null)
            {
                return false;
            }

            try
            {
                var normalized = NormalizeEvent(evt, receivedAtMs, ttlMs);
                writer.WriteLine(normalized.ToString(Formatting.None));
                return true;
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }
        }

        private static JObject NormalizeEvent(JObject evt, long receivedAtMs, int ttlMs)
        {
            var tsMs = ReadLong(evt, "tsMs", -1);
            if (tsMs <= 0)
            {
                tsMs = ReadLong(evt, "timestampMs", -1);
            }
            if (tsMs <= 0)
            {
                tsMs = receivedAtMs > 0 ? receivedAtMs : DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            }

            var name = InferName(evt);
            var category = InferCategory(name);
            var phase = InferPhase(evt);
            var status = InferStatus(evt);
            var component = InferComponent(evt);
            var frameSeq = ExtractFrameSeq(evt);
            var latencyMs = ExtractLatencyMs(evt);
            var payload = BuildPayload(evt, name, ttlMs);

            return new JObject
            {
                ["schemaVersion"] = SchemaVersion,
                ["tsMs"] = tsMs,
                ["runId"] = ReadString(evt, "runId"),
                ["frameSeq"] = frameSeq > 0 ? frameSeq : JValue.CreateNull(),
                ["component"] = component,
                ["category"] = category,
                ["name"] = name,
                ["phase"] = string.IsNullOrWhiteSpace(phase) ? JValue.CreateNull() : phase,
                ["status"] = string.IsNullOrWhiteSpace(status) ? JValue.CreateNull() : status,
                ["latencyMs"] = latencyMs >= 0 ? latencyMs : JValue.CreateNull(),
                ["payload"] = payload,
            };
        }

        private static JObject BuildPayload(JObject evt, string name, int ttlMs)
        {
            var payload = evt["payload"] as JObject;
            var clone = payload != null ? (JObject)payload.DeepClone() : new JObject();
            if (ttlMs > 0 && clone["ttlMs"] == null)
            {
                clone["ttlMs"] = ttlMs;
            }

            if (name == "ocr.scan_text")
            {
                if (clone["text"] == null)
                {
                    var text = ResolveText(evt);
                    if (!string.IsNullOrWhiteSpace(text))
                    {
                        clone["text"] = text;
                    }
                }
            }
            else if (name == "risk.hazards" || name == "risk.depth")
            {
                if (clone["hazards"] == null)
                {
                    var hazards = ExtractHazards(evt);
                    if (hazards.Count > 0)
                    {
                        clone["hazards"] = hazards;
                    }
                }
            }
            else if (name == "safety.confirm")
            {
                if (clone["confirmId"] == null)
                {
                    var confirmId = ReadString(evt, "confirmId");
                    if (!string.IsNullOrWhiteSpace(confirmId))
                    {
                        clone["confirmId"] = confirmId;
                    }
                }
                if (clone["requestId"] == null)
                {
                    var requestId = ReadString(evt, "requestId");
                    if (!string.IsNullOrWhiteSpace(requestId))
                    {
                        clone["requestId"] = requestId;
                    }
                }
            }

            return clone;
        }

        private static string InferName(JObject evt)
        {
            var blob = BuildBlob(evt);
            if (ContainsAny(blob, "local_fallback", "safety_fallback", "on_device_fallback", "fallback_triggered"))
            {
                return "safety.local_fallback";
            }
            if (ContainsAny(blob, "preempt", "preemption"))
            {
                return "safety.preempt";
            }
            if (ContainsAny(blob, "critical_latch", "safety_lock", "latch", "emergency"))
            {
                return "safety.latch";
            }
            if (ContainsAny(blob, "confirm", "ask_user", "user_confirm", "clarify", "double_check"))
            {
                return "safety.confirm";
            }

            var hazards = ExtractHazards(evt);
            if (hazards.Count > 0)
            {
                return "risk.hazards";
            }

            if (ContainsAny(blob, "depth", "dropoff", "stair", "hazard"))
            {
                return "risk.depth";
            }
            if (ContainsAny(blob, "ocr", "scan_text", "read_text", "text_reader"))
            {
                return "ocr.scan_text";
            }

            var eventType = ReadString(evt, "type").ToLowerInvariant();
            if (eventType == "health")
            {
                return "system.health";
            }
            if (eventType == "metric")
            {
                return "metric.generic";
            }
            if (eventType == "scenario")
            {
                return "scenario.event";
            }
            return "unknown";
        }

        private static string InferCategory(string name)
        {
            if (name.StartsWith("ocr.", StringComparison.Ordinal) || name.StartsWith("risk.", StringComparison.Ordinal))
            {
                return "tool";
            }
            if (name.StartsWith("safety.", StringComparison.Ordinal))
            {
                return "safety";
            }
            if (name.StartsWith("system.", StringComparison.Ordinal))
            {
                return "system";
            }
            if (name.StartsWith("scenario.", StringComparison.Ordinal))
            {
                return "scenario";
            }
            if (name.StartsWith("metric.", StringComparison.Ordinal))
            {
                return "metric";
            }
            return "unknown";
        }

        private static string InferPhase(JObject evt)
        {
            var explicitPhase = ReadString(evt, "phase").ToLowerInvariant();
            if (explicitPhase == "start" || explicitPhase == "result" || explicitPhase == "error" || explicitPhase == "info")
            {
                return explicitPhase;
            }

            var blob = BuildBlob(evt);
            if (ContainsAny(blob, "start", "request", "intent", "call", "confirm_request", "double_check", "clarify"))
            {
                return "start";
            }
            if (ContainsAny(blob, "result", "response", "done"))
            {
                return "result";
            }
            if (ContainsAny(blob, "error", "exception", "fail", "timeout", "expired"))
            {
                return "error";
            }
            if (ContainsAny(blob, "info", "log"))
            {
                return "info";
            }
            return string.Empty;
        }

        private static string InferStatus(JObject evt)
        {
            var explicitStatus = ReadString(evt, "status").ToLowerInvariant();
            if (explicitStatus == "ok" || explicitStatus == "timeout" || explicitStatus == "cancel" || explicitStatus == "error")
            {
                return explicitStatus;
            }

            var blob = BuildBlob(evt);
            if (ContainsAny(blob, "timeout", "expired"))
            {
                return "timeout";
            }
            if (ContainsAny(blob, "cancel", "canceled", "cancelled"))
            {
                return "cancel";
            }
            if (ContainsAny(blob, "error", "exception", "fail"))
            {
                return "error";
            }
            if (ContainsAny(blob, "result", "response", "done", "ok", "success"))
            {
                return "ok";
            }
            return string.Empty;
        }

        private static string InferComponent(JObject evt)
        {
            var explicitComponent = ReadString(evt, "component").ToLowerInvariant();
            if (explicitComponent == "unity" || explicitComponent == "gateway" || explicitComponent == "cloud" || explicitComponent == "sim")
            {
                return explicitComponent;
            }

            var blob = string.Join(" ",
                ReadString(evt, "source"),
                ReadString(evt, "tool"),
                ReadString(evt, "toolName"),
                ReadString(evt, "category")).ToLowerInvariant();
            if (ContainsAny(blob, "unity"))
            {
                return "unity";
            }
            if (ContainsAny(blob, "gateway"))
            {
                return "gateway";
            }
            if (ContainsAny(blob, "real_", "cloud", "onnx", "vlm", "det", "ocr", "depth"))
            {
                return "cloud";
            }
            if (ContainsAny(blob, "mock", "sim"))
            {
                return "sim";
            }
            return "unknown";
        }

        private static int ExtractFrameSeq(JObject evt)
        {
            var direct = new[]
            {
                ReadLong(evt, "frameSeq", -1),
                ReadLong(evt, "frame_seq", -1),
                ReadLong(evt, "seq", -1),
                ReadLong(evt, "image_seq", -1),
            };
            for (var i = 0; i < direct.Length; i++)
            {
                if (direct[i] > 0)
                {
                    return (int)direct[i];
                }
            }

            var meta = evt["meta"] as JObject;
            if (meta != null)
            {
                var nested = ExtractFrameSeq(meta);
                if (nested > 0)
                {
                    return nested;
                }
            }

            var payload = evt["payload"] as JObject;
            if (payload != null)
            {
                var nested = ExtractFrameSeq(payload);
                if (nested > 0)
                {
                    return nested;
                }
            }

            var fromText = ParseSeqFromText(ReadString(evt, "frameId"));
            if (fromText > 0)
            {
                return fromText;
            }
            fromText = ParseSeqFromText(ReadString(evt, "filename"));
            if (fromText > 0)
            {
                return fromText;
            }
            fromText = ParseSeqFromText(ReadString(evt, "image"));
            if (fromText > 0)
            {
                return fromText;
            }
            fromText = ParseSeqFromText(ReadString(evt, "path"));
            if (fromText > 0)
            {
                return fromText;
            }

            return -1;
        }

        private static int ParseSeqFromText(string text)
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return -1;
            }

            var match = FrameRegex.Match(text);
            if (match.Success && int.TryParse(match.Groups[1].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var seq) && seq > 0)
            {
                return seq;
            }

            match = NumberRegex.Match(text);
            if (match.Success && int.TryParse(match.Groups[1].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out seq) && seq > 0)
            {
                return seq;
            }
            return -1;
        }

        private static int ExtractLatencyMs(JObject evt)
        {
            var latency = ReadLong(evt, "latencyMs", -1);
            if (latency < 0)
            {
                latency = ReadLong(evt, "durationMs", -1);
            }
            if (latency >= 0)
            {
                return (int)latency;
            }

            var start = ReadLong(evt, "startMs", -1);
            var end = ReadLong(evt, "endMs", -1);
            if (start >= 0 && end >= start)
            {
                return (int)(end - start);
            }

            var payload = evt["payload"] as JObject;
            if (payload != null)
            {
                return ExtractLatencyMs(payload);
            }
            return -1;
        }

        private static JArray ExtractHazards(JObject evt)
        {
            var hazards = new JArray();
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            void AddHazard(string kind, string severity)
            {
                if (string.IsNullOrWhiteSpace(kind))
                {
                    return;
                }

                var normalizedKind = kind.Trim().ToLowerInvariant();
                if (seen.Contains(normalizedKind))
                {
                    return;
                }

                seen.Add(normalizedKind);
                var row = new JObject
                {
                    ["hazardKind"] = normalizedKind,
                };
                if (!string.IsNullOrWhiteSpace(severity))
                {
                    row["severity"] = severity.Trim().ToLowerInvariant();
                }
                hazards.Add(row);
            }

            void ConsumeNode(JToken token)
            {
                if (token == null)
                {
                    return;
                }

                if (token is JObject obj)
                {
                    if (!string.IsNullOrWhiteSpace(ReadString(obj, "hazardKind")))
                    {
                        AddHazard(ReadString(obj, "hazardKind"), ReadString(obj, "severity"));
                    }
                    else if (!string.IsNullOrWhiteSpace(ReadString(obj, "kind")))
                    {
                        AddHazard(ReadString(obj, "kind"), ReadString(obj, "severity"));
                    }
                    else if (!string.IsNullOrWhiteSpace(ReadString(obj, "type")))
                    {
                        AddHazard(ReadString(obj, "type"), ReadString(obj, "severity"));
                    }

                    ConsumeNode(obj["hazards"]);
                    ConsumeNode(obj["risks"]);
                    ConsumeNode(obj["depthHazards"]);
                }
                else if (token is JArray arr)
                {
                    for (var i = 0; i < arr.Count; i++)
                    {
                        ConsumeNode(arr[i]);
                    }
                }
            }

            ConsumeNode(evt);
            return hazards;
        }

        private static string ResolveText(JObject evt)
        {
            var direct = ReadString(evt, "text");
            if (!string.IsNullOrWhiteSpace(direct))
            {
                return direct;
            }

            direct = ReadString(evt, "summary");
            if (!string.IsNullOrWhiteSpace(direct))
            {
                return direct;
            }

            var payload = evt["payload"] as JObject;
            if (payload != null)
            {
                direct = ReadString(payload, "text");
                if (!string.IsNullOrWhiteSpace(direct))
                {
                    return direct;
                }
                direct = ReadString(payload, "summary");
                if (!string.IsNullOrWhiteSpace(direct))
                {
                    return direct;
                }
            }

            return string.Empty;
        }

        private static string BuildBlob(JObject evt)
        {
            var parts = new List<string>
            {
                ReadString(evt, "type"),
                ReadString(evt, "name"),
                ReadString(evt, "tool"),
                ReadString(evt, "toolName"),
                ReadString(evt, "source"),
                ReadString(evt, "category"),
                ReadString(evt, "summary"),
                ReadString(evt, "message"),
                ReadString(evt, "event"),
                ReadString(evt, "status"),
            };

            var payload = evt["payload"] as JObject;
            if (payload != null)
            {
                parts.Add(ReadString(payload, "type"));
                parts.Add(ReadString(payload, "name"));
                parts.Add(ReadString(payload, "tool"));
                parts.Add(ReadString(payload, "toolName"));
                parts.Add(ReadString(payload, "source"));
                parts.Add(ReadString(payload, "category"));
                parts.Add(ReadString(payload, "summary"));
                parts.Add(ReadString(payload, "message"));
                parts.Add(ReadString(payload, "event"));
                parts.Add(ReadString(payload, "status"));
                parts.Add(ReadString(payload, "reason"));
                parts.Add(ReadString(payload, "error"));
            }

            return string.Join(" ", parts).ToLowerInvariant();
        }

        private static bool ContainsAny(string text, params string[] keywords)
        {
            if (string.IsNullOrEmpty(text) || keywords == null)
            {
                return false;
            }

            for (var i = 0; i < keywords.Length; i++)
            {
                var keyword = keywords[i];
                if (string.IsNullOrWhiteSpace(keyword))
                {
                    continue;
                }

                if (text.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }
            return false;
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj?[key];
            if (token == null)
            {
                return string.Empty;
            }
            var text = token.ToString();
            return string.IsNullOrWhiteSpace(text) ? string.Empty : text.Trim();
        }

        private static long ReadLong(JObject obj, string key, long defaultValue)
        {
            var token = obj?[key];
            if (token == null)
            {
                return defaultValue;
            }
            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<long>();
            }
            if (long.TryParse(token.ToString(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed))
            {
                return parsed;
            }
            if (double.TryParse(token.ToString(), NumberStyles.Float, CultureInfo.InvariantCulture, out var parsedDouble))
            {
                return (long)parsedDouble;
            }
            return defaultValue;
        }
    }
}
