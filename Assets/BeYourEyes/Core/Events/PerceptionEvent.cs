using System.Collections.Generic;

namespace BeYourEyes.Core.Events
{
    public sealed class PerceptionEvent
    {
        public readonly EventEnvelope envelope;
        public readonly string summary;
        public readonly List<DetectedObject> objects;

        public PerceptionEvent(EventEnvelope envelope, string summary, List<DetectedObject> objects = null)
        {
            this.envelope = envelope;
            this.summary = summary ?? string.Empty;
            this.objects = objects;
        }
    }
}
