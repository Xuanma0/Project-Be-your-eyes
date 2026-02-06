namespace BeYourEyes.Adapters.Networking
{
    [System.Serializable]
    public class GatewayMockEventDto
    {
        public string type;
        public long timestampMs;
        public string coordFrame;
        public float confidence;
        public int ttlMs;
        public string source;
        public string riskText;
        public string summary;
        public float distanceM;
        public float azimuthDeg;
    }
}
