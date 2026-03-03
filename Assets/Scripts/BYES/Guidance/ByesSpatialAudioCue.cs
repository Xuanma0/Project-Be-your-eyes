using System;
using UnityEngine;

namespace BYES.Guidance
{
    public sealed class ByesSpatialAudioCue : MonoBehaviour
    {
        [SerializeField] private float cooldownSec = 0.4f;
        [SerializeField] private float baseVolume = 0.6f;
        [SerializeField] private float pitchLeft = 0.9f;
        [SerializeField] private float pitchRight = 1.1f;
        [SerializeField] private float pitchCenter = 1.0f;
        [SerializeField] private float pitchStop = 0.7f;

        private AudioSource _left;
        private AudioSource _right;
        private AudioSource _center;
        private AudioClip _beepClip;
        private float _lastPlayedAt;

        public float CooldownSec => cooldownSec;

        public void SetCooldownSec(float value)
        {
            cooldownSec = Mathf.Clamp(value, 0.05f, 2f);
        }

        private void Awake()
        {
            _beepClip = CreateBeepClip();
            _left = CreateSource("LeftCue", new Vector3(-0.2f, 0f, 0.5f));
            _right = CreateSource("RightCue", new Vector3(0.2f, 0f, 0.5f));
            _center = CreateSource("CenterCue", new Vector3(0f, 0f, 0.5f));
        }

        public void Play(GuidanceOutput output)
        {
            if (Time.unscaledTime - _lastPlayedAt < Mathf.Max(0.05f, cooldownSec))
            {
                return;
            }

            if (_beepClip == null)
            {
                return;
            }

            var volume = Mathf.Clamp01(baseVolume * Mathf.Lerp(0.4f, 1f, output.Strength));
            switch (output.Direction)
            {
                case GuidanceDirection.Left:
                    PlayOne(_left, pitchLeft, volume);
                    break;
                case GuidanceDirection.Right:
                    PlayOne(_right, pitchRight, volume);
                    break;
                case GuidanceDirection.Center:
                    PlayOne(_center, pitchCenter, volume * 0.7f);
                    break;
                case GuidanceDirection.Stop:
                    PlayOne(_center, pitchStop, 1f);
                    break;
                default:
                    return;
            }

            _lastPlayedAt = Time.unscaledTime;
        }

        private void PlayOne(AudioSource source, float pitch, float volume)
        {
            if (source == null)
            {
                return;
            }
            source.pitch = Mathf.Clamp(pitch, 0.5f, 2f);
            source.volume = Mathf.Clamp01(volume);
            source.PlayOneShot(_beepClip);
        }

        private AudioSource CreateSource(string name, Vector3 localPos)
        {
            var go = new GameObject(name);
            go.transform.SetParent(transform, false);
            go.transform.localPosition = localPos;
            var src = go.AddComponent<AudioSource>();
            src.playOnAwake = false;
            src.spatialBlend = 1f;
            src.rolloffMode = AudioRolloffMode.Linear;
            src.minDistance = 0.1f;
            src.maxDistance = 3f;
            return src;
        }

        private static AudioClip CreateBeepClip()
        {
            const int sampleRate = 22050;
            const float durationSec = 0.08f;
            var sampleCount = Mathf.CeilToInt(sampleRate * durationSec);
            var clip = AudioClip.Create("BYES_GuidanceBeep", sampleCount, 1, sampleRate, false);
            var data = new float[sampleCount];
            var frequency = 960f;
            for (var i = 0; i < sampleCount; i += 1)
            {
                var t = i / (float)sampleRate;
                var env = Mathf.Clamp01(1f - (i / (float)sampleCount));
                data[i] = Mathf.Sin(2f * Mathf.PI * frequency * t) * env * 0.25f;
            }
            clip.SetData(data, 0);
            return clip;
        }
    }
}
