namespace BeYourEyes.Adapters.Networking
{
    public enum CapabilityState
    {
        OK,
        OFFLINE,
        REMOTE_STALE,
        REMOTE_SAFE_MODE,
        REMOTE_THROTTLED,
        REMOTE_DEGRADED,
        LIMITED_NOT_READY,
    }
}
