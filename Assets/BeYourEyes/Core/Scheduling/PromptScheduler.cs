using System;
using System.Collections.Generic;
using BeYourEyes.Core.EventBus;
using BeYourEyes.Core.Events;

namespace BeYourEyes.Core.Scheduling
{
    public sealed class PromptScheduler
    {
        private const int RiskThrottleMs = 2000;

        private readonly IEventBus bus;
        private readonly Func<long> nowMs;
        private readonly Dictionary<string, long> riskLastPublishedMsByText = new Dictionary<string, long>();

        public PromptScheduler(IEventBus bus, Func<long> nowMs)
        {
            this.bus = bus ?? throw new ArgumentNullException(nameof(bus));
            this.nowMs = nowMs ?? throw new ArgumentNullException(nameof(nowMs));

            this.bus.Subscribe<RiskEvent>(OnRiskEvent);
            this.bus.Subscribe<PerceptionEvent>(OnPerceptionEvent);
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

            var riskText = string.IsNullOrWhiteSpace(evt.riskText) ? "检测到风险" : evt.riskText;
            if (riskLastPublishedMsByText.TryGetValue(riskText, out var lastMs))
            {
                if (now - lastMs < RiskThrottleMs)
                {
                    return;
                }
            }

            riskLastPublishedMsByText[riskText] = now;

            var prompt = new PromptEvent(
                evt.envelope,
                riskText,
                100,
                true,
                "tts",
                "risk");

            bus.Publish(prompt);

            // TODO: wire PromptScheduler to InteractionStateMachine and force Emergency when risk escalates.
            var suggestion = new DialogEvent(evt.envelope, "建议进入紧急状态", true);
            bus.Publish(suggestion);
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

            var text = string.IsNullOrWhiteSpace(evt.summary) ? "检测到新信息" : evt.summary;
            var prompt = new PromptEvent(
                evt.envelope,
                text,
                10,
                false,
                "tts",
                "info");

            bus.Publish(prompt);
        }
    }
}
