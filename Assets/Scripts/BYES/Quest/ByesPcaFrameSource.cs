using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using BeYourEyes.Unity.Capture;
using Unity.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;

namespace BYES.Quest
{
    public sealed class ByesPcaFrameSource : MonoBehaviour, IByesFrameSource
    {
        private const string CanonicalRealSourceName = "pca_real";
        private const string LegacySourceName = "pca";
        private const string CanonicalFallbackSourceName = "ar_cpuimage_fallback";
        private const string CanonicalRenderTextureSourceName = "rendertexture_fallback";
        private const string SourceProviderName = "ByesPcaFrameSource";
        private const string OpenXrRuntimeTypeName = "UnityEngine.XR.OpenXR.OpenXRRuntime, Unity.XR.OpenXR";
        private const string AndroidSceneUnderstandingCoarsePermission = "android.permission.SCENE_UNDERSTANDING_COARSE";
        private const string AndroidSceneUnderstandingFinePermission = "android.permission.SCENE_UNDERSTANDING_FINE";

        [Header("PCA Capture")]
        [SerializeField] private bool androidOnly = true;
        [SerializeField] private int maxWidth = 960;
        [SerializeField] private int maxHeight = 540;
        [SerializeField] private int jpegQuality = 70;
        [SerializeField] private int captureTargetHz = 15;
        [SerializeField] private int captureMaxInflight = 1;
        [SerializeField] private int requestedPcaWidth = 1280;
        [SerializeField] private int requestedPcaHeight = 960;
        [SerializeField] private float pcaStartupTimeoutSec = 0.35f;

        private ARCameraManager _cameraManager;
        private ScreenFrameGrabber _screenGrabber;
        private Texture2D _encodeTexture;
        private int _lastWidth;
        private int _lastHeight;
        private bool _hasIntrinsics;
        private XRCameraIntrinsics _lastIntrinsics;
        private string _lastStatus = "uninitialized";
        private string _sourceMode = "unavailable";
        private string _sourceReason = "uninitialized";
        private string _activeProviderName = SourceProviderName;
        private string _deviceModel = string.Empty;
        private string _runtimeName = string.Empty;
        private string _providerTypeName = string.Empty;
        private string _providerState = "missing";
        private string _providerStateReason = "provider_init_failed";
        private bool _cameraPermissionRequested;
        private bool _pcaDeviceSupported;
        private bool _pcaRuntimeSupported;
        private bool _pcaPermissionGranted;
        private bool _pcaProviderAvailable;
        private bool _pcaProviderReady;

        public string SourceName => string.IsNullOrWhiteSpace(_sourceMode) ? "unavailable" : _sourceMode;
        public bool IsAvailable => _cameraManager != null || _screenGrabber != null;
        public bool SupportsAsyncGpuReadback => IsRenderTextureActive() && _screenGrabber != null && _screenGrabber.SupportsAsyncGpuReadback;
        public bool AsyncGpuReadbackEnabled => IsRenderTextureActive() && _screenGrabber != null && _screenGrabber.AsyncGpuReadbackEnabled;
        public int CaptureTargetHz => IsRenderTextureActive() && _screenGrabber != null
            ? Mathf.Max(1, _screenGrabber.CaptureTargetHz)
            : Mathf.Max(1, captureTargetHz);
        public int CaptureMaxInflight => IsRenderTextureActive() && _screenGrabber != null
            ? Mathf.Max(1, _screenGrabber.CaptureMaxInflight)
            : Mathf.Max(1, captureMaxInflight);
        public int ActiveReadbackRequests => IsRenderTextureActive() && _screenGrabber != null
            ? Mathf.Max(0, _screenGrabber.ActiveReadbackRequests)
            : 0;
        public int LastFrameWidth => Mathf.Max(0, _lastWidth > 0 ? _lastWidth : (_screenGrabber != null ? _screenGrabber.LastFrameWidth : 0));
        public int LastFrameHeight => Mathf.Max(0, _lastHeight > 0 ? _lastHeight : (_screenGrabber != null ? _screenGrabber.LastFrameHeight : 0));

        private void Awake()
        {
            _cameraManager = FindFirstObjectByType<ARCameraManager>();
            _screenGrabber = GetComponent<ScreenFrameGrabber>();
            RefreshPcaProofFlags();
            InitializeIdleMode();
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
            RefreshPcaProofFlags();
            byte[] jpg = null;
            var rootReason = ResolvePcaRootReason();

            if (_pcaRuntimeSupported && !_pcaPermissionGranted)
            {
                MaybeRequestCameraPermission();
                RefreshPcaProofFlags();
                rootReason = ResolvePcaRootReason();
            }

            if (_cameraManager != null && _pcaRuntimeSupported && _pcaPermissionGranted)
            {
                string providerReason = rootReason;
                yield return WaitForProviderReady(reason => providerReason = reason);
                RefreshPcaProofFlags();

                if (_pcaProviderReady)
                {
                    string captureFailure = string.Empty;
                    yield return CaptureFromArCpuImage(
                        CanonicalRealSourceName,
                        "ok",
                        bytes => jpg = bytes,
                        reason => captureFailure = reason);
                    if (jpg != null && jpg.Length > 0)
                    {
                        onDone?.Invoke(jpg);
                        yield break;
                    }

                    if (!string.IsNullOrWhiteSpace(captureFailure))
                    {
                        rootReason = captureFailure;
                    }
                }
                else if (!string.IsNullOrWhiteSpace(providerReason))
                {
                    rootReason = providerReason;
                }
            }

            if (_cameraManager != null && _pcaPermissionGranted)
            {
                string fallbackFailure = string.Empty;
                yield return CaptureFromArCpuImage(
                    CanonicalFallbackSourceName,
                    rootReason,
                    bytes => jpg = bytes,
                    reason => fallbackFailure = reason);
                if (jpg != null && jpg.Length > 0)
                {
                    onDone?.Invoke(jpg);
                    yield break;
                }

                if (!string.IsNullOrWhiteSpace(fallbackFailure))
                {
                    rootReason = fallbackFailure;
                }
            }

            if (_screenGrabber != null)
            {
                yield return CaptureFromRenderTexture(rootReason, bytes => jpg = bytes);
                onDone?.Invoke(jpg);
                yield break;
            }

            SetUnavailable(string.IsNullOrWhiteSpace(rootReason) ? "missing_capture_fallback" : rootReason);
            onDone?.Invoke(null);
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
            meta["frameSourceProvider"] = _activeProviderName;
            meta["frameSourceKind"] = string.Equals(SourceName, CanonicalRealSourceName, StringComparison.OrdinalIgnoreCase)
                ? "real"
                : (string.Equals(SourceName, "unavailable", StringComparison.OrdinalIgnoreCase) ? "unavailable" : "fallback");
            meta["frameSourceReason"] = _sourceReason;
            meta["frameSourceLabel"] = SourceName;
            meta["frameSourceLegacy"] = LegacySourceName;
            meta["pcaStatus"] = _lastStatus;
            meta["frameSourceMode"] = _sourceMode;
            meta["frameSourceStatus"] = _lastStatus;
            meta["pcaAvailable"] = string.Equals(SourceName, CanonicalRealSourceName, StringComparison.OrdinalIgnoreCase);
            meta["pcaReason"] = _sourceReason;
            meta["pcaDeviceSupported"] = _pcaDeviceSupported;
            meta["pcaRuntimeSupported"] = _pcaRuntimeSupported;
            meta["pcaPermissionGranted"] = _pcaPermissionGranted;
            meta["pcaProviderAvailable"] = _pcaProviderAvailable;
            meta["pcaProviderReady"] = _pcaProviderReady;
            meta["deviceModel"] = _deviceModel;
            meta["pcaDeviceName"] = string.IsNullOrWhiteSpace(_providerTypeName) ? null : _providerTypeName;
            meta["pcaRuntimeName"] = _runtimeName;
            meta["pcaProviderState"] = _providerState;
            meta["pcaProviderStateReason"] = _providerStateReason;
            if (_hasIntrinsics)
            {
                meta["fx"] = _lastIntrinsics.focalLength.x;
                meta["fy"] = _lastIntrinsics.focalLength.y;
                meta["cx"] = _lastIntrinsics.principalPoint.x;
                meta["cy"] = _lastIntrinsics.principalPoint.y;
            }
        }

        private bool IsRenderTextureActive()
        {
            return string.Equals(_sourceMode, CanonicalRenderTextureSourceName, StringComparison.OrdinalIgnoreCase);
        }

        private void InitializeIdleMode()
        {
            var rootReason = ResolvePcaRootReason();
            if (HasFullPcaProof())
            {
                SetSourceState(
                    CanonicalRealSourceName,
                    "ok",
                    "ready:" + CanonicalRealSourceName,
                    BuildProviderName("PcaReal"));
                return;
            }

            if (_cameraManager != null && _pcaPermissionGranted)
            {
                SetSourceState(
                    CanonicalFallbackSourceName,
                    ComposeFallbackReason(rootReason, CanonicalFallbackSourceName),
                    "ready:" + CanonicalFallbackSourceName,
                    BuildProviderName("ARCpuImage"));
                return;
            }

            if (_screenGrabber != null)
            {
                SetSourceState(
                    CanonicalRenderTextureSourceName,
                    ComposeFallbackReason(rootReason, CanonicalRenderTextureSourceName),
                    "ready:" + CanonicalRenderTextureSourceName,
                    BuildProviderName("RenderTexture"));
                return;
            }

            SetUnavailable(string.IsNullOrWhiteSpace(rootReason) ? "missing_capture_fallback" : rootReason);
        }

        private IEnumerator WaitForProviderReady(Action<string> onDone)
        {
            var initialReason = ResolvePcaRootReason();
            if (!string.IsNullOrWhiteSpace(initialReason) && !IsProviderWarmupReason(initialReason))
            {
                onDone?.Invoke(initialReason);
                yield break;
            }

            var deadline = Time.realtimeSinceStartup + Mathf.Max(0.1f, pcaStartupTimeoutSec);
            while (Time.realtimeSinceStartup < deadline)
            {
                RefreshPcaProofFlags();
                if (_pcaProviderReady)
                {
                    onDone?.Invoke(string.Empty);
                    yield break;
                }

                var waitReason = ResolvePcaRootReason();
                if (!IsProviderWarmupReason(waitReason))
                {
                    onDone?.Invoke(waitReason);
                    yield break;
                }

                yield return null;
            }

            RefreshPcaProofFlags();
            var timeoutReason = ResolvePcaRootReason();
            if (string.IsNullOrWhiteSpace(timeoutReason) || IsProviderWarmupReason(timeoutReason))
            {
                timeoutReason = "provider_init_failed";
            }
            onDone?.Invoke(timeoutReason);
        }

        private IEnumerator CaptureFromArCpuImage(
            string sourceMode,
            string rootReason,
            Action<byte[]> onDone,
            Action<string> onFailureReason)
        {
            if (_cameraManager == null)
            {
                onFailureReason?.Invoke("missing_ar_camera_manager");
                onDone?.Invoke(null);
                yield break;
            }

            if (!_cameraManager.TryAcquireLatestCpuImage(out var cpuImage))
            {
                var failureReason = string.Equals(sourceMode, CanonicalRealSourceName, StringComparison.OrdinalIgnoreCase)
                    ? "provider_frame_unavailable"
                    : "ar_cpuimage_unavailable";
                SetFailedArCpuImageState(sourceMode, rootReason, failureReason);
                onFailureReason?.Invoke(failureReason);
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
                data.Dispose();
                cpuImage.Dispose();
                var failureReason = string.Equals(sourceMode, CanonicalRealSourceName, StringComparison.OrdinalIgnoreCase)
                    ? "provider_capture_failed"
                    : "ar_cpuimage_convert_failed";
                SetFailedArCpuImageState(sourceMode, rootReason, failureReason + ":" + ex.GetType().Name);
                onFailureReason?.Invoke(failureReason);
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

            if (string.Equals(sourceMode, CanonicalRealSourceName, StringComparison.OrdinalIgnoreCase))
            {
                SetSourceState(
                    CanonicalRealSourceName,
                    "ok",
                    "ok:" + CanonicalRealSourceName,
                    BuildProviderName("PcaReal"));
            }
            else
            {
                SetSourceState(
                    CanonicalFallbackSourceName,
                    ComposeFallbackReason(rootReason, CanonicalFallbackSourceName),
                    "ok:" + CanonicalFallbackSourceName,
                    BuildProviderName("ARCpuImage"));
            }

            var jpg = _encodeTexture.EncodeToJPG(Mathf.Clamp(jpegQuality, 1, 100));
            onDone?.Invoke(jpg);
        }

        private IEnumerator CaptureFromRenderTexture(string rootReason, Action<byte[]> onDone)
        {
            if (_screenGrabber == null)
            {
                SetUnavailable(string.IsNullOrWhiteSpace(rootReason) ? "missing_screen_grabber" : rootReason);
                _activeProviderName = BuildProviderName("RenderTexture");
                onDone?.Invoke(null);
                yield break;
            }

            byte[] jpg = null;
            yield return _screenGrabber.CaptureJpg(bytes => jpg = bytes);
            _lastWidth = _screenGrabber.LastFrameWidth;
            _lastHeight = _screenGrabber.LastFrameHeight;
            _hasIntrinsics = false;
            SetSourceState(
                CanonicalRenderTextureSourceName,
                ComposeFallbackReason(rootReason, CanonicalRenderTextureSourceName),
                jpg != null && jpg.Length > 0
                    ? "ok:" + CanonicalRenderTextureSourceName
                    : CanonicalRenderTextureSourceName + ":capture_failed",
                BuildProviderName("RenderTexture"));
            onDone?.Invoke(jpg);
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

        private void MaybeRequestCameraPermission()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_cameraPermissionRequested)
            {
                return;
            }

            try
            {
                if (!UnityEngine.Android.Permission.HasUserAuthorizedPermission(AndroidSceneUnderstandingFinePermission))
                {
                    UnityEngine.Android.Permission.RequestUserPermission(AndroidSceneUnderstandingFinePermission);
                }

                if (!UnityEngine.Android.Permission.HasUserAuthorizedPermission(AndroidSceneUnderstandingCoarsePermission))
                {
                    UnityEngine.Android.Permission.RequestUserPermission(AndroidSceneUnderstandingCoarsePermission);
                }

                if (!UnityEngine.Android.Permission.HasUserAuthorizedPermission(UnityEngine.Android.Permission.Camera))
                {
                    UnityEngine.Android.Permission.RequestUserPermission(UnityEngine.Android.Permission.Camera);
                }
            }
            catch
            {
                // Best effort only. Runtime truth still falls back if permission cannot be proven.
            }
            finally
            {
                _cameraPermissionRequested = true;
            }
#endif
        }

        private void RefreshPcaProofFlags()
        {
            _deviceModel = ResolveDeviceModel();
            _runtimeName = ResolveOpenXrRuntimeName();
            _pcaDeviceSupported = IsQuest3Family(_deviceModel);
            var runtimeUnsupportedReason = ResolveRuntimeUnsupportedReason(_runtimeName, _deviceModel);
            if (string.IsNullOrWhiteSpace(runtimeUnsupportedReason) && androidOnly && Application.platform != RuntimePlatform.Android)
            {
                runtimeUnsupportedReason = "link_unsupported";
            }
            _pcaRuntimeSupported = string.IsNullOrWhiteSpace(runtimeUnsupportedReason);
            _pcaPermissionGranted = HasRequiredCameraPermission(_cameraManager);
            RefreshProviderProofState();
        }

        private void RefreshProviderProofState()
        {
            _providerTypeName = string.Empty;
            _providerState = "missing";
            _providerStateReason = "provider_init_failed";
            _pcaProviderAvailable = false;
            _pcaProviderReady = false;

            if (_cameraManager == null)
            {
                return;
            }

            var subsystem = _cameraManager.subsystem;
            if (subsystem == null)
            {
                _providerState = "uninitialized";
                _providerStateReason = "provider_init_failed";
                return;
            }

            _providerTypeName = subsystem.GetType().Name;
            if (!TryQueryPassthroughCameraState(subsystem, out var providerState, out var providerReason, out var providerReady))
            {
                _providerState = subsystem.running ? "running_without_state_api" : "not_running";
                _providerStateReason = string.IsNullOrWhiteSpace(providerReason)
                    ? (subsystem.running ? "provider_state_unavailable" : "provider_not_started")
                    : providerReason;
                _pcaProviderAvailable = false;
                _pcaProviderReady = false;
                return;
            }

            _providerState = string.IsNullOrWhiteSpace(providerState) ? "unknown" : providerState;
            _providerStateReason = providerReady ? string.Empty : providerReason;
            _pcaProviderAvailable = true;
            _pcaProviderReady = providerReady;
        }

        private bool TryQueryPassthroughCameraState(
            XRCameraSubsystem subsystem,
            out string providerState,
            out string providerReason,
            out bool providerReady)
        {
            providerState = string.Empty;
            providerReason = "provider_state_unavailable";
            providerReady = false;

            var method = subsystem.GetType().GetMethod("GetPassthroughCameraState", BindingFlags.Instance | BindingFlags.Public);
            if (method == null)
            {
                return false;
            }

            object result;
            try
            {
                result = method.Invoke(subsystem, null);
            }
            catch (TargetInvocationException ex)
            {
                providerReason = MapProviderExceptionReason(ex.InnerException ?? ex);
                return false;
            }
            catch (Exception ex)
            {
                providerReason = MapProviderExceptionReason(ex);
                return false;
            }

            if (result == null)
            {
                providerReason = "provider_init_failed";
                return false;
            }

            var resultType = result.GetType();
            var statusObj = resultType.GetProperty("status", BindingFlags.Instance | BindingFlags.Public)?.GetValue(result);
            var valueObj = resultType.GetProperty("value", BindingFlags.Instance | BindingFlags.Public)?.GetValue(result);
            providerState = valueObj?.ToString() ?? string.Empty;

            if (!IsSuccessfulStatus(statusObj))
            {
                providerReason = MapProviderStateReason(providerState, statusObj);
                return false;
            }

            switch ((providerState ?? string.Empty).Trim().ToLowerInvariant())
            {
                case "ready":
                    providerReady = true;
                    providerReason = string.Empty;
                    return true;
                case "initialized":
                    providerReason = "provider_initializing";
                    return true;
                case "disabled":
                    providerReason = "provider_disabled";
                    return true;
                case "error":
                    providerReason = "provider_init_failed";
                    return true;
                default:
                    providerReason = string.IsNullOrWhiteSpace(providerState)
                        ? "provider_state_unavailable"
                        : "provider_state_unknown";
                    return true;
            }
        }

        private static bool IsSuccessfulStatus(object statusObj)
        {
            if (statusObj == null)
            {
                return false;
            }

            var statusType = statusObj.GetType();
            var isSuccessMethod = statusType.GetMethod("IsSuccess", BindingFlags.Instance | BindingFlags.Public);
            if (isSuccessMethod != null)
            {
                try
                {
                    if (isSuccessMethod.Invoke(statusObj, null) is bool success)
                    {
                        return success;
                    }
                }
                catch
                {
                    // Fall through to string heuristics below.
                }
            }

            var statusCodeObj = statusType.GetProperty("statusCode", BindingFlags.Instance | BindingFlags.Public)?.GetValue(statusObj);
            var statusText = string.Concat(statusCodeObj?.ToString() ?? string.Empty, "|", statusObj);
            var lowered = statusText.ToLowerInvariant();
            return !lowered.Contains("error")
                   && !lowered.Contains("unsupported")
                   && !lowered.Contains("uninitialized")
                   && !lowered.Contains("notstarted")
                   && !lowered.Contains("failure");
        }

        private static string MapProviderStateReason(string providerState, object statusObj)
        {
            var loweredState = (providerState ?? string.Empty).Trim().ToLowerInvariant();
            if (loweredState == "disabled")
            {
                return "provider_disabled";
            }

            if (loweredState == "initialized")
            {
                return "provider_initializing";
            }

            if (loweredState == "error")
            {
                return "provider_init_failed";
            }

            var statusText = statusObj?.GetType().GetProperty("statusCode", BindingFlags.Instance | BindingFlags.Public)?.GetValue(statusObj)?.ToString()
                ?? statusObj?.ToString()
                ?? string.Empty;
            var loweredStatus = statusText.Trim().ToLowerInvariant();
            if (loweredStatus.Contains("notstarted"))
            {
                return "provider_not_started";
            }

            if (loweredStatus.Contains("uninitialized"))
            {
                return "provider_init_failed";
            }

            if (loweredStatus.Contains("unsupported"))
            {
                return "provider_init_failed";
            }

            return "provider_init_failed";
        }

        private static string MapProviderExceptionReason(Exception ex)
        {
            if (ex == null)
            {
                return "provider_init_failed";
            }

            var lowered = ex.GetType().Name.ToLowerInvariant();
            if (lowered.Contains("notsupported"))
            {
                return "provider_init_failed";
            }

            if (lowered.Contains("dllnotfound") || lowered.Contains("entrypointnotfound"))
            {
                return "provider_init_failed";
            }

            return "provider_init_failed";
        }

        private static string ComposeFallbackReason(string rootReason, string fallbackSource, string secondaryReason = null)
        {
            var sourceSuffix = string.Equals(fallbackSource, CanonicalRenderTextureSourceName, StringComparison.OrdinalIgnoreCase)
                ? "using_rendertexture"
                : "using_ar_cpuimage";
            var primary = string.IsNullOrWhiteSpace(rootReason) ? string.Empty : rootReason.Trim().ToLowerInvariant();
            var secondary = string.IsNullOrWhiteSpace(secondaryReason) ? string.Empty : secondaryReason.Trim().ToLowerInvariant();
            if (string.IsNullOrWhiteSpace(primary))
            {
                primary = secondary;
            }
            if (string.IsNullOrWhiteSpace(primary) || string.Equals(primary, "ok", StringComparison.OrdinalIgnoreCase))
            {
                return sourceSuffix;
            }
            return primary + "_" + sourceSuffix;
        }

        private string ResolvePcaRootReason()
        {
            var runtimeReason = ResolveRuntimeUnsupportedReason(_runtimeName, _deviceModel);
            if (!string.IsNullOrWhiteSpace(runtimeReason))
            {
                return runtimeReason;
            }

            if (!_pcaDeviceSupported)
            {
                return "unsupported_device";
            }

            if (!_pcaPermissionGranted)
            {
                return "no_permission";
            }

            if (!_pcaProviderAvailable)
            {
                return string.IsNullOrWhiteSpace(_providerStateReason) ? "provider_init_failed" : _providerStateReason;
            }

            if (!_pcaProviderReady)
            {
                return string.IsNullOrWhiteSpace(_providerStateReason) ? "provider_init_failed" : _providerStateReason;
            }

            return string.Empty;
        }

        private void SetFailedArCpuImageState(string sourceMode, string rootReason, string failureReason)
        {
            if (string.Equals(sourceMode, CanonicalRealSourceName, StringComparison.OrdinalIgnoreCase))
            {
                SetUnavailable(failureReason);
                _activeProviderName = BuildProviderName("PcaReal");
                return;
            }

            SetSourceState(
                CanonicalFallbackSourceName,
                ComposeFallbackReason(rootReason, CanonicalFallbackSourceName, failureReason),
                CanonicalFallbackSourceName + ":" + failureReason,
                BuildProviderName("ARCpuImage"));
        }

        private void SetUnavailable(string reason)
        {
            SetSourceState(
                "unavailable",
                string.IsNullOrWhiteSpace(reason) ? "unavailable" : reason.Trim().ToLowerInvariant(),
                "unavailable:" + (string.IsNullOrWhiteSpace(reason) ? "unavailable" : reason.Trim().ToLowerInvariant()),
                string.IsNullOrWhiteSpace(_providerTypeName) ? SourceProviderName : BuildProviderName("Unavailable"));
        }

        private void SetSourceState(string sourceMode, string sourceReason, string status, string providerName)
        {
            _sourceMode = string.IsNullOrWhiteSpace(sourceMode) ? "unavailable" : sourceMode.Trim().ToLowerInvariant();
            _sourceReason = string.IsNullOrWhiteSpace(sourceReason) ? "unavailable" : sourceReason.Trim().ToLowerInvariant();
            _lastStatus = string.IsNullOrWhiteSpace(status) ? "unavailable:" + _sourceReason : status.Trim();
            _activeProviderName = string.IsNullOrWhiteSpace(providerName) ? SourceProviderName : providerName.Trim();
        }

        private string BuildProviderName(string capturePath)
        {
            if (string.IsNullOrWhiteSpace(capturePath))
            {
                return SourceProviderName;
            }

            var providerType = string.IsNullOrWhiteSpace(_providerTypeName) ? "UnknownProvider" : _providerTypeName.Trim();
            return SourceProviderName + "." + providerType + "." + capturePath.Trim();
        }

        private bool HasFullPcaProof()
        {
            return _pcaDeviceSupported
                   && _pcaRuntimeSupported
                   && _pcaPermissionGranted
                   && _pcaProviderAvailable
                   && _pcaProviderReady;
        }

        private static bool IsProviderWarmupReason(string reason)
        {
            var token = string.IsNullOrWhiteSpace(reason) ? string.Empty : reason.Trim().ToLowerInvariant();
            return token == "provider_initializing" || token == "provider_not_started";
        }

        private static string ResolveRuntimeUnsupportedReason(string runtimeName, string deviceModel)
        {
            if (Application.isEditor)
            {
                return "link_unsupported";
            }

            if (Application.platform != RuntimePlatform.Android)
            {
                return "link_unsupported";
            }

            if (RuntimeLooksSimulated(runtimeName, deviceModel))
            {
                return "simulator_unsupported";
            }

            return string.Empty;
        }

        private static bool RuntimeLooksSimulated(string runtimeName, string deviceModel)
        {
            var runtime = string.IsNullOrWhiteSpace(runtimeName) ? string.Empty : runtimeName.Trim().ToLowerInvariant();
            if (runtime.Contains("mock") || runtime.Contains("simulator") || runtime.Contains("simulation"))
            {
                return true;
            }

            var model = string.IsNullOrWhiteSpace(deviceModel) ? string.Empty : deviceModel.Trim().ToLowerInvariant();
            return model.Contains("simulator") || model.Contains("emulator") || model.Contains("mock runtime");
        }

        private static string ResolveOpenXrRuntimeName()
        {
            try
            {
                var runtimeType = Type.GetType(OpenXrRuntimeTypeName, throwOnError: false);
                var nameProperty = runtimeType?.GetProperty("name", BindingFlags.Public | BindingFlags.Static);
                var runtimeName = nameProperty?.GetValue(null) as string;
                return string.IsNullOrWhiteSpace(runtimeName) ? string.Empty : runtimeName.Trim();
            }
            catch
            {
                return string.Empty;
            }
        }

        private static bool HasRequiredCameraPermission(ARCameraManager cameraManager)
        {
            var arFoundationPermission = cameraManager != null && cameraManager.permissionGranted;
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                return arFoundationPermission
                       || UnityEngine.Android.Permission.HasUserAuthorizedPermission(UnityEngine.Android.Permission.Camera)
                       || UnityEngine.Android.Permission.HasUserAuthorizedPermission(AndroidSceneUnderstandingFinePermission)
                       || UnityEngine.Android.Permission.HasUserAuthorizedPermission(AndroidSceneUnderstandingCoarsePermission);
            }
            catch
            {
                return arFoundationPermission;
            }
#else
            return arFoundationPermission;
#endif
        }

        private static bool IsQuest3Family(string deviceModel)
        {
            var lowered = string.IsNullOrWhiteSpace(deviceModel) ? string.Empty : deviceModel.Trim().ToLowerInvariant();
            return lowered.Contains("quest 3s")
                   || lowered.Contains("quest3s")
                   || lowered.Contains("quest 3")
                   || lowered.Contains("quest3");
        }

        private static string ResolveDeviceModel()
        {
            var systemModel = string.IsNullOrWhiteSpace(SystemInfo.deviceModel) ? string.Empty : SystemInfo.deviceModel.Trim();
            if (!string.IsNullOrWhiteSpace(systemModel))
            {
                return systemModel;
            }

#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                using var buildClass = new AndroidJavaClass("android.os.Build");
                var model = buildClass.GetStatic<string>("MODEL");
                return string.IsNullOrWhiteSpace(model) ? "android" : model.Trim();
            }
            catch
            {
                return "android";
            }
#else
            return Application.isEditor ? "editor" : "unknown";
#endif
        }

        private void ResolveTargetSize(int sourceWidth, int sourceHeight, out int targetWidth, out int targetHeight)
        {
            targetWidth = sourceWidth;
            targetHeight = sourceHeight;

            var widthLimit = sourceWidth;
            var heightLimit = sourceHeight;

            if (requestedPcaWidth > 0)
            {
                widthLimit = Mathf.Min(widthLimit, requestedPcaWidth);
            }

            if (requestedPcaHeight > 0)
            {
                heightLimit = Mathf.Min(heightLimit, requestedPcaHeight);
            }

            if (maxWidth > 0)
            {
                widthLimit = Mathf.Min(widthLimit, maxWidth);
            }

            if (maxHeight > 0)
            {
                heightLimit = Mathf.Min(heightLimit, maxHeight);
            }

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
