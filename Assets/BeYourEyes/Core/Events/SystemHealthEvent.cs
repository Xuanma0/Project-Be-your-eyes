namespace BeYourEyes.Core.Events
{
    public sealed class SystemHealthEvent
    {
        public readonly EventEnvelope envelope;
        public readonly string status;
        public readonly int? rttMs;

        public SystemHealthEvent(EventEnvelope envelope, string status, int? rttMs = null)
        {
            this.envelope = envelope;
            this.status = status ?? string.Empty;
            this.rttMs = rttMs;
        }
    }
}
