using System;
using UnityEngine;

namespace BeYourEyes.Presenters.Audio
{
    public sealed class AndroidTtsBackend : ITtsBackend
    {
#if UNITY_ANDROID && !UNITY_EDITOR
        private AndroidJavaObject activity;
        private AndroidJavaObject tts;
        private bool initialized;
        private int queueFlush = 0;
        private int queueAdd = 1;
#endif

        public bool Initialize(MonoBehaviour owner, float speechRate, float pitch)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                using (var unityPlayer = new AndroidJavaClass("com.unity3d.player.UnityPlayer"))
                {
                    activity = unityPlayer.GetStatic<AndroidJavaObject>("currentActivity");
                }

                if (activity == null)
                {
                    return false;
                }

                tts = new AndroidJavaObject("android.speech.tts.TextToSpeech", activity, new TtsInitListener(status =>
                {
                    initialized = status == 0;
                }));

                using (var localeClass = new AndroidJavaClass("java.util.Locale"))
                using (var ttsClass = new AndroidJavaClass("android.speech.tts.TextToSpeech"))
                {
                    var locale = localeClass.CallStatic<AndroidJavaObject>("getDefault");
                    queueFlush = ttsClass.GetStatic<int>("QUEUE_FLUSH");
                    queueAdd = ttsClass.GetStatic<int>("QUEUE_ADD");
                    tts.Call<int>("setLanguage", locale);
                }

                tts.Call<int>("setSpeechRate", Mathf.Clamp(speechRate, 0.5f, 2.0f));
                tts.Call<int>("setPitch", Mathf.Clamp(pitch, 0.5f, 2.0f));
                initialized = true;
                return true;
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[AndroidTTS] init failed: {ex.Message}");
                initialized = false;
                return false;
            }
#else
            return false;
#endif
        }

        public void Speak(string text, bool flushQueue)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!initialized || tts == null || string.IsNullOrWhiteSpace(text))
            {
                return;
            }

            try
            {
                var utteranceId = $"byes_{DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}";
                var queueMode = flushQueue ? queueFlush : queueAdd;
                tts.Call<int>("speak", text, queueMode, null, utteranceId);
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[AndroidTTS] speak failed: {ex.Message}");
            }
#endif
        }

        public void Shutdown()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                if (tts != null)
                {
                    tts.Call("stop");
                    tts.Call("shutdown");
                    tts.Dispose();
                    tts = null;
                }
                initialized = false;
            }
            catch
            {
            }
#endif
        }

#if UNITY_ANDROID && !UNITY_EDITOR
        private sealed class TtsInitListener : AndroidJavaProxy
        {
            private readonly Action<int> onInit;

            public TtsInitListener(Action<int> onInitAction)
                : base("android.speech.tts.TextToSpeech$OnInitListener")
            {
                onInit = onInitAction;
            }

            public void onInit(int status)
            {
                onInit?.Invoke(status);
            }
        }
#endif
    }
}
