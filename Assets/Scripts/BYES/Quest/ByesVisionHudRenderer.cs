using System;
using System.Collections;
using System.Collections.Generic;
using BeYourEyes.Adapters.Networking;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

namespace BYES.Quest
{
    public sealed class ByesVisionHudRenderer : MonoBehaviour
    {
        private GatewayClient _gatewayClient;
        private RawImage _detImage;
        private RawImage _segImage;
        private RawImage _depthImage;
        private List<Image> _boxOutlines;
        private List<Text> _boxLabels;
        private float _overlayWidth = 960f;
        private float _overlayHeight = 540f;
        private bool _showDet = true;
        private bool _showSeg = true;
        private bool _showDepth = true;
        private float _detAlpha = 0.45f;
        private float _segAlpha = 0.35f;
        private float _depthAlpha = 0.30f;
        private bool _freezeOverlay;
        private bool _bound;
        private int _overlayUpdates;
        private float _fpsTickStart;
        private readonly Dictionary<string, string> _pendingOverlayAssets = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, string> _appliedOverlayAssets = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, long> _pendingOverlayFrameSeq = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, long> _appliedOverlayFrameSeq = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, long> _latestOverlayFrameSeq = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, long> _pendingOverlayTsMs = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, Texture> _overlayTextureCache = new Dictionary<string, Texture>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, string> _failedOverlayAssets = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, bool> _overlayAvailability = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
        private readonly Dictionary<string, string> _overlayReasons = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        private readonly HashSet<string> _overlayFetchInFlight = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        public float OverlayFps { get; private set; }
        public float LastDecodeMs { get; private set; }
        public float LastFetchMs { get; private set; }
        public int LastAssetBytes { get; private set; }
        public long LastSegTsMs { get; private set; } = -1;
        public long LastDepthTsMs { get; private set; } = -1;
        public long LastDetTsMs { get; private set; } = -1;
        public string LastOverlayKind { get; private set; } = "-";
        public bool FreezeOverlay => _freezeOverlay;
        public bool IsOverlayAvailable(string applyMode) => _overlayAvailability.TryGetValue(applyMode ?? string.Empty, out var available) && available;
        public string GetOverlayReason(string applyMode) => _overlayReasons.TryGetValue(applyMode ?? string.Empty, out var reason) ? reason : "unavailable";
        public string GetAppliedOverlayAssetId(string applyMode) => _appliedOverlayAssets.TryGetValue(applyMode ?? string.Empty, out var assetId) ? assetId : null;

        public void Initialize(
            RawImage detImage,
            RawImage segImage,
            RawImage depthImage,
            List<Image> boxOutlines,
            List<Text> boxLabels,
            float overlayWidth = 960f,
            float overlayHeight = 540f)
        {
            _detImage = detImage;
            _segImage = segImage;
            _depthImage = depthImage;
            _boxOutlines = boxOutlines ?? new List<Image>();
            _boxLabels = boxLabels ?? new List<Text>();
            _overlayWidth = Mathf.Max(2f, overlayWidth);
            _overlayHeight = Mathf.Max(2f, overlayHeight);
            ApplyVisualState();
        }

        public void Bind(GatewayClient gatewayClient)
        {
            if (gatewayClient == null || _bound)
            {
                return;
            }
            _gatewayClient = gatewayClient;
            _gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            _gatewayClient.OnGatewayEvent += HandleGatewayEvent;
            _bound = true;
        }

        public void Unbind()
        {
            if (!_bound || _gatewayClient == null)
            {
                _bound = false;
                return;
            }
            _gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            _bound = false;
        }

        public void SetVisualState(bool showDet, bool showSeg, bool showDepth, float detAlpha, float segAlpha, float depthAlpha)
        {
            _showDet = showDet;
            _showSeg = showSeg;
            _showDepth = showDepth;
            _detAlpha = Mathf.Clamp01(detAlpha);
            _segAlpha = Mathf.Clamp01(segAlpha);
            _depthAlpha = Mathf.Clamp01(depthAlpha);
            ApplyVisualState();
        }

        public void SetFreezeOverlay(bool freezeOverlay)
        {
            _freezeOverlay = freezeOverlay;
        }

        public void SetOverlayUnavailable(string applyMode, string reason, bool clearTexture)
        {
            var normalizedMode = NormalizeApplyMode(applyMode);
            if (string.IsNullOrWhiteSpace(normalizedMode))
            {
                return;
            }

            var normalizedReason = string.IsNullOrWhiteSpace(reason) ? "unavailable" : reason.Trim().ToLowerInvariant();
            if (clearTexture)
            {
                ClearOverlayTexture(normalizedMode);
                _appliedOverlayAssets.Remove(normalizedMode);
                _overlayAvailability[normalizedMode] = false;
                _overlayReasons[normalizedMode] = normalizedReason;
            }
            else
            {
                _overlayAvailability[normalizedMode] = HasValidTexture(normalizedMode);
                _overlayReasons[normalizedMode] = _overlayAvailability[normalizedMode]
                    ? "stale_hold:" + normalizedReason
                    : normalizedReason;
            }

            RefreshLayerVisibility(normalizedMode);
        }

        public void ClearOverlay(string applyMode, string reason = "cleared")
        {
            SetOverlayUnavailable(applyMode, reason, clearTexture: true);
        }

        private void OnDisable()
        {
            Unbind();
        }

        private void Update()
        {
            var now = Time.unscaledTime;
            if (_fpsTickStart <= 0f)
            {
                _fpsTickStart = now;
                _overlayUpdates = 0;
                return;
            }

            var dt = now - _fpsTickStart;
            if (dt >= 0.5f)
            {
                OverlayFps = _overlayUpdates / Mathf.Max(0.0001f, dt);
                _overlayUpdates = 0;
                _fpsTickStart = now;
            }
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
            var eventFrameSeq = ReadFrameSeq(evt, payload);
            var eventTsMs = ReadEventTsMs(evt, payload);

            if (_freezeOverlay && (
                    string.Equals(name, "vis.overlay.v1", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(name, "seg.mask.v1", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(name, "depth.map.v1", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(name, "det.objects.v1", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(name, "det.objects", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(name, "target.update", StringComparison.OrdinalIgnoreCase)))
            {
                return;
            }

            switch (name)
            {
                case "vis.overlay.v1":
                    HandleOverlayEvent(payload, eventFrameSeq, eventTsMs);
                    break;
                case "seg.mask.v1":
                    if (_showSeg)
                    {
                        var segAssetId = NormalizeAssetId(payload.Value<string>("assetId"));
                        if (!string.IsNullOrWhiteSpace(segAssetId))
                        {
                            RequestOverlayAsset(segAssetId, applyMode: "seg", frameSeq: eventFrameSeq, eventTsMs: eventTsMs);
                        }
                        UpdateOverlayTimestamp("seg", eventTsMs);
                    }
                    break;
                case "depth.map.v1":
                    if (_showDepth)
                    {
                        var depthAssetId = NormalizeAssetId(payload.Value<string>("assetId"));
                        if (!string.IsNullOrWhiteSpace(depthAssetId))
                        {
                            RequestOverlayAsset(depthAssetId, applyMode: "depth", frameSeq: eventFrameSeq, eventTsMs: eventTsMs);
                        }
                        UpdateOverlayTimestamp("depth", eventTsMs);
                    }
                    break;
                case "det.objects.v1":
                case "det.objects":
                    UpdateOverlayTimestamp("det", eventTsMs);
                    if (_showDet)
                    {
                        UpdateDetOverlay(payload);
                    }
                    break;
                case "target.update":
                    if (_showDet)
                    {
                        UpdateDetOverlay(payload);
                    }
                    break;
            }
        }

        private void HandleOverlayEvent(JObject payload, long frameSeq, long eventTsMs)
        {
            if (payload == null)
            {
                return;
            }
            var kind = (payload.Value<string>("kind") ?? string.Empty).Trim().ToLowerInvariant();
            var assetId = NormalizeAssetId(payload.Value<string>("assetId"));
            if (string.IsNullOrWhiteSpace(assetId))
            {
                return;
            }
            LastOverlayKind = string.IsNullOrWhiteSpace(kind) ? "-" : kind;

            if (kind == "det")
            {
                if (_showDet)
                {
                    RequestOverlayAsset(assetId, applyMode: "det", frameSeq: frameSeq, eventTsMs: eventTsMs);
                }
                UpdateOverlayTimestamp("det", eventTsMs);
                return;
            }

            if (kind == "seg")
            {
                if (_showSeg)
                {
                    RequestOverlayAsset(assetId, applyMode: "seg", frameSeq: frameSeq, eventTsMs: eventTsMs);
                }
                UpdateOverlayTimestamp("seg", eventTsMs);
                return;
            }

            if (kind == "depth")
            {
                if (_showDepth)
                {
                    RequestOverlayAsset(assetId, applyMode: "depth", frameSeq: frameSeq, eventTsMs: eventTsMs);
                }
                UpdateOverlayTimestamp("depth", eventTsMs);
                return;
            }

            if (kind == "combo")
            {
                if (_showDet)
                {
                    RequestOverlayAsset(assetId, applyMode: "det", frameSeq: frameSeq, eventTsMs: eventTsMs);
                }
                if (_showSeg)
                {
                    RequestOverlayAsset(assetId, applyMode: "seg", frameSeq: frameSeq, eventTsMs: eventTsMs);
                }
                UpdateOverlayTimestamp("det", eventTsMs);
                UpdateOverlayTimestamp("seg", eventTsMs);
            }
        }

        private void RequestOverlayAsset(string assetId, string applyMode, long frameSeq, long eventTsMs)
        {
            var normalizedAssetId = NormalizeAssetId(assetId);
            var normalizedMode = NormalizeApplyMode(applyMode);
            if (string.IsNullOrWhiteSpace(normalizedAssetId) || string.IsNullOrWhiteSpace(normalizedMode))
            {
                return;
            }
            if (IsStaleOverlayFrame(normalizedMode, frameSeq))
            {
                return;
            }
            RememberOverlayFrameSeq(normalizedMode, frameSeq);

            if (_overlayTextureCache.TryGetValue(normalizedAssetId, out var cachedTexture) && cachedTexture != null)
            {
                ApplyOverlayTexture(normalizedMode, cachedTexture);
                _appliedOverlayAssets[normalizedMode] = normalizedAssetId;
                if (frameSeq > 0)
                {
                    _appliedOverlayFrameSeq[normalizedMode] = frameSeq;
                }
                _overlayAvailability[normalizedMode] = true;
                _overlayReasons[normalizedMode] = "ok";
                UpdateOverlayTimestamp(normalizedMode, eventTsMs);
                _overlayUpdates += 1;
                return;
            }

            if (_appliedOverlayAssets.TryGetValue(normalizedMode, out var appliedAssetId)
                && string.Equals(appliedAssetId, normalizedAssetId, StringComparison.OrdinalIgnoreCase)
                && !_overlayFetchInFlight.Contains(normalizedMode))
            {
                return;
            }

            if (_failedOverlayAssets.TryGetValue(normalizedAssetId, out var failedReason)
                && !_overlayFetchInFlight.Contains(normalizedMode))
            {
                _overlayAvailability[normalizedMode] = HasValidTexture(normalizedMode);
                _overlayReasons[normalizedMode] = _overlayAvailability[normalizedMode] ? "stale_hold:" + failedReason : failedReason;
                RefreshLayerVisibility(normalizedMode);
                return;
            }

            _pendingOverlayAssets[normalizedMode] = normalizedAssetId;
            _pendingOverlayFrameSeq[normalizedMode] = frameSeq;
            _pendingOverlayTsMs[normalizedMode] = eventTsMs;
            if (_overlayFetchInFlight.Contains(normalizedMode))
            {
                return;
            }

            StartCoroutine(DrainOverlayAssetQueue(normalizedMode));
        }

        private IEnumerator DrainOverlayAssetQueue(string applyMode)
        {
            if (!_overlayFetchInFlight.Add(applyMode))
            {
                yield break;
            }

            try
            {
                while (true)
                {
                    if (!_pendingOverlayAssets.TryGetValue(applyMode, out var assetId) || string.IsNullOrWhiteSpace(assetId))
                    {
                        yield break;
                    }

                    _pendingOverlayAssets.Remove(applyMode);
                    _pendingOverlayFrameSeq.TryGetValue(applyMode, out var pendingFrameSeq);
                    _pendingOverlayFrameSeq.Remove(applyMode);
                    _pendingOverlayTsMs.TryGetValue(applyMode, out var pendingTsMs);
                    _pendingOverlayTsMs.Remove(applyMode);
                    Texture texture = null;
                    var bytes = 0;
                    var elapsedMs = 0f;
                    string fetchReason = null;
                    yield return DownloadAssetInternal(assetId, (downloaded, fetchMs, assetBytes, reason) =>
                    {
                        texture = downloaded;
                        elapsedMs = fetchMs;
                        bytes = assetBytes;
                        fetchReason = reason;
                    });

                    if (_pendingOverlayAssets.TryGetValue(applyMode, out var newerAssetId)
                        && !string.IsNullOrWhiteSpace(newerAssetId)
                        && !string.Equals(newerAssetId, assetId, StringComparison.Ordinal))
                    {
                        continue;
                    }
                    if (IsStaleOverlayFrame(applyMode, pendingFrameSeq))
                    {
                        continue;
                    }

                    LastFetchMs = elapsedMs;
                    LastDecodeMs = elapsedMs;
                    if (texture == null)
                    {
                        _failedOverlayAssets[assetId] = string.IsNullOrWhiteSpace(fetchReason) ? "asset_fetch_failed" : fetchReason;
                        _overlayAvailability[applyMode] = HasValidTexture(applyMode);
                        _overlayReasons[applyMode] = _overlayAvailability[applyMode]
                            ? "stale_hold:" + _failedOverlayAssets[assetId]
                            : _failedOverlayAssets[assetId];
                        RefreshLayerVisibility(applyMode);
                        continue;
                    }

                    LastAssetBytes = bytes;
                    _overlayTextureCache[assetId] = texture;
                    _failedOverlayAssets.Remove(assetId);
                    ApplyOverlayTexture(applyMode, texture);
                    _appliedOverlayAssets[applyMode] = assetId;
                    if (pendingFrameSeq > 0)
                    {
                        _appliedOverlayFrameSeq[applyMode] = pendingFrameSeq;
                    }
                    _overlayAvailability[applyMode] = true;
                    _overlayReasons[applyMode] = "ok";
                    UpdateOverlayTimestamp(applyMode, pendingTsMs);
                    _overlayUpdates += 1;
                }
            }
            finally
            {
                _overlayFetchInFlight.Remove(applyMode);
            }
        }

        private IEnumerator DownloadAssetInternal(string assetId, Action<Texture, float, int, string> onDone)
        {
            if (_gatewayClient == null)
            {
                onDone?.Invoke(null, 0f, 0, "gateway_unavailable");
                yield break;
            }

            var normalizedAssetId = NormalizeAssetId(assetId);
            if (string.IsNullOrWhiteSpace(normalizedAssetId))
            {
                onDone?.Invoke(null, 0f, 0, "asset_id_missing");
                yield break;
            }

            var baseUrl = (_gatewayClient.BaseUrl ?? string.Empty).TrimEnd('/');
            var url = $"{baseUrl}/api/assets/{UnityWebRequest.EscapeURL(normalizedAssetId)}";
            var started = Time.realtimeSinceStartup;
            using var request = UnityWebRequestTexture.GetTexture(url, true);
            request.timeout = 6;
            var apiKey = _gatewayClient.ApiKey;
            if (!string.IsNullOrWhiteSpace(apiKey))
            {
                request.SetRequestHeader("X-BYES-API-Key", apiKey.Trim());
            }
            yield return request.SendWebRequest();
            var elapsedMs = Mathf.Max(0f, (Time.realtimeSinceStartup - started) * 1000f);
            if (request.result != UnityWebRequest.Result.Success)
            {
                var reason = request.responseCode > 0
                    ? $"http_{request.responseCode}"
                    : (string.IsNullOrWhiteSpace(request.error) ? "asset_fetch_failed" : request.error.Trim().Replace(' ', '_').ToLowerInvariant());
                onDone?.Invoke(null, elapsedMs, 0, reason);
                yield break;
            }

            var texture = DownloadHandlerTexture.GetContent(request);
            var bytes = request.downloadHandler?.data != null ? request.downloadHandler.data.Length : 0;
            onDone?.Invoke(texture, elapsedMs, bytes, "ok");
        }

        private void ApplyOverlayTexture(string applyMode, Texture texture)
        {
            if (string.Equals(applyMode, "det", StringComparison.OrdinalIgnoreCase))
            {
                if (_detImage != null)
                {
                    _detImage.texture = texture;
                    RefreshLayerVisibility("det");
                }
                return;
            }

            if (string.Equals(applyMode, "seg", StringComparison.OrdinalIgnoreCase))
            {
                if (_segImage != null)
                {
                    _segImage.texture = texture;
                    RefreshLayerVisibility("seg");
                }
                return;
            }

            if (_depthImage != null)
            {
                _depthImage.texture = texture;
                RefreshLayerVisibility("depth");
            }
        }

        private void ClearOverlayTexture(string applyMode)
        {
            if (string.Equals(applyMode, "det", StringComparison.OrdinalIgnoreCase))
            {
                if (_detImage != null)
                {
                    _detImage.texture = null;
                }
                ClearDetBoxes();
                return;
            }

            if (string.Equals(applyMode, "seg", StringComparison.OrdinalIgnoreCase))
            {
                if (_segImage != null)
                {
                    _segImage.texture = null;
                }
                return;
            }

            if (_depthImage != null)
            {
                _depthImage.texture = null;
            }
        }

        private bool HasValidTexture(string applyMode)
        {
            if (string.Equals(applyMode, "det", StringComparison.OrdinalIgnoreCase))
            {
                return _detImage != null && _detImage.texture != null;
            }

            if (string.Equals(applyMode, "seg", StringComparison.OrdinalIgnoreCase))
            {
                return _segImage != null && _segImage.texture != null;
            }

            return _depthImage != null && _depthImage.texture != null;
        }

        private void RefreshLayerVisibility(string applyMode)
        {
            if (string.Equals(applyMode, "det", StringComparison.OrdinalIgnoreCase))
            {
                if (_detImage != null)
                {
                    _detImage.enabled = _showDet && _detImage.texture != null && _detAlpha > 0.001f;
                }
                return;
            }

            if (string.Equals(applyMode, "seg", StringComparison.OrdinalIgnoreCase))
            {
                if (_segImage != null)
                {
                    _segImage.enabled = _showSeg && _segImage.texture != null && _segAlpha > 0.001f;
                }
                return;
            }

            if (_depthImage != null)
            {
                _depthImage.enabled = _showDepth && _depthImage.texture != null && _depthAlpha > 0.001f;
            }
        }

        private void UpdateDetOverlay(JObject payload)
        {
            if (_boxOutlines == null || _boxLabels == null)
            {
                return;
            }

            ClearDetBoxes();
            var objects = payload["objects"] as JArray;
            var imageWidth = Mathf.Max(1f, payload.Value<float?>("imageWidth") ?? 1f);
            var imageHeight = Mathf.Max(1f, payload.Value<float?>("imageHeight") ?? 1f);

            if (objects == null)
            {
                return;
            }

            var idx = 0;
            foreach (var token in objects)
            {
                if (idx >= _boxOutlines.Count || idx >= _boxLabels.Count)
                {
                    break;
                }
                if (token is not JObject obj)
                {
                    continue;
                }

                JArray boxNorm = obj["box_norm"] as JArray;
                JArray boxPx = obj["box_xyxy"] as JArray;
                float x0;
                float y0;
                float x1;
                float y1;
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
                    (x0, x1) = (x1, x0);
                }
                if (y1 < y0)
                {
                    (y0, y1) = (y1, y0);
                }

                var outline = _boxOutlines[idx];
                var labelText = _boxLabels[idx];
                if (outline == null || labelText == null)
                {
                    idx += 1;
                    continue;
                }
                var rect = outline.rectTransform;
                var w = Mathf.Max(2f, (x1 - x0) * _overlayWidth);
                var h = Mathf.Max(2f, (y1 - y0) * _overlayHeight);
                rect.sizeDelta = new Vector2(w, h);
                rect.anchoredPosition = new Vector2(
                    -_overlayWidth * 0.5f + (x0 + x1) * 0.5f * _overlayWidth,
                    _overlayHeight * 0.5f - (y0 + y1) * 0.5f * _overlayHeight);
                outline.enabled = _showDet;

                var label = (obj.Value<string>("label") ?? "obj").Trim();
                var trackId = (obj.Value<string>("trackId") ?? string.Empty).Trim();
                var conf = obj.Value<float?>("conf") ?? 0f;
                labelText.text = string.IsNullOrWhiteSpace(trackId)
                    ? $"{label} {conf:0.00}"
                    : $"{label}#{trackId} {conf:0.00}";
                labelText.enabled = _showDet;
                idx += 1;
            }
            _overlayUpdates += 1;
        }

        private void ClearDetBoxes()
        {
            if (_boxOutlines == null || _boxLabels == null)
            {
                return;
            }

            for (var i = 0; i < _boxOutlines.Count; i += 1)
            {
                if (_boxOutlines[i] != null)
                {
                    _boxOutlines[i].enabled = false;
                }
                if (i < _boxLabels.Count && _boxLabels[i] != null)
                {
                    _boxLabels[i].enabled = false;
                }
            }
        }

        private void ApplyVisualState()
        {
            if (_detImage != null)
            {
                _detImage.color = new Color(1f, 1f, 1f, _detAlpha);
            }
            if (_segImage != null)
            {
                _segImage.color = new Color(1f, 0.25f, 0.25f, _segAlpha);
            }
            if (_depthImage != null)
            {
                _depthImage.color = new Color(1f, 1f, 1f, _depthAlpha);
            }
            RefreshLayerVisibility("det");
            RefreshLayerVisibility("seg");
            RefreshLayerVisibility("depth");
            if (_boxOutlines == null || _boxLabels == null)
            {
                return;
            }
            for (var i = 0; i < _boxOutlines.Count; i += 1)
            {
                if (_boxOutlines[i] != null)
                {
                    _boxOutlines[i].enabled = _showDet && _boxOutlines[i].enabled;
                }
                if (i < _boxLabels.Count && _boxLabels[i] != null)
                {
                    _boxLabels[i].enabled = _showDet && _boxLabels[i].enabled;
                }
            }
        }

        private static string NormalizeApplyMode(string applyMode)
        {
            var normalized = string.IsNullOrWhiteSpace(applyMode) ? string.Empty : applyMode.Trim().ToLowerInvariant();
            return normalized switch
            {
                "det" => "det",
                "seg" => "seg",
                "depth" => "depth",
                _ => string.Empty,
            };
        }

        private static string NormalizeAssetId(string assetId)
        {
            var normalized = string.IsNullOrWhiteSpace(assetId) ? string.Empty : assetId.Trim();
            if (string.IsNullOrWhiteSpace(normalized))
            {
                return string.Empty;
            }

            var queryIndex = normalized.IndexOf('?');
            if (queryIndex >= 0)
            {
                normalized = normalized.Substring(0, queryIndex);
            }

            var hashIndex = normalized.IndexOf('#');
            if (hashIndex >= 0)
            {
                normalized = normalized.Substring(0, hashIndex);
            }

            return normalized.Trim();
        }

        private static long ReadFrameSeq(JObject evt, JObject payload)
        {
            var parsed = ReadLong(payload?["frameSeq"]);
            if (parsed > 0)
            {
                return parsed;
            }
            parsed = ReadLong(evt?["frameSeq"]);
            return parsed > 0 ? parsed : -1;
        }

        private static long ReadEventTsMs(JObject evt, JObject payload)
        {
            var parsed = ReadLong(payload?["tsMs"]);
            if (parsed > 0)
            {
                return parsed;
            }
            parsed = ReadLong(evt?["tsMs"]);
            if (parsed > 0)
            {
                return parsed;
            }
            return DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }

        private static long ReadLong(JToken token)
        {
            if (token == null)
            {
                return -1;
            }
            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<long>();
            }
            return long.TryParse(token.ToString(), out var parsed) ? parsed : -1;
        }

        private bool IsStaleOverlayFrame(string applyMode, long frameSeq)
        {
            if (frameSeq <= 0)
            {
                return false;
            }
            if (_latestOverlayFrameSeq.TryGetValue(applyMode, out var latestFrameSeq) && frameSeq < latestFrameSeq)
            {
                return true;
            }
            if (_appliedOverlayFrameSeq.TryGetValue(applyMode, out var appliedFrameSeq) && frameSeq < appliedFrameSeq)
            {
                return true;
            }
            return false;
        }

        private void RememberOverlayFrameSeq(string applyMode, long frameSeq)
        {
            if (frameSeq <= 0)
            {
                return;
            }
            if (_latestOverlayFrameSeq.TryGetValue(applyMode, out var latestFrameSeq) && latestFrameSeq >= frameSeq)
            {
                return;
            }
            _latestOverlayFrameSeq[applyMode] = frameSeq;
        }

        private void UpdateOverlayTimestamp(string applyMode, long tsMs)
        {
            var normalizedMode = NormalizeApplyMode(applyMode);
            var safeTsMs = tsMs > 0 ? tsMs : DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            switch (normalizedMode)
            {
                case "det":
                    LastDetTsMs = safeTsMs;
                    break;
                case "seg":
                    LastSegTsMs = safeTsMs;
                    break;
                case "depth":
                    LastDepthTsMs = safeTsMs;
                    break;
            }
        }
    }
}
