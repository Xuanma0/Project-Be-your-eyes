using System;

namespace BeYourEyes.Core.Events
{
    public sealed class EventEnvelope
    {
        private const int DefaultTtlMs = 1000;

        public readonly long timestampMs;
        public readonly CoordFrame coordFrame;
        public readonly float confidence;
        public readonly int ttlMs;
        public readonly string source;

        public EventEnvelope(long timestampMs, CoordFrame coordFrame, float confidence, int ttlMs, string source)
        {
            this.timestampMs = timestampMs;
            this.coordFrame = coordFrame;
            this.confidence = Math.Clamp(confidence, 0f, 1f);

            // ttlMs <= 0 is normalized to 1000ms to avoid accidental immediate expiry.
            this.ttlMs = ttlMs <= 0 ? DefaultTtlMs : ttlMs;
            this.source = source ?? string.Empty;
        }

        public bool IsExpired(long nowMs)
        {
            return nowMs - timestampMs > ttlMs;
        }
    }
}
