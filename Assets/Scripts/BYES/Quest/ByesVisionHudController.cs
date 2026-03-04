using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using BeYourEyes.Adapters.Networking;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace BYES.Quest
{
    public sealed class ByesVisionHudController : MonoBehaviour
    {
        [SerializeField] private bool showDetOverlay = true;
        [SerializeField] private bool showSegOverlay = true;
        [SerializeField] private bool showDepthOverlay = true;
        [SerializeField] private bool showTargetOverlay = true;
        [SerializeField] private bool fullFovOverlayLayer = true;
        [SerializeField] private bool freezeOverlay = false;
        [SerializeField] private float detAlpha = 0.45f;
        [SerializeField] private float segAlpha = 0.35f;
        [SerializeField] private float depthAlpha = 0.30f;
        [SerializeField] private float hudDistance = 0.9f;
        [SerializeField] private float hudScale = 0.0018f;
        [SerializeField] private float fullFovCoverage = 1.0f;
        [SerializeField] private int maxBoxes = 8;

        private GatewayClient _gatewayClient;
        private Canvas _canvas;
        private RectTransform _overlayRoot;
        private RawImage _detImage;
        private RawImage _segImage;
        private RawImage _depthImage;
        private Text _statsText;
        private readonly List<Image> _boxOutlines = new List<Image>();
        private readonly List<Text> _boxLabels = new List<Text>();
        private ByesVisionHudRenderer _renderer;
        private Texture2D _segTexture;
        private Texture2D _depthTexture;
        private long _lastSegTsMs = -1;
        private long _lastDepthTsMs = -1;
        private long _lastDetTsMs = -1;
        private int _assetBytes;
        private float _lastDecodeMs;
        private float _overlayFps;
        private float _fpsLastTick;
        private int _fpsFrames;
        private bool _isInitialized;

        public bool ShowDetOverlay => showDetOverlay;
        public bool ShowSegOverlay => showSegOverlay;
        public bool ShowDepthOverlay => showDepthOverlay;
        public bool ShowTargetOverlay => showTargetOverlay;
        public bool FullFovOverlayLayer => fullFovOverlayLayer;
        public bool FreezeOverlay => freezeOverlay;
        public float DetAlpha => detAlpha;
        public float SegAlpha => segAlpha;
        public float DepthAlpha => depthAlpha;
        public float OverlayFps => _overlayFps;
        public float LastDecodeMs => _lastDecodeMs;
        public float LastFetchMs => _renderer != null ? _renderer.LastFetchMs : -1f;
        public int LastAssetBytes => _assetBytes;
        public string LastOverlayKind => _renderer != null ? _renderer.LastOverlayKind : "-";

        public long LastSegAgeMs
        {
            get
            {
                if (_lastSegTsMs <= 0)
                {
                    return -1;
                }
                return Math.Max(0, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _lastSegTsMs);
            }
        }

        public long LastDepthAgeMs
        {
            get
            {
                if (_lastDepthTsMs <= 0)
                {
                    return -1;
                }
                return Math.Max(0, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _lastDepthTsMs);
            }
        }

        public long LastDetAgeMs
        {
            get
            {
                if (_lastDetTsMs <= 0)
                {
                    return -1;
                }
                return Math.Max(0, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _lastDetTsMs);
            }
        }

        private void Awake()
        {
            EnsureHud();
            ResolveRefs();
            Bind();
            ApplyVisualState();
            UpdatePose(force: true);
        }

        private void OnEnable()
        {
            ResolveRefs();
            Bind();
        }

        private void OnDisable()
        {
            Unbind();
        }

        private void Update()
        {
            UpdatePose(force: false);
            UpdateStats();
        }

        public void SetShowDet(bool enabled)
        {
            showDetOverlay = enabled;
            ApplyVisualState();
        }

        public void SetShowSeg(bool enabled)
        {
            showSegOverlay = enabled;
            ApplyVisualState();
        }

        public void SetShowDepth(bool enabled)
        {
            showDepthOverlay = enabled;
            ApplyVisualState();
        }

        public void SetShowTarget(bool enabled)
        {
            showTargetOverlay = enabled;
            ApplyVisualState();
        }

        public void SetSegAlpha(float value)
        {
            segAlpha = Mathf.Clamp01(value);
            ApplyVisualState();
        }

        public void SetDetAlpha(float value)
        {
            detAlpha = Mathf.Clamp01(value);
            ApplyVisualState();
        }

        public void SetDepthAlpha(float value)
        {
            depthAlpha = Mathf.Clamp01(value);
            ApplyVisualState();
        }

        public void SetFreezeOverlay(bool enabled)
        {
            freezeOverlay = enabled;
            ApplyVisualState();
        }

        public void SetFullFovOverlayLayer(bool enabled)
        {
            fullFovOverlayLayer = enabled;
            UpdatePose(force: true);
        }

        public void ResetHud()
        {
            showDetOverlay = true;
            showSegOverlay = true;
            showDepthOverlay = true;
            showTargetOverlay = true;
            freezeOverlay = false;
            detAlpha = 0.45f;
            segAlpha = 0.35f;
            depthAlpha = 0.30f;
            ApplyVisualState();
        }

        private void EnsureHud()
        {
            if (_isInitialized)
            {
                return;
            }

            var root = new GameObject("BYES_VisionHUD", typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            root.transform.SetParent(transform, false);
            _canvas = root.GetComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.sortingOrder = 6100;
            var canvasRect = root.GetComponent<RectTransform>();
            canvasRect.sizeDelta = new Vector2(960f, 540f);
            canvasRect.localScale = Vector3.one * hudScale;

            _overlayRoot = canvasRect;

            var detGo = CreateUiObject("DetOverlay", root.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(960f, 540f), Vector2.zero);
            _detImage = detGo.AddComponent<RawImage>();
            _detImage.color = new Color(1f, 1f, 1f, detAlpha);
            _detImage.raycastTarget = false;

            var depthGo = CreateUiObject("DepthOverlay", root.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(960f, 540f), Vector2.zero);
            _depthImage = depthGo.AddComponent<RawImage>();
            _depthImage.color = new Color(1f, 1f, 1f, depthAlpha);
            _depthImage.raycastTarget = false;

            var segGo = CreateUiObject("SegOverlay", root.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(960f, 540f), Vector2.zero);
            _segImage = segGo.AddComponent<RawImage>();
            _segImage.color = new Color(1f, 0.2f, 0.2f, segAlpha);
            _segImage.raycastTarget = false;

            for (var i = 0; i < Mathf.Max(1, maxBoxes); i += 1)
            {
                var boxGo = CreateUiObject($"Box_{i}", root.transform, new Vector2(0.5f, 0.5f), new Vector2(0.5f, 0.5f), new Vector2(100f, 100f), Vector2.zero);
                var image = boxGo.AddComponent<Image>();
                image.color = new Color(0.1f, 1f, 0.2f, 0.95f);
                image.raycastTarget = false;
                _boxOutlines.Add(image);

                var label = CreateText($"BoxLabel_{i}", boxGo.transform, "-", 20, TextAnchor.UpperLeft, new Vector2(0f, 1f), new Vector2(20f, 12f), new Vector2(240f, 48f));
                label.raycastTarget = false;
                _boxLabels.Add(label);
            }

            _statsText = CreateText("Stats", root.transform, "HUD idle", 20, TextAnchor.UpperLeft, new Vector2(0f, 1f), new Vector2(16f, -12f), new Vector2(760f, 82f));
            _statsText.raycastTarget = false;

            _isInitialized = true;
            EnsureRenderer();
        }

        private void ResolveRefs()
        {
            _gatewayClient ??= FindFirstObjectByType<GatewayClient>();
            if (_canvas != null && _canvas.worldCamera == null)
            {
                _canvas.worldCamera = ResolveWorldCamera();
            }
        }

        private void Bind()
        {
            if (_gatewayClient == null)
            {
                return;
            }
            EnsureRenderer();
            _renderer?.Bind(_gatewayClient);
        }

        private void Unbind()
        {
            _renderer?.Unbind();
        }

        private void HandleGatewayEvent(JObject evt)
        {
            if (evt == null)
            {
                return;
            }

            var name = (evt.Value<string>("name") ?? evt.Value<string>("type") ?? string.Empty).Trim();
            if (string.IsNullOrWhiteSpace(name))
            {
                return;
            }

            var payload = evt["payload"] as JObject;
            if (payload == null)
            {
                return;
            }

            switch (name)
            {
                case "seg.mask.v1":
                    if (showSegOverlay)
                    {
                        var segAssetId = (payload.Value<string>("assetId") ?? string.Empty).Trim();
                        if (!string.IsNullOrWhiteSpace(segAssetId))
                        {
                            StartCoroutine(DownloadAsset(segAssetId, applyToSeg: true));
                        }
                        _lastSegTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    }
                    break;
                case "depth.map.v1":
                    if (showDepthOverlay)
                    {
                        var depthAssetId = (payload.Value<string>("assetId") ?? string.Empty).Trim();
                        if (!string.IsNullOrWhiteSpace(depthAssetId))
                        {
                            StartCoroutine(DownloadAsset(depthAssetId, applyToSeg: false));
                        }
                        _lastDepthTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    }
                    break;
                case "det.objects.v1":
                case "det.objects":
                    _lastDetTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    if (showDetOverlay)
                    {
                        UpdateDetOverlay(payload);
                    }
                    break;
                case "target.update":
                    if (showTargetOverlay && showDetOverlay)
                    {
                        UpdateDetOverlay(payload);
                    }
                    break;
            }
        }

        private IEnumerator DownloadAsset(string assetId, bool applyToSeg)
        {
            if (_gatewayClient == null)
            {
                yield break;
            }
            var baseUrl = _gatewayClient.BaseUrl.TrimEnd('/');
            var url = $"{baseUrl}/api/assets/{UnityWebRequest.EscapeURL(assetId)}";
            var started = Time.realtimeSinceStartup;
            using (var request = UnityWebRequestTexture.GetTexture(url, true))
            {
                request.timeout = 6;
                var apiKey = _gatewayClient.ApiKey;
                if (!string.IsNullOrWhiteSpace(apiKey))
                {
                    request.SetRequestHeader("X-BYES-API-Key", apiKey.Trim());
                }
                yield return request.SendWebRequest();
                _lastDecodeMs = Mathf.Max(0f, (Time.realtimeSinceStartup - started) * 1000f);
                if (request.result != UnityWebRequest.Result.Success)
                {
                    yield break;
                }

                var texture = DownloadHandlerTexture.GetContent(request);
                if (texture == null)
                {
                    yield break;
                }

                _assetBytes = request.downloadHandler != null && request.downloadHandler.data != null
                    ? request.downloadHandler.data.Length
                    : 0;

                if (applyToSeg)
                {
                    _segTexture = texture;
                    _segImage.texture = _segTexture;
                }
                else
                {
                    _depthTexture = texture;
                    _depthImage.texture = _depthTexture;
                }
            }
        }

        private void UpdateDetOverlay(JObject payload)
        {
            var objects = payload["objects"] as JArray;
            var imageWidth = Mathf.Max(1f, payload.Value<float?>("imageWidth") ?? 1f);
            var imageHeight = Mathf.Max(1f, payload.Value<float?>("imageHeight") ?? 1f);

            for (var i = 0; i < _boxOutlines.Count; i += 1)
            {
                _boxOutlines[i].enabled = false;
                _boxLabels[i].enabled = false;
            }

            if (objects == null)
            {
                return;
            }

            var idx = 0;
            foreach (var token in objects)
            {
                if (idx >= _boxOutlines.Count)
                {
                    break;
                }
                if (token is not JObject obj)
                {
                    continue;
                }

                JArray boxNorm = obj["box_norm"] as JArray;
                JArray boxPx = obj["box_xyxy"] as JArray;
                float x0, y0, x1, y1;
                if (boxNorm != null && boxNorm.Count == 4)
                {
                    x0 = Mathf.Clamp01(boxNorm[0]?.Value<float>() ?? 0f);
                    y0 = Mathf.Clamp01(boxNorm[1]?.Value<float>() ?? 0f);
                    x1 = Mathf.Clamp01(boxNorm[2]?.Value<float>() ?? 0f);
                    y1 = Mathf.Clamp01(boxNorm[3]?.Value<float>() ?? 0f);
                }
                else if (boxPx != null && boxPx.Count == 4)
                {
                    x0 = Mathf.Clamp01((boxPx[0]?.Value<float>() ?? 0f) / imageWidth);
                    y0 = Mathf.Clamp01((boxPx[1]?.Value<float>() ?? 0f) / imageHeight);
                    x1 = Mathf.Clamp01((boxPx[2]?.Value<float>() ?? imageWidth) / imageWidth);
                    y1 = Mathf.Clamp01((boxPx[3]?.Value<float>() ?? imageHeight) / imageHeight);
                }
                else
                {
                    continue;
                }

                if (x1 < x0)
                {
                    var t = x0;
                    x0 = x1;
                    x1 = t;
                }
                if (y1 < y0)
                {
                    var t = y0;
                    y0 = y1;
                    y1 = t;
                }

                var rect = _boxOutlines[idx].rectTransform;
                var overlayW = 960f;
                var overlayH = 540f;
                var w = Mathf.Max(2f, (x1 - x0) * overlayW);
                var h = Mathf.Max(2f, (y1 - y0) * overlayH);
                rect.sizeDelta = new Vector2(w, h);
                rect.anchoredPosition = new Vector2(
                    -overlayW * 0.5f + (x0 + x1) * 0.5f * overlayW,
                    overlayH * 0.5f - (y0 + y1) * 0.5f * overlayH);
                _boxOutlines[idx].enabled = true;

                var label = (obj.Value<string>("label") ?? "obj").Trim();
                var trackId = (obj.Value<string>("trackId") ?? string.Empty).Trim();
                var conf = obj.Value<float?>("conf") ?? 0f;
                _boxLabels[idx].text = string.IsNullOrWhiteSpace(trackId)
                    ? $"{label} {conf:0.00}"
                    : $"{label}#{trackId} {conf:0.00}";
                _boxLabels[idx].enabled = true;
                idx += 1;
            }
        }

        private void ApplyVisualState()
        {
            EnsureRenderer();
            _renderer?.SetVisualState(showDetOverlay, showSegOverlay, showDepthOverlay, detAlpha, segAlpha, depthAlpha);
            _renderer?.SetFreezeOverlay(freezeOverlay);
        }

        private void UpdatePose(bool force)
        {
            if (_overlayRoot == null)
            {
                return;
            }
            var cam = ResolveWorldCamera();
            if (cam == null)
            {
                return;
            }
            if (_canvas != null)
            {
                _canvas.worldCamera = cam;
            }

            if (fullFovOverlayLayer)
            {
                var targetPos = cam.transform.position + cam.transform.forward * hudDistance;
                _overlayRoot.position = targetPos;
                _overlayRoot.rotation = cam.transform.rotation;

                var fov = Mathf.Clamp(cam.fieldOfView, 20f, 140f) * Mathf.Deg2Rad;
                var worldH = 2f * Mathf.Max(0.05f, hudDistance) * Mathf.Tan(fov * 0.5f) * Mathf.Clamp(fullFovCoverage, 0.6f, 1.2f);
                var worldW = worldH * Mathf.Max(0.5f, cam.aspect);
                var targetScale = new Vector3(worldW / 960f, worldH / 540f, 1f);
                if (force)
                {
                    _overlayRoot.localScale = targetScale;
                }
                else
                {
                    _overlayRoot.localScale = Vector3.Lerp(_overlayRoot.localScale, targetScale, Time.unscaledDeltaTime * 10f);
                }
                return;
            }

            var relaxedPos = cam.transform.position + cam.transform.forward * hudDistance;
            _overlayRoot.position = Vector3.Lerp(_overlayRoot.position, relaxedPos, Time.unscaledDeltaTime * 10f);
            var toCam = cam.transform.position - _overlayRoot.position;
            if (toCam.sqrMagnitude > 0.0001f)
            {
                var rot = Quaternion.LookRotation(toCam.normalized, cam.transform.up);
                _overlayRoot.rotation = Quaternion.Slerp(_overlayRoot.rotation, rot, Time.unscaledDeltaTime * 12f);
            }
        }

        private void UpdateStats()
        {
            if (_statsText == null)
            {
                return;
            }
            EnsureRenderer();
            if (_renderer != null)
            {
                _overlayFps = _renderer.OverlayFps;
                _lastDecodeMs = _renderer.LastDecodeMs;
                _assetBytes = _renderer.LastAssetBytes;
                _lastSegTsMs = _renderer.LastSegTsMs;
                _lastDepthTsMs = _renderer.LastDepthTsMs;
                _lastDetTsMs = _renderer.LastDetTsMs;
            }
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            var segAge = _lastSegTsMs > 0 ? Math.Max(0, now - _lastSegTsMs) : -1;
            var depthAge = _lastDepthTsMs > 0 ? Math.Max(0, now - _lastDepthTsMs) : -1;
            var detAge = _lastDetTsMs > 0 ? Math.Max(0, now - _lastDetTsMs) : -1;
            var kind = _renderer != null ? _renderer.LastOverlayKind : "-";
            var fetchMs = _renderer != null ? _renderer.LastFetchMs : -1f;
            _statsText.text = $"HUD fps:{_overlayFps:0.0} kind:{kind} fetch:{fetchMs:0.0}ms decode:{_lastDecodeMs:0.0}ms bytes:{_assetBytes}\n" +
                              $"segAge:{(segAge >= 0 ? segAge + "ms" : "-")} depthAge:{(depthAge >= 0 ? depthAge + "ms" : "-")} detAge:{(detAge >= 0 ? detAge + "ms" : "-")}";
        }

        private void EnsureRenderer()
        {
            if (_renderer == null)
            {
                _renderer = GetComponent<ByesVisionHudRenderer>();
                if (_renderer == null)
                {
                    _renderer = gameObject.AddComponent<ByesVisionHudRenderer>();
                }
            }
            _renderer?.Initialize(_detImage, _segImage, _depthImage, _boxOutlines, _boxLabels, 960f, 540f);
        }

        private void TickOverlayFps()
        {
            _fpsFrames += 1;
            var now = Time.unscaledTime;
            if (_fpsLastTick <= 0f)
            {
                _fpsLastTick = now;
                return;
            }
            var delta = now - _fpsLastTick;
            if (delta >= 0.5f)
            {
                _overlayFps = _fpsFrames / delta;
                _fpsFrames = 0;
                _fpsLastTick = now;
            }
        }

        private static GameObject CreateUiObject(string name, Transform parent, Vector2 anchorMin, Vector2 anchorMax, Vector2 size, Vector2 anchoredPos)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            var rect = go.GetComponent<RectTransform>();
            rect.anchorMin = anchorMin;
            rect.anchorMax = anchorMax;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.sizeDelta = size;
            rect.anchoredPosition = anchoredPos;
            return go;
        }

        private static Text CreateText(string name, Transform parent, string value, int size, TextAnchor align, Vector2 anchor, Vector2 pos, Vector2 dim)
        {
            var go = CreateUiObject(name, parent, anchor, anchor, dim, pos);
            var text = go.AddComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.color = Color.white;
            text.alignment = align;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Truncate;
            text.fontSize = size;
            text.text = value;
            return text;
        }

        private static Camera ResolveWorldCamera()
        {
            if (Camera.main != null && Camera.main.isActiveAndEnabled)
            {
                return Camera.main;
            }
            var cameras = Camera.allCameras;
            for (var i = 0; i < cameras.Length; i += 1)
            {
                if (cameras[i] != null && cameras[i].isActiveAndEnabled)
                {
                    return cameras[i];
                }
            }
            return null;
        }
    }
}
