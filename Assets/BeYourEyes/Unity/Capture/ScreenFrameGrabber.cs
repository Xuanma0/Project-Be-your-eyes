using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Rendering;

namespace BeYourEyes.Unity.Capture
{
    public sealed class ScreenFrameGrabber : MonoBehaviour
    {
        private const string EnvUseAsyncReadback = "BYES_CAPTURE_USE_ASYNC_GPU_READBACK";
        private const string EnvTargetHz = "BYES_CAPTURE_TARGET_HZ";
        private const string EnvMaxInflight = "BYES_CAPTURE_MAX_INFLIGHT";

        [Header("Capture Encode")]
        [SerializeField] private int maxWidth = 960;
        [SerializeField] private int maxHeight = 540;
        [SerializeField] private int jpegQuality = 70;
        [SerializeField] private bool keepAspect = true;

        [Header("Capture Runtime")]
        [SerializeField] private bool useAsyncGpuReadback = true;
        [SerializeField] private int captureTargetHz = 1;
        [SerializeField] private int captureMaxInflight = 1;

        private readonly WaitForEndOfFrame _endOfFrame = new WaitForEndOfFrame();

        private RenderTexture _captureRt;
        private Texture2D _encodeTexture;
        private bool _runtimeAsyncEnabled;
        private bool _warnedNoAsync;
        private int _activeReadbackRequests;

        public bool SupportsAsyncGpuReadback => SystemInfo.supportsAsyncGPUReadback;
        public bool AsyncGpuReadbackEnabled => _runtimeAsyncEnabled;
        public int CaptureTargetHz => Mathf.Max(1, captureTargetHz);
        public int CaptureMaxInflight => Mathf.Max(1, captureMaxInflight);
        public int ActiveReadbackRequests => Mathf.Max(0, _activeReadbackRequests);

        private void Awake()
        {
            ApplyEnvOverrides();
            _runtimeAsyncEnabled = ResolveAsyncEnabled();
        }

        private void OnDestroy()
        {
            ReleaseResources();
        }

        public IEnumerator CaptureJpg(Action<byte[]> onDone)
        {
            yield return _endOfFrame;

            var sourceWidth = Mathf.Max(32, Screen.width);
            var sourceHeight = Mathf.Max(32, Screen.height);
            ResolveTargetSize(sourceWidth, sourceHeight, out var targetWidth, out var targetHeight);
            EnsureResources(targetWidth, targetHeight);

            var jpg = (byte[])null;

            if (_runtimeAsyncEnabled)
            {
                yield return CaptureAsync(targetWidth, targetHeight, bytes => jpg = bytes);
            }

            if (jpg == null || jpg.Length == 0)
            {
                jpg = CaptureSync(targetWidth, targetHeight);
            }

            onDone?.Invoke(jpg);
        }

        private IEnumerator CaptureAsync(int width, int height, Action<byte[]> onDone)
        {
            var maxInflight = Mathf.Max(1, captureMaxInflight);
            while (_activeReadbackRequests >= maxInflight)
            {
                yield return null;
            }

            CaptureScreenIntoRt();

            _activeReadbackRequests += 1;
            var request = AsyncGPUReadback.Request(_captureRt, 0, TextureFormat.RGB24);
            while (!request.done)
            {
                yield return null;
            }

            _activeReadbackRequests = Mathf.Max(0, _activeReadbackRequests - 1);

            if (request.hasError)
            {
                _runtimeAsyncEnabled = false;
                if (!_warnedNoAsync)
                {
                    _warnedNoAsync = true;
                    Debug.LogWarning("[ScreenFrameGrabber] AsyncGPUReadback failed, fallback to sync ReadPixels.");
                }
                onDone?.Invoke(null);
                yield break;
            }

            var data = request.GetData<byte>();
            if (!data.IsCreated || data.Length <= 0)
            {
                onDone?.Invoke(null);
                yield break;
            }

            EnsureEncodeTexture(width, height);
            _encodeTexture.LoadRawTextureData(data);
            _encodeTexture.Apply(false, false);
            onDone?.Invoke(_encodeTexture.EncodeToJPG(Mathf.Clamp(jpegQuality, 1, 100)));
        }

        private byte[] CaptureSync(int width, int height)
        {
            CaptureScreenIntoRt();
            EnsureEncodeTexture(width, height);

            var prevActive = RenderTexture.active;
            try
            {
                RenderTexture.active = _captureRt;
                _encodeTexture.ReadPixels(new Rect(0f, 0f, width, height), 0, 0, false);
                _encodeTexture.Apply(false, false);
                return _encodeTexture.EncodeToJPG(Mathf.Clamp(jpegQuality, 1, 100));
            }
            finally
            {
                RenderTexture.active = prevActive;
            }
        }

        private void CaptureScreenIntoRt()
        {
            try
            {
                ScreenCapture.CaptureScreenshotIntoRenderTexture(_captureRt);
            }
            catch (Exception ex)
            {
                if (!_warnedNoAsync)
                {
                    _warnedNoAsync = true;
                    Debug.LogWarning($"[ScreenFrameGrabber] CaptureScreenshotIntoRenderTexture failed: {ex.Message}");
                }
            }
        }

        private void ResolveTargetSize(int sourceWidth, int sourceHeight, out int targetWidth, out int targetHeight)
        {
            targetWidth = sourceWidth;
            targetHeight = sourceHeight;

            var widthLimit = maxWidth > 0 ? maxWidth : sourceWidth;
            var heightLimit = maxHeight > 0 ? maxHeight : sourceHeight;

            if (sourceWidth <= widthLimit && sourceHeight <= heightLimit)
            {
                return;
            }

            if (!keepAspect)
            {
                targetWidth = Mathf.Max(32, widthLimit);
                targetHeight = Mathf.Max(32, heightLimit);
                return;
            }

            var scaleX = (float)widthLimit / sourceWidth;
            var scaleY = (float)heightLimit / sourceHeight;
            var scale = Mathf.Clamp(Mathf.Min(scaleX, scaleY), 0.01f, 1f);
            targetWidth = Mathf.Max(32, Mathf.RoundToInt(sourceWidth * scale));
            targetHeight = Mathf.Max(32, Mathf.RoundToInt(sourceHeight * scale));
        }

        private void EnsureResources(int width, int height)
        {
            if (_captureRt != null && (_captureRt.width != width || _captureRt.height != height))
            {
                _captureRt.Release();
                Destroy(_captureRt);
                _captureRt = null;
            }

            if (_captureRt == null)
            {
                _captureRt = new RenderTexture(width, height, 0, RenderTextureFormat.ARGB32)
                {
                    name = "BeYourEyes.ScreenFrameGrabber.CaptureRT"
                };
                _captureRt.Create();
            }

            EnsureEncodeTexture(width, height);
        }

        private void EnsureEncodeTexture(int width, int height)
        {
            if (_encodeTexture != null && (_encodeTexture.width != width || _encodeTexture.height != height))
            {
                Destroy(_encodeTexture);
                _encodeTexture = null;
            }

            if (_encodeTexture == null)
            {
                _encodeTexture = new Texture2D(width, height, TextureFormat.RGB24, false)
                {
                    name = "BeYourEyes.ScreenFrameGrabber.EncodeTex"
                };
            }
        }

        private void ReleaseResources()
        {
            if (_captureRt != null)
            {
                _captureRt.Release();
                Destroy(_captureRt);
                _captureRt = null;
            }

            if (_encodeTexture != null)
            {
                Destroy(_encodeTexture);
                _encodeTexture = null;
            }
        }

        private void ApplyEnvOverrides()
        {
            var asyncEnv = Environment.GetEnvironmentVariable(EnvUseAsyncReadback);
            if (TryParseBool(asyncEnv, out var asyncValue))
            {
                useAsyncGpuReadback = asyncValue;
            }
            else if (Application.platform == RuntimePlatform.Android)
            {
                useAsyncGpuReadback = true;
            }

            var targetHzEnv = Environment.GetEnvironmentVariable(EnvTargetHz);
            if (TryParsePositiveInt(targetHzEnv, out var targetHz))
            {
                captureTargetHz = targetHz;
            }

            var inflightEnv = Environment.GetEnvironmentVariable(EnvMaxInflight);
            if (TryParsePositiveInt(inflightEnv, out var inflight))
            {
                captureMaxInflight = inflight;
            }
        }

        private bool ResolveAsyncEnabled()
        {
            if (!useAsyncGpuReadback)
            {
                return false;
            }

            if (SystemInfo.supportsAsyncGPUReadback)
            {
                return true;
            }

            if (!_warnedNoAsync)
            {
                _warnedNoAsync = true;
                Debug.LogWarning("[ScreenFrameGrabber] AsyncGPUReadback unsupported on this device, fallback to sync ReadPixels.");
            }

            return false;
        }

        private static bool TryParseBool(string raw, out bool value)
        {
            value = false;
            if (string.IsNullOrWhiteSpace(raw))
            {
                return false;
            }

            var normalized = raw.Trim().ToLowerInvariant();
            if (normalized == "1" || normalized == "true" || normalized == "yes" || normalized == "on")
            {
                value = true;
                return true;
            }

            if (normalized == "0" || normalized == "false" || normalized == "no" || normalized == "off")
            {
                value = false;
                return true;
            }

            return false;
        }

        private static bool TryParsePositiveInt(string raw, out int value)
        {
            value = 0;
            if (string.IsNullOrWhiteSpace(raw))
            {
                return false;
            }

            if (!int.TryParse(raw.Trim(), out var parsed))
            {
                return false;
            }

            if (parsed <= 0)
            {
                return false;
            }

            value = parsed;
            return true;
        }
    }
}
