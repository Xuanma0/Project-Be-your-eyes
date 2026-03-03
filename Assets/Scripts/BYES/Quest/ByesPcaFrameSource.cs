using System;
using System.Collections;
using System.Collections.Generic;
using BeYourEyes.Unity.Capture;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace BYES.Quest
{
    public sealed class ByesPcaFrameSource : MonoBehaviour, IByesFrameSource
    {
        [Header("PCA Capture")]
        [SerializeField] private bool androidOnly = true;
        [SerializeField] private int maxWidth = 960;
        [SerializeField] private int maxHeight = 540;
        [SerializeField] private int jpegQuality = 70;
        [SerializeField] private int captureTargetHz = 15;
        [SerializeField] private int captureMaxInflight = 1;

        private ARCameraManager _cameraManager;
        private Texture2D _encodeTexture;
        private int _lastWidth;
        private int _lastHeight;
        private bool _hasIntrinsics;
        private XRCameraIntrinsics _lastIntrinsics;
        private string _lastStatus = "uninitialized";

        public string SourceName => "pca";
        public bool IsAvailable => _cameraManager != null && (!androidOnly || Application.platform == RuntimePlatform.Android);
        public bool SupportsAsyncGpuReadback => false;
        public bool AsyncGpuReadbackEnabled => false;
        public int CaptureTargetHz => Mathf.Max(1, captureTargetHz);
        public int CaptureMaxInflight => Mathf.Max(1, captureMaxInflight);
        public int ActiveReadbackRequests => 0;
        public int LastFrameWidth => Mathf.Max(0, _lastWidth);
        public int LastFrameHeight => Mathf.Max(0, _lastHeight);

        private void Awake()
        {
            _cameraManager = FindFirstObjectByType<ARCameraManager>();
            if (_cameraManager == null)
            {
                _lastStatus = "missing_ar_camera_manager";
            }
            else
            {
                _lastStatus = "ready";
            }
        }

        private void OnDestroy()
        {
            if (_encodeTexture != null)
            {
                Destroy(_encodeTexture);
                _encodeTexture = null;
            }
        }

        public IEnumerator CaptureJpg(Action<byte[]> onDone)
        {
            if (!IsAvailable)
            {
                _lastStatus = _cameraManager == null ? "missing_ar_camera_manager" : "platform_not_supported";
                onDone?.Invoke(null);
                yield break;
            }

            if (!_cameraManager.TryAcquireLatestCpuImage(out var cpuImage))
            {
                _lastStatus = "cpu_image_unavailable";
                onDone?.Invoke(null);
                yield break;
            }

            var outputWidth = Mathf.Max(32, cpuImage.width);
            var outputHeight = Mathf.Max(32, cpuImage.height);
            ResolveTargetSize(cpuImage.width, cpuImage.height, out outputWidth, out outputHeight);
            var conversion = new XRCpuImage.ConversionParams
            {
                inputRect = new RectInt(0, 0, cpuImage.width, cpuImage.height),
                outputDimensions = new Vector2Int(outputWidth, outputHeight),
                outputFormat = TextureFormat.RGBA32,
                transformation = XRCpuImage.Transformation.None,
            };
            var dataSize = cpuImage.GetConvertedDataSize(conversion);
            var data = new NativeArray<byte>(dataSize, Allocator.Temp);
            try
            {
                cpuImage.Convert(conversion, data);
            }
            catch (Exception ex)
            {
                _lastStatus = $"convert_failed:{ex.GetType().Name}";
                data.Dispose();
                cpuImage.Dispose();
                onDone?.Invoke(null);
                yield break;
            }

            cpuImage.Dispose();

            EnsureTexture(outputWidth, outputHeight);
            _encodeTexture.LoadRawTextureData(data);
            _encodeTexture.Apply(false, false);
            data.Dispose();

            _lastWidth = outputWidth;
            _lastHeight = outputHeight;
            _hasIntrinsics = _cameraManager.TryGetIntrinsics(out _lastIntrinsics);
            _lastStatus = "ok";

            var jpg = _encodeTexture.EncodeToJPG(Mathf.Clamp(jpegQuality, 1, 100));
            onDone?.Invoke(jpg);
            yield break;
        }

        public void FillMeta(IDictionary<string, object> meta)
        {
            if (meta == null)
            {
                return;
            }

            meta["frameSource"] = SourceName;
            meta["frameWidth"] = LastFrameWidth;
            meta["frameHeight"] = LastFrameHeight;
            meta["captureTargetHz"] = CaptureTargetHz;
            meta["captureMaxInflight"] = CaptureMaxInflight;
            meta["pcaStatus"] = _lastStatus;
            if (_hasIntrinsics)
            {
                meta["fx"] = _lastIntrinsics.focalLength.x;
                meta["fy"] = _lastIntrinsics.focalLength.y;
                meta["cx"] = _lastIntrinsics.principalPoint.x;
                meta["cy"] = _lastIntrinsics.principalPoint.y;
            }
        }

        private void EnsureTexture(int width, int height)
        {
            if (_encodeTexture != null && (_encodeTexture.width != width || _encodeTexture.height != height))
            {
                Destroy(_encodeTexture);
                _encodeTexture = null;
            }

            if (_encodeTexture == null)
            {
                _encodeTexture = new Texture2D(width, height, TextureFormat.RGBA32, false)
                {
                    name = "BYES.PCA.EncodeTex",
                };
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

            var scaleX = (float)widthLimit / sourceWidth;
            var scaleY = (float)heightLimit / sourceHeight;
            var scale = Mathf.Clamp(Mathf.Min(scaleX, scaleY), 0.01f, 1f);
            targetWidth = Mathf.Max(32, Mathf.RoundToInt(sourceWidth * scale));
            targetHeight = Mathf.Max(32, Mathf.RoundToInt(sourceHeight * scale));
        }
    }
}
