namespace BeYourEyes.Core.Events
{
    public sealed class DialogEvent
    {
        public readonly EventEnvelope envelope;
        public readonly string text;
        public readonly bool? requiresConfirmation;

        public DialogEvent(EventEnvelope envelope, string text, bool? requiresConfirmation = null)
        {
            this.envelope = envelope;
            this.text = text ?? string.Empty;
            this.requiresConfirmation = requiresConfirmation;
        }
    }
}
