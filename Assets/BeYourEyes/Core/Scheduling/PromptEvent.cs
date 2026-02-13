using BeYourEyes.Core.Events;

namespace BeYourEyes.Core.Scheduling
{
    public sealed class PromptEvent
    {
        public readonly EventEnvelope envelope;
        public readonly string text;
        public readonly int priority;
        public readonly bool canInterrupt;
        public readonly string channel;
        public readonly string category;

        public PromptEvent(
            EventEnvelope envelope,
            string text,
            int priority,
            bool canInterrupt,
            string channel,
            string category)
        {
            this.envelope = envelope;
            this.text = text ?? string.Empty;
            this.priority = priority;
            this.canInterrupt = canInterrupt;
            this.channel = channel ?? string.Empty;
            this.category = category ?? string.Empty;
        }
    }
}
