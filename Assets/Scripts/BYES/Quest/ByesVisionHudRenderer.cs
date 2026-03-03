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
        private RawImage _segImage;
        private RawImage _depthImage;
        private List<Image> _boxOutlines;
        private List<Text> _boxLabels;
        private float _overlayWidth = 960f;
        private float _overlayHeight = 540f;
        private bool _showDet = true;
        private bool _showSeg = true;
        private bool _showDepth = true;
        private float _segAlpha = 0.35f;
        private float _depthAlpha = 0.30f;
        private bool _bound;
        private int _overlayUpdates;
        private float _fpsTickStart;

        public float OverlayFps { get; private set; }
        public float LastDecodeMs { get; private set; }
        public int LastAssetBytes { get; private set; }
        public long LastSegTsMs { get; private set; } = -1;
        public long LastDepthTsMs { get; private set; } = -1;
        public long LastDetTsMs { get; private set; } = -1;

        public void Initialize(
            RawImage segImage,
            RawImage depthImage,
            List<Image> boxOutlines,
            List<Text> boxLabels,
            float overlayWidth = 960f,
            float overlayHeight = 540f)
        {
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

        public void SetVisualState(bool showDet, bool showSeg, bool showDepth, float segAlpha, float depthAlpha)
        {
            _showDet = showDet;
            _showSeg = showSeg;
            _showDepth = showDepth;
            _segAlpha = Mathf.Clamp01(segAlpha);
            _depthAlpha = Mathf.Clamp01(depthAlpha);
            ApplyVisualState();
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

            switch (name)
            {
                case "seg.mask.v1":
                    if (_showSeg)
                    {
                        var segAssetId = (payload.Value<string>("assetId") ?? string.Empty).Trim();
                        if (!string.IsNullOrWhiteSpace(segAssetId))
                        {
                            StartCoroutine(DownloadAsset(segAssetId, applyToSeg: true));
                        }
                        LastSegTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    }
                    break;
                case "depth.map.v1":
                    if (_showDepth)
                    {
                        var depthAssetId = (payload.Value<string>("assetId") ?? string.Empty).Trim();
                        if (!string.IsNullOrWhiteSpace(depthAssetId))
                        {
                            StartCoroutine(DownloadAsset(depthAssetId, applyToSeg: false));
                        }
                        LastDepthTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                    }
                    break;
                case "det.objects.v1":
                case "det.objects":
                    LastDetTsMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
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

        private IEnumerator DownloadAsset(string assetId, bool applyToSeg)
        {
            if (_gatewayClient == null)
            {
                yield break;
            }

            var baseUrl = (_gatewayClient.BaseUrl ?? string.Empty).TrimEnd('/');
            var url = $"{baseUrl}/api/assets/{UnityWebRequest.EscapeURL(assetId)}";
            var started = Time.realtimeSinceStartup;
            using var request = UnityWebRequestTexture.GetTexture(url, true);
            request.timeout = 6;
            var apiKey = _gatewayClient.ApiKey;
            if (!string.IsNullOrWhiteSpace(apiKey))
            {
                request.SetRequestHeader("X-BYES-API-Key", apiKey.Trim());
            }
            yield return request.SendWebRequest();
            LastDecodeMs = Mathf.Max(0f, (Time.realtimeSinceStartup - started) * 1000f);
            if (request.result != UnityWebRequest.Result.Success)
            {
                yield break;
            }

            var texture = DownloadHandlerTexture.GetContent(request);
            if (texture == null)
            {
                yield break;
            }

            LastAssetBytes = request.downloadHandler?.data != null ? request.downloadHandler.data.Length : 0;
            if (applyToSeg)
            {
                if (_segImage != null)
                {
                    _segImage.texture = texture;
                }
            }
            else
            {
                if (_depthImage != null)
                {
                    _depthImage.texture = texture;
                }
            }
            _overlayUpdates += 1;
        }

        private void UpdateDetOverlay(JObject payload)
        {
            if (_boxOutlines == null || _boxLabels == null)
            {
                return;
            }

            var objects = payload["objects"] as JArray;
            var imageWidth = Mathf.Max(1f, payload.Value<float?>("imageWidth") ?? 1f);
            var imageHeight = Mathf.Max(1f, payload.Value<float?>("imageHeight") ?? 1f);

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

        private void ApplyVisualState()
        {
            if (_segImage != null)
            {
                _segImage.enabled = _showSeg;
                _segImage.color = new Color(1f, 0.25f, 0.25f, _segAlpha);
            }
            if (_depthImage != null)
            {
                _depthImage.enabled = _showDepth;
                _depthImage.color = new Color(1f, 1f, 1f, _depthAlpha);
            }
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
    }
}
