namespace BeYourEyes.Core.Events
{
    public sealed class DetectedObject
    {
        public readonly string label;
        public readonly float? distanceM;
        public readonly float? azimuthDeg;

        public DetectedObject(string label, float? distanceM = null, float? azimuthDeg = null)
        {
            this.label = label ?? string.Empty;
            this.distanceM = distanceM;
            this.azimuthDeg = azimuthDeg;
        }
    }
}
