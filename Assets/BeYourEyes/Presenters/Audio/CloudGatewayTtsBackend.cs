using System;
using System.Collections;
using System.IO;
using System.Text;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace BeYourEyes.Presenters.Audio
{
    public sealed class CloudGatewayTtsBackend : ITtsBackend
    {
        private readonly AndroidTtsBackend androidFallback = new AndroidTtsBackend();

        private MonoBehaviour owner;
        private AudioSource audioSource;
        private bool initialized;
        private bool cloudReady;
        private string baseUrl = "http://127.0.0.1:8000";
        private int timeoutSec = 6;
        private string speaker = "Chelsie";
        private Coroutine activeSpeakRoutine;
        private float cloudRetryCooldownSec = 10f;
        private float cloudRetryAt;

        public bool Initialize(MonoBehaviour owner, float speechRate, float pitch)
        {
            this.owner = owner;
            if (this.owner == null)
            {
                return false;
            }

            androidFallback.Initialize(owner, speechRate, pitch);

            var gatewayClient = UnityEngine.Object.FindFirstObjectByType<Adapters.Networking.GatewayClient>();
            if (gatewayClient != null)
            {
                baseUrl = gatewayClient.BaseUrl;
            }

            audioSource = owner.GetComponent<AudioSource>();
            if (audioSource == null)
            {
                audioSource = owner.gameObject.AddComponent<AudioSource>();
            }
            audioSource.playOnAwake = false;
            audioSource.loop = false;

            initialized = true;
            owner.StartCoroutine(ProbeCloudStatusRoutine());
            return true;
        }

        public void Speak(string text, bool flushQueue)
        {
            if (!initialized || string.IsNullOrWhiteSpace(text))
            {
                return;
            }

            if (flushQueue)
            {
                if (activeSpeakRoutine != null)
                {
                    owner.StopCoroutine(activeSpeakRoutine);
                    activeSpeakRoutine = null;
                }
                if (audioSource != null)
                {
                    audioSource.Stop();
                    audioSource.clip = null;
                }
            }

            var now = Time.realtimeSinceStartup;
            if (!cloudReady && now >= cloudRetryAt)
            {
                owner.StartCoroutine(ProbeCloudStatusRoutine());
            }

            if (!cloudReady)
            {
                androidFallback.Speak(text, flushQueue);
                return;
            }

            activeSpeakRoutine = owner.StartCoroutine(SpeakViaCloudRoutine(text, flushQueue));
        }

        public void Shutdown()
        {
            if (!initialized)
            {
                return;
            }

            if (activeSpeakRoutine != null && owner != null)
            {
                owner.StopCoroutine(activeSpeakRoutine);
                activeSpeakRoutine = null;
            }

            if (audioSource != null)
            {
                audioSource.Stop();
                audioSource.clip = null;
            }

            androidFallback.Shutdown();
            initialized = false;
        }

        private IEnumerator ProbeCloudStatusRoutine()
        {
            var url = $"{baseUrl.TrimEnd('/')}/api/tts/status";
            using (var req = UnityWebRequest.Get(url))
            {
                req.timeout = Mathf.Clamp(timeoutSec, 2, 15);
                req.downloadHandler = new DownloadHandlerBuffer();
                yield return req.SendWebRequest();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    cloudReady = false;
                    cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                    yield break;
                }

                var body = req.downloadHandler != null ? req.downloadHandler.text : string.Empty;
                try
                {
                    var payload = string.IsNullOrWhiteSpace(body) ? new JObject() : JObject.Parse(body);
                    cloudReady = payload.Value<bool?>("ready") == true;
                    if (!cloudReady)
                    {
                        cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                    }
                }
                catch
                {
                    cloudReady = false;
                    cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                }
            }
        }

        private IEnumerator SpeakViaCloudRoutine(string text, bool flushQueue)
        {
            var reqBody = new JObject
            {
                ["text"] = text,
                ["speaker"] = speaker,
                ["language"] = "Auto",
                ["instruct"] = string.Empty,
            }.ToString();

            var url = $"{baseUrl.TrimEnd('/')}/api/tts/synthesize";
            var bytes = Encoding.UTF8.GetBytes(reqBody);
            using (var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST))
            {
                req.uploadHandler = new UploadHandlerRaw(bytes);
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                req.timeout = Mathf.Clamp(timeoutSec, 2, 20);

                yield return req.SendWebRequest();

                if (req.result != UnityWebRequest.Result.Success)
                {
                    cloudReady = false;
                    cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                    androidFallback.Speak(text, flushQueue);
                    activeSpeakRoutine = null;
                    yield break;
                }

                var wavData = req.downloadHandler != null ? req.downloadHandler.data : null;
                if (wavData == null || wavData.Length == 0)
                {
                    cloudReady = false;
                    cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                    androidFallback.Speak(text, flushQueue);
                    activeSpeakRoutine = null;
                    yield break;
                }

                var tmpPath = Path.Combine(Application.temporaryCachePath, $"byes_qwen_tts_{DateTime.UtcNow.Ticks}.wav");
                try
                {
                    File.WriteAllBytes(tmpPath, wavData);
                }
                catch
                {
                    cloudReady = false;
                    cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                    androidFallback.Speak(text, flushQueue);
                    activeSpeakRoutine = null;
                    yield break;
                }

                var wavUrl = $"file://{tmpPath.Replace("\\", "/")}";
                using (var audioReq = UnityWebRequestMultimedia.GetAudioClip(wavUrl, AudioType.WAV))
                {
                    audioReq.timeout = Mathf.Clamp(timeoutSec, 2, 20);
                    yield return audioReq.SendWebRequest();
                    if (audioReq.result != UnityWebRequest.Result.Success)
                    {
                        cloudReady = false;
                        cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                        androidFallback.Speak(text, flushQueue);
                        activeSpeakRoutine = null;
                        yield break;
                    }

                    var clip = DownloadHandlerAudioClip.GetContent(audioReq);
                    if (clip == null)
                    {
                        cloudReady = false;
                        cloudRetryAt = Time.realtimeSinceStartup + cloudRetryCooldownSec;
                        androidFallback.Speak(text, flushQueue);
                        activeSpeakRoutine = null;
                        yield break;
                    }

                    if (audioSource != null)
                    {
                        if (flushQueue)
                        {
                            audioSource.Stop();
                        }
                        audioSource.clip = clip;
                        audioSource.Play();
                    }
                }

                activeSpeakRoutine = null;
            }
        }
    }
}