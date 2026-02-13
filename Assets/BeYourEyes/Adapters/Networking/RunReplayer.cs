using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEngine;
using BeYourEyes.Unity.Capture;

namespace BeYourEyes.Adapters.Networking
{
    public sealed class RunReplayer : MonoBehaviour
    {
        [SerializeField] private GatewayClient gatewayClient;
        [SerializeField] private FrameCapture frameCapture;
        [SerializeField] private float replaySpeed = 1f;
        [SerializeField] private bool reconnectAfterReplay;
        [SerializeField] private bool verboseLogs;

        private Coroutine replayRoutine;
        private readonly List<ReplayEntry> replayEntries = new List<ReplayEntry>();

        public bool IsReplaying { get; private set; }
        public int ReplayIndex { get; private set; }
        public int ReplayTotal => replayEntries.Count;
        public float ReplaySpeed => Mathf.Max(0.25f, replaySpeed);
        public string CurrentReplayRunId { get; private set; } = string.Empty;
        public string CurrentReplayDirectory { get; private set; } = string.Empty;
        public string LastReplayError { get; private set; } = string.Empty;

        private struct ReplayEntry
        {
            public long OffsetMs;
            public JObject Event;
        }

        private void OnEnable()
        {
            EnsureDependencies();
        }

        private void Update()
        {
            if (gatewayClient == null || frameCapture == null)
            {
                EnsureDependencies();
            }
        }

        private void OnDisable()
        {
            StopReplay();
        }

        public bool ReplayLatestRun(out string message)
        {
            var latest = RunRecorder.GetLatestRunDirectory();
            if (string.IsNullOrWhiteSpace(latest))
            {
                message = "no_runs";
                LastReplayError = message;
                return false;
            }

            return ReplayRun(latest, out message);
        }

        public bool ReplayRun(string runDirectory, out string message)
        {
            StopReplay();
            EnsureDependencies();

            if (gatewayClient == null)
            {
                message = "gateway_missing";
                LastReplayError = message;
                return false;
            }

            if (string.IsNullOrWhiteSpace(runDirectory) || !Directory.Exists(runDirectory))
            {
                message = "run_dir_missing";
                LastReplayError = message;
                return false;
            }

            var uiPath = Path.Combine(runDirectory, "ui_events.jsonl");
            if (!File.Exists(uiPath))
            {
                message = "ui_events_missing";
                LastReplayError = message;
                return false;
            }

            if (!TryLoadEntries(uiPath, out message))
            {
                LastReplayError = message;
                return false;
            }

            CurrentReplayDirectory = runDirectory;
            CurrentReplayRunId = new DirectoryInfo(runDirectory).Name;
            replayRoutine = StartCoroutine(ReplayLoop());
            return true;
        }

        public void StopReplay()
        {
            if (replayRoutine != null)
            {
                StopCoroutine(replayRoutine);
                replayRoutine = null;
            }

            if (IsReplaying)
            {
                gatewayClient?.ExitReplayMode(reconnectAfterReplay);
            }

            IsReplaying = false;
            ReplayIndex = 0;
            replayEntries.Clear();
        }

        private void EnsureDependencies()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<GatewayClient>();
            }
            if (frameCapture == null)
            {
                frameCapture = FindFirstObjectByType<FrameCapture>();
            }
        }

        private bool TryLoadEntries(string uiEventsPath, out string message)
        {
            replayEntries.Clear();
            ReplayIndex = 0;

            string[] lines;
            try
            {
                lines = File.ReadAllLines(uiEventsPath);
            }
            catch (Exception ex)
            {
                message = ex.Message;
                return false;
            }

            if (lines == null || lines.Length == 0)
            {
                message = "ui_events_empty";
                return false;
            }

            long firstReceivedAtMs = -1;
            foreach (var line in lines)
            {
                if (string.IsNullOrWhiteSpace(line))
                {
                    continue;
                }

                JObject row;
                try
                {
                    row = JObject.Parse(line);
                }
                catch
                {
                    continue;
                }

                var evt = row["event"] as JObject ?? row;
                var receivedAtMs = ReadLong(row, "receivedAtMs", -1);
                if (receivedAtMs <= 0)
                {
                    receivedAtMs = ReadLong(evt, "_receivedAtMs", -1);
                }
                if (receivedAtMs <= 0)
                {
                    receivedAtMs = replayEntries.Count == 0 ? 0 : replayEntries[replayEntries.Count - 1].OffsetMs + 100;
                }
                if (firstReceivedAtMs <= 0)
                {
                    firstReceivedAtMs = receivedAtMs;
                }

                replayEntries.Add(new ReplayEntry
                {
                    OffsetMs = Math.Max(0, receivedAtMs - firstReceivedAtMs),
                    Event = evt.DeepClone() as JObject ?? new JObject(),
                });
            }

            if (replayEntries.Count == 0)
            {
                message = "ui_events_parse_empty";
                return false;
            }

            message = "ok";
            return true;
        }

        private IEnumerator ReplayLoop()
        {
            IsReplaying = true;
            ReplayIndex = 0;
            LastReplayError = string.Empty;

            gatewayClient.EnterReplayMode();

            var speed = Mathf.Max(0.25f, replaySpeed);
            var replayStartMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            for (var i = 0; i < replayEntries.Count; i++)
            {
                var entry = replayEntries[i];
                while (true)
                {
                    var elapsedMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - replayStartMs;
                    var targetMs = (long)(entry.OffsetMs / speed);
                    if (elapsedMs >= targetMs)
                    {
                        break;
                    }

                    yield return null;
                }

                var evt = entry.Event.DeepClone() as JObject;
                if (evt == null)
                {
                    ReplayIndex = i + 1;
                    continue;
                }

                if (!gatewayClient.TryAcceptUiEvent(evt, ReadString(evt, "type"), out _, out _, out _, isReplay: true))
                {
                    ReplayIndex = i + 1;
                    continue;
                }

                gatewayClient.PublishAcceptedUiEvent(evt);
                ReplayIndex = i + 1;
                if (verboseLogs)
                {
                    Debug.Log($"[RunReplayer] replayed {ReplayIndex}/{ReplayTotal} type={ReadString(evt, "type")} seq={ReadLong(evt, "seq", -1)}");
                }

                yield return null;
            }

            gatewayClient.ExitReplayMode(reconnectAfterReplay);
            IsReplaying = false;
            replayRoutine = null;
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj?[key];
            return token == null ? string.Empty : token.ToString().Trim();
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

            return long.TryParse(token.ToString(), out var parsed) ? parsed : defaultValue;
        }
    }
}
