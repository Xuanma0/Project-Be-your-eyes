namespace BeYourEyes.Core.Events
{
    public sealed class NavigationEvent
    {
        public readonly EventEnvelope envelope;
        public readonly string instruction;
        public readonly float? distanceM;
        public readonly float? turnDeg;

        public NavigationEvent(EventEnvelope envelope, string instruction, float? distanceM = null, float? turnDeg = null)
        {
            this.envelope = envelope;
            this.instruction = instruction ?? string.Empty;
            this.distanceM = distanceM;
            this.turnDeg = turnDeg;
        }
    }
}
