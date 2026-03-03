using System;
using System.Collections;
using System.Collections.Generic;
using BeYourEyes.Unity.Capture;
using UnityEngine;

namespace BYES.Quest
{
    public sealed class ByesRenderTextureFrameSource : MonoBehaviour, IByesFrameSource
    {
        [SerializeField] private ScreenFrameGrabber source;

        public string SourceName => "rendertexture";
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
            if (source == null || meta == null)
            {
                return;
            }
            source.FillMeta(meta);
            meta["frameSource"] = SourceName;
        }
    }
}
