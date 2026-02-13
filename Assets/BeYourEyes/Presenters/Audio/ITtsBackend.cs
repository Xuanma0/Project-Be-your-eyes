namespace BeYourEyes.Presenters.Audio
{
    public interface ITtsBackend
    {
        bool Initialize(UnityEngine.MonoBehaviour owner, float speechRate, float pitch);
        void Speak(string text, bool flushQueue);
        void Shutdown();
    }
}
