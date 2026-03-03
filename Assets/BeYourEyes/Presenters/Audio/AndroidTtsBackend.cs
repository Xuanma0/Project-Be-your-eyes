using System;
using System.Threading;
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

                string initError = null;
                var initDone = new ManualResetEvent(false);
                activity.Call("runOnUiThread", new AndroidJavaRunnable(() =>
                {
                    try
                    {
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
                    }
                    catch (Exception ex)
                    {
                        initError = ex.Message;
                        initialized = false;
                    }
                    finally
                    {
                        initDone.Set();
                    }
                }));

                initDone.WaitOne(2000);
                if (!string.IsNullOrWhiteSpace(initError) || tts == null)
                {
                    Debug.LogWarning($"[AndroidTTS] init failed on UI thread: {initError}");
                    initialized = false;
                    return false;
                }

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
                activity?.Call("runOnUiThread", new AndroidJavaRunnable(() =>
                {
                    tts?.Call<int>("speak", text, queueMode, null, utteranceId);
                }));
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
                    if (activity != null)
                    {
                        activity.Call("runOnUiThread", new AndroidJavaRunnable(() =>
                        {
                            tts?.Call("stop");
                            tts?.Call("shutdown");
                        }));
                    }
                    else
                    {
                        tts.Call("stop");
                        tts.Call("shutdown");
                    }
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
            private readonly Action<int> onInitCallback;

            public TtsInitListener(Action<int> onInitAction)
                : base("android.speech.tts.TextToSpeech$OnInitListener")
            {
                onInitCallback = onInitAction;
            }

            public void onInit(int status)
            {
                onInitCallback?.Invoke(status);
            }
        }
#endif
    }
}
