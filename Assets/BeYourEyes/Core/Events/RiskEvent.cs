namespace BeYourEyes.Core.Events
{
    public sealed class RiskEvent
    {
        public readonly EventEnvelope envelope;
        public readonly string riskText;
        public readonly float? distanceM;
        public readonly float? azimuthDeg;

        public RiskEvent(EventEnvelope envelope, string riskText, float? distanceM = null, float? azimuthDeg = null)
        {
            this.envelope = envelope;
            this.riskText = riskText ?? string.Empty;
            this.distanceM = distanceM;
            this.azimuthDeg = azimuthDeg;
        }
    }
}
