using System;
using System.Collections.Generic;
using BeYourEyes.Core.EventBus;
using BeYourEyes.Core.Events;

namespace BeYourEyes.Core.Scheduling
{
    public sealed class PromptScheduler
    {
        private const int RiskThrottleMs = 2000;
        private const int SafeModeNoticeThrottleMs = 60000;
        private const int StartupConnectingDelayMs = 3000;
        private const string SafeModeEnteredText = "Connection lost. Safe mode enabled: risk alerts only.";
        private const string SafeModeRestoredText = "Connection restored. Safe mode disabled.";
        private const string StartupConnectingText = "Connecting to gateway...";

        private readonly IEventBus bus;
        private readonly Func<long> nowMs;
        private readonly Dictionary<string, long> riskLastPublishedMsByText = new Dictionary<string, long>();

        private bool safeMode;
        private bool hasEverConnected;
        private bool startupPrompted;
        private long startupMs = long.MinValue;
        private long lastLostPromptMs = long.MinValue;

        public bool SafeModeEnabled => safeMode;

        public PromptScheduler(IEventBus bus, Func<long> nowMs)
        {
            this.bus = bus ?? throw new ArgumentNullException(nameof(bus));
            this.nowMs = nowMs ?? throw new ArgumentNullException(nameof(nowMs));
            startupMs = this.nowMs();

            this.bus.Subscribe<RiskEvent>(OnRiskEvent);
            this.bus.Subscribe<PerceptionEvent>(OnPerceptionEvent);
            this.bus.Subscribe<SystemHealthEvent>(OnSystemHealthEvent);
        }

        private void OnRiskEvent(RiskEvent evt)
        {
            if (evt == null || evt.envelope == null)
            {
                return;
            }

            var now = nowMs();
            if (evt.envelope.IsExpired(now))
            {
                return;
            }

            var riskText = string.IsNullOrWhiteSpace(evt.riskText) ? "Risk detected" : evt.riskText;
            if (riskLastPublishedMsByText.TryGetValue(riskText, out var lastMs) && now - lastMs < RiskThrottleMs)
            {
                return;
            }

            riskLastPublishedMsByText[riskText] = now;
            bus.Publish(new PromptEvent(evt.envelope, riskText, 100, true, "tts", "risk"));

            // TODO: wire PromptScheduler to InteractionStateMachine and force Emergency when risk escalates.
            bus.Publish(new DialogEvent(evt.envelope, "Suggest entering emergency state", true));
        }

        private void OnPerceptionEvent(PerceptionEvent evt)
        {
            if (evt == null || evt.envelope == null)
            {
                return;
            }

            var now = nowMs();
            if (evt.envelope.IsExpired(now))
            {
                return;
            }

            if (safeMode)
            {
                return;
            }

            var text = string.IsNullOrWhiteSpace(evt.summary) ? "Perception update available" : evt.summary;
            bus.Publish(new PromptEvent(evt.envelope, text, 10, false, "tts", "info"));
        }

        private void OnSystemHealthEvent(SystemHealthEvent evt)
        {
            if (evt == null || evt.envelope == null)
            {
                return;
            }

            var now = nowMs();
            if (evt.envelope.IsExpired(now))
            {
                return;
            }

            var status = (evt.status ?? string.Empty).Trim().ToLowerInvariant();
            if (status == "tick")
            {
                if (!hasEverConnected && !startupPrompted && now - startupMs >= StartupConnectingDelayMs)
                {
                    startupPrompted = true;
                    bus.Publish(new PromptEvent(evt.envelope, StartupConnectingText, 90, false, "tts", "system"));
                }

                return;
            }

            if (status == "gateway_connected")
            {
                hasEverConnected = true;
                if (safeMode)
                {
                    safeMode = false;
                    bus.Publish(new PromptEvent(evt.envelope, SafeModeRestoredText, 50, true, "tts", "system"));
                }
                return;
            }

            if (status != "gateway_disconnected" && status != "gateway_unreachable")
            {
                return;
            }

            if (!hasEverConnected || safeMode)
            {
                return;
            }

            safeMode = true;

            var shouldNotify = lastLostPromptMs == long.MinValue || now - lastLostPromptMs >= SafeModeNoticeThrottleMs;
            if (!shouldNotify)
            {
                return;
            }

            lastLostPromptMs = now;
            bus.Publish(new PromptEvent(evt.envelope, SafeModeEnteredText, 90, true, "tts", "system"));
        }
    }
}
