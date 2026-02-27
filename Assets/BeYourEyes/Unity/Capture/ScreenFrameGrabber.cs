using System;
using System.Collections;
using UnityEngine;

namespace BeYourEyes.Unity.Capture
{
    public sealed class ScreenFrameGrabber : MonoBehaviour
    {
        [Header("Capture Encode")]
        [SerializeField] private int maxWidth = 960;
        [SerializeField] private int maxHeight = 540;
        [SerializeField] private int jpegQuality = 70;
        [SerializeField] private bool keepAspect = true;

        public IEnumerator CaptureJpg(Action<byte[]> onDone)
        {
            yield return new WaitForEndOfFrame();

            var tex = ScreenCapture.CaptureScreenshotAsTexture();
            if (tex == null)
            {
                onDone?.Invoke(null);
                yield break;
            }

            var jpg = EncodeWithResize(tex);
            Destroy(tex);
            onDone?.Invoke(jpg);
        }

        private byte[] EncodeWithResize(Texture2D source)
        {
            if (source == null)
            {
                return null;
            }

            var sourceWidth = Mathf.Max(1, source.width);
            var sourceHeight = Mathf.Max(1, source.height);
            var targetWidth = sourceWidth;
            var targetHeight = sourceHeight;

            var widthLimit = maxWidth > 0 ? maxWidth : sourceWidth;
            var heightLimit = maxHeight > 0 ? maxHeight : sourceHeight;

            if (sourceWidth > widthLimit || sourceHeight > heightLimit)
            {
                if (keepAspect)
                {
                    var scaleX = (float)widthLimit / sourceWidth;
                    var scaleY = (float)heightLimit / sourceHeight;
                    var scale = Mathf.Clamp01(Mathf.Min(scaleX, scaleY));
                    targetWidth = Mathf.Max(1, Mathf.RoundToInt(sourceWidth * scale));
                    targetHeight = Mathf.Max(1, Mathf.RoundToInt(sourceHeight * scale));
                }
                else
                {
                    targetWidth = Mathf.Max(1, widthLimit);
                    targetHeight = Mathf.Max(1, heightLimit);
                }
            }

            var clampedQuality = Mathf.Clamp(jpegQuality, 1, 100);
            if (targetWidth == sourceWidth && targetHeight == sourceHeight)
            {
                return source.EncodeToJPG(clampedQuality);
            }

            var tempRt = RenderTexture.GetTemporary(targetWidth, targetHeight, 0, RenderTextureFormat.ARGB32);
            var previousRt = RenderTexture.active;
            try
            {
                Graphics.Blit(source, tempRt);
                RenderTexture.active = tempRt;
                var resized = new Texture2D(targetWidth, targetHeight, TextureFormat.RGB24, false);
                try
                {
                    resized.ReadPixels(new Rect(0, 0, targetWidth, targetHeight), 0, 0, false);
                    resized.Apply(false, false);
                    return resized.EncodeToJPG(clampedQuality);
                }
                finally
                {
                    Destroy(resized);
                }
            }
            finally
            {
                RenderTexture.active = previousRt;
                RenderTexture.ReleaseTemporary(tempRt);
            }
        }
    }
}
