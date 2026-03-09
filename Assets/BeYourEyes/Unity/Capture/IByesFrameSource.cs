using System;
using System.Collections;
using System.Collections.Generic;

namespace BeYourEyes.Unity.Capture
{
    public interface IByesFrameSource
    {
        string SourceName { get; }
        bool IsAvailable { get; }
        bool SupportsAsyncGpuReadback { get; }
        bool AsyncGpuReadbackEnabled { get; }
        int CaptureTargetHz { get; }
        int CaptureMaxInflight { get; }
        int ActiveReadbackRequests { get; }
        int LastFrameWidth { get; }
        int LastFrameHeight { get; }

        IEnumerator CaptureJpg(Action<byte[]> onDone);
        void FillMeta(IDictionary<string, object> meta);
    }
}
