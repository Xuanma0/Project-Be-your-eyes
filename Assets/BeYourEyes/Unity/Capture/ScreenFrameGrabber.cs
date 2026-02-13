using System;
using System.Collections;
using UnityEngine;

namespace BeYourEyes.Unity.Capture
{
    public sealed class ScreenFrameGrabber : MonoBehaviour
    {
        public IEnumerator CaptureJpg(Action<byte[]> onDone)
        {
            yield return new WaitForEndOfFrame();

            var tex = ScreenCapture.CaptureScreenshotAsTexture();
            if (tex == null)
            {
                onDone?.Invoke(null);
                yield break;
            }

            var jpg = tex.EncodeToJPG(70);
            Destroy(tex);
            onDone?.Invoke(jpg);
        }
    }
}
