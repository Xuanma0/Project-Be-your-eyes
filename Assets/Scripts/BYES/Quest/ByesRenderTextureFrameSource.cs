using System;
using System.Collections;
using System.Collections.Generic;
using BeYourEyes.Unity.Capture;
using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesRenderTextureFrameSource : MonoBehaviour, IByesFrameSource
    {
        private const string CanonicalSourceName = "rendertexture_fallback";
        private const string SourceProviderName = "ByesRenderTextureFrameSource";

        [SerializeField] private ScreenFrameGrabber source;

        public string SourceName => CanonicalSourceName;
        public bool IsAvailable => source != null;
        public bool SupportsAsyncGpuReadback => source != null && source.SupportsAsyncGpuReadback;
        public bool AsyncGpuReadbackEnabled => source != null && source.AsyncGpuReadbackEnabled;
        public int CaptureTargetHz => source != null ? source.CaptureTargetHz : 1;
        public int CaptureMaxInflight => source != null ? source.CaptureMaxInflight : 1;
        public int ActiveReadbackRequests => source != null ? source.ActiveReadbackRequests : 0;
        public int LastFrameWidth => source != null ? source.LastFrameWidth : 0;
        public int LastFrameHeight => source != null ? source.LastFrameHeight : 0;

        private void Awake()
        {
            if (source == null)
            {
                source = GetComponent<ScreenFrameGrabber>();
            }
            if (source == null)
            {
                source = gameObject.AddComponent<ScreenFrameGrabber>();
            }
        }

        public IEnumerator CaptureJpg(Action<byte[]> onDone)
        {
            if (source == null)
            {
                onDone?.Invoke(null);
                yield break;
            }
            yield return source.CaptureJpg(onDone);
        }

        public void FillMeta(IDictionary<string, object> meta)
        {
            if (meta == null)
            {
                return;
            }
            if (source == null)
            {
                meta["frameSource"] = "unavailable";
                meta["frameSourceMode"] = "unavailable";
                meta["frameSourceStatus"] = "unavailable:missing_screen_grabber";
                meta["frameSourceKind"] = "unavailable";
                meta["frameSourceReason"] = "missing_screen_grabber";
                meta["frameSourceLabel"] = "unavailable";
                meta["frameSourceProvider"] = SourceProviderName;
                meta["pcaAvailable"] = false;
                meta["pcaReason"] = "missing_screen_grabber";
                return;
            }
            source.FillMeta(meta);
            meta["frameSource"] = SourceName;
            meta["frameSourceMode"] = CanonicalSourceName;
            meta["frameSourceStatus"] = "ok:rendertexture_fallback";
            meta["frameSourceKind"] = "fallback";
            meta["frameSourceReason"] = "screen_grabber_fallback";
            meta["frameSourceLabel"] = CanonicalSourceName;
            meta["frameSourceProvider"] = SourceProviderName;
            meta["pcaAvailable"] = false;
            meta["pcaReason"] = "screen_grabber_fallback";
        }
    }
}
