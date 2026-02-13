using UnityEngine;

namespace BeYourEyes.Presenters.Audio
{
    public sealed class DummyTtsBackend : ITtsBackend
    {
        public bool Initialize(MonoBehaviour owner, float speechRate, float pitch)
        {
            return true;
        }

        public void Speak(string text, bool flushQueue)
        {
            Debug.Log($"[DummyTTS] {(flushQueue ? "FLUSH" : "ADD")} {text}");
        }

        public void Shutdown()
        {
        }
    }
}
