using System;
using System.Collections;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.UI;
using BeYourEyes.Unity.Interaction;
using BeYourEyes.Presenters.Audio;

namespace BeYourEyes.Presenters.DebugHUD
{
    public sealed class GatewayHUD : MonoBehaviour
    {
        [SerializeField] private BeYourEyes.Adapters.Networking.GatewayClient gatewayClient;
        [SerializeField] private BeYourEyes.Unity.Capture.FrameCapture frameCapture;
        [SerializeField] private LocalSafetyFallback localSafetyFallback;
        [SerializeField] private RiskFeedback riskFeedback;
        [SerializeField] private DirectionalGuidance directionalGuidance;
        [SerializeField] private SpeechOrchestrator speechOrchestrator;
        [SerializeField] private LocalIntentController localIntentController;
        [SerializeField] private DevScenarioPanel devScenarioPanel;
        [SerializeField] private BeYourEyes.Adapters.Networking.RunRecorder runRecorder;
        [SerializeField] private BeYourEyes.Adapters.Networking.RunReplayer runReplayer;
        [SerializeField] private float confirmPollIntervalSec = 1.5f;
        [SerializeField] private float limitedConfirmPollIntervalSec = 2.0f;
        [SerializeField] private int capabilityHintCooldownMs = 1200;
        [SerializeField] private bool showDebugCounters = true;

        private Text statusText;
        private Text confirmPromptText;
        private RectTransform confirmOptionsRoot;
        private Button speechReplayButton;
        private Button startRecButton;
        private Button stopRecButton;
        private Button replayRunButton;
        private Button stopReplayButton;
        private Button recordFramesButton;
        private readonly List<Button> confirmButtons = new List<Button>();

        private string wsState = "Disconnected";
        private string healthStatus = "-";
        private string healthReason = "-";
        private string capabilityState = "OK";
        private string capabilityReason = "-";
        private string capabilityHintText = string.Empty;
        private long capabilityHintUntilMs = -1;
        private long lastCapabilityHintAtMs = long.MinValue;
        private long lastReplayBlockHintAtMs = long.MinValue;
        private string riskText = "-";
        private string riskLevel = "-";
        private string actionSummary = "-";
        private string lastEventType = "-";
        private string lastEventSummary = "-";
        private string lastEventStage = "-";

        private string pendingConfirmId;
        private string pendingConfirmKind;
        private bool confirmSubmitting;
        private readonly HashSet<string> resolvedConfirmIds = new HashSet<string>();
        private readonly HashSet<string> expiredConfirmIds = new HashSet<string>();
        private readonly Dictionary<string, long> confirmFirstSeenAtMs = new Dictionary<string, long>();
        private readonly Dictionary<string, int> confirmTtlById = new Dictionary<string, int>();
        private long latestContentSeq = -1;
        private long displayedEventSeq = -1;
        private long displayedEventReceivedAtMs = -1;
        private int displayedEventTtlMs = 1500;

        private float nextClientLookupAt;
        private Coroutine confirmPollRoutine;

        private void OnEnable()
        {
            EnsureUi();
            EnsureRiskFeedback();
            EnsureDirectionalGuidance();
            EnsureSpeechOrchestrator();
            EnsureLocalIntentController();
            EnsureRunTools();
            EnsureDevScenarioPanel();
            BindClient();
            StartConfirmPoller();
        }

        private void OnDisable()
        {
            StopConfirmPoller();
            UnbindClient();
        }

        private void Update()
        {
            if (gatewayClient == null && Time.unscaledTime >= nextClientLookupAt)
            {
                nextClientLookupAt = Time.unscaledTime + 1f;
                BindClient();
            }

            if (frameCapture == null)
            {
                frameCapture = FindFirstObjectByType<BeYourEyes.Unity.Capture.FrameCapture>();
            }
            if (localSafetyFallback == null)
            {
                localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
            }
            if (riskFeedback == null)
            {
                riskFeedback = FindFirstObjectByType<RiskFeedback>();
            }
            if (directionalGuidance == null)
            {
                directionalGuidance = FindFirstObjectByType<DirectionalGuidance>();
            }
            if (speechOrchestrator == null)
            {
                speechOrchestrator = FindFirstObjectByType<SpeechOrchestrator>();
            }
            if (localIntentController == null)
            {
                localIntentController = FindFirstObjectByType<LocalIntentController>();
            }
            if (runRecorder == null)
            {
                runRecorder = FindFirstObjectByType<BeYourEyes.Adapters.Networking.RunRecorder>();
            }
            if (runReplayer == null)
            {
                runReplayer = FindFirstObjectByType<BeYourEyes.Adapters.Networking.RunReplayer>();
            }
            if (devScenarioPanel == null)
            {
                devScenarioPanel = FindFirstObjectByType<DevScenarioPanel>();
            }

            if (statusText != null)
            {
                var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                if (IsDisplayedEventExpired(nowMs))
                {
                    ClearDisplayedContent();
                }

                var lastMsgAgeText = gatewayClient != null && gatewayClient.LastMessageAtMs > 0
                    ? $"{Mathf.Max(0f, (float)(nowMs - gatewayClient.LastMessageAtMs) / 1000f):0.0}s ago"
                    : "-";
                var reconnectText = gatewayClient != null ? gatewayClient.ReconnectAttempt.ToString() : "-";
                var healthRttText = gatewayClient != null && gatewayClient.LastHealthRttMs >= 0
                    ? $"{gatewayClient.LastHealthRttMs} ms"
                    : "-";
                var ttfaText = gatewayClient != null && gatewayClient.LastTtfaMs >= 0 ? $"{gatewayClient.LastTtfaMs} ms" : "-";
                var ttfaEmaText = gatewayClient != null && gatewayClient.TtfaEmaMs >= 0 ? $"{gatewayClient.TtfaEmaMs:0.0} ms" : "-";
                var captureStats = frameCapture == null
                    ? "-"
                    : $"cap={frameCapture.FramesCaptured} sent={frameCapture.FramesSent} dropBusy={frameCapture.FramesDroppedBusy} dropNoConn={frameCapture.FramesDroppedNoConn}";
                var bytesEmaText = frameCapture != null && frameCapture.BytesEma >= 0
                    ? $"{frameCapture.BytesEma:0}"
                    : "-";
                var keyframeReasonText = frameCapture == null ? "-" : frameCapture.LastKeyframeReason;
                var fallbackStateText = localSafetyFallback == null ? "OK" : localSafetyFallback.CurrentState.ToString();
                var fallbackSinceText = "-";
                var fallbackReasonText = localSafetyFallback == null ? "-" : localSafetyFallback.LastReason;
                var intentText = gatewayClient == null ? "none" : gatewayClient.CurrentIntentKind;
                var questionText = gatewayClient == null ? "-" : Truncate(gatewayClient.CurrentQuestion, 40);
                var localIntentHint = localIntentController == null ? "-" : localIntentController.HintText;
                var capabilityText = gatewayClient == null ? capabilityState : gatewayClient.CurrentCapabilityState.ToString();
                var runIdText = runRecorder == null || string.IsNullOrWhiteSpace(runRecorder.CurrentRunId) ? "-" : runRecorder.CurrentRunId;
                var runPathText = runRecorder == null || string.IsNullOrWhiteSpace(runRecorder.CurrentRunDirectory) ? "-" : runRecorder.CurrentRunDirectory;
                var recStateText = runRecorder == null ? "n/a" : (runRecorder.IsRecording ? "REC" : "IDLE");
                var replayStateText = runReplayer == null ? "n/a" : (runReplayer.IsReplaying ? "REPLAY" : "IDLE");
                var replayProgressText = runReplayer == null || !runReplayer.IsReplaying
                    ? "-"
                    : $"{runReplayer.ReplayIndex}/{Mathf.Max(1, runReplayer.ReplayTotal)} @{runReplayer.ReplaySpeed:0.0}x";
                var replayModeText = gatewayClient != null && gatewayClient.IsReplayMode ? "ON" : "OFF";
                if (gatewayClient != null)
                {
                    capabilityReason = gatewayClient.CapabilityTransitionReason;
                }
                var readinessText = gatewayClient == null || !gatewayClient.ReadinessKnown
                    ? "n/a"
                    : $"{gatewayClient.ReadyToolsCount}/{gatewayClient.UnavailableToolsCount}";
                if (localSafetyFallback != null && localSafetyFallback.StateEnteredAtMs > 0)
                {
                    fallbackSinceText = $"{Mathf.Max(0f, (float)(nowMs - localSafetyFallback.StateEnteredAtMs) / 1000f):0.0}s";
                }
                if (capabilityHintUntilMs > 0 && nowMs > capabilityHintUntilMs)
                {
                    capabilityHintText = string.Empty;
                    capabilityHintUntilMs = -1;
                }
                if (localSafetyFallback != null && !localSafetyFallback.IsOk)
                {
                    ClearDisplayedContent();
                }
                if (recordFramesButton != null && runRecorder != null)
                {
                    var text = recordFramesButton.GetComponentInChildren<Text>();
                    if (text != null)
                    {
                        text.text = runRecorder.RecordFrames ? "RecordFrames: ON" : "RecordFrames: OFF";
                    }
                }

                var lastEventAgeMs = displayedEventReceivedAtMs > 0 ? Math.Max(0, nowMs - displayedEventReceivedAtMs) : -1;
                var safeBanner = string.Equals(healthStatus, "SAFE_MODE", StringComparison.OrdinalIgnoreCase)
                    ? "\nSAFE MODE: STOP / RISK ONLY"
                    : string.Empty;
                var debugLines = string.Empty;
                if (showDebugCounters && gatewayClient != null)
                {
                    var guidanceLine = directionalGuidance == null
                        ? "\nGuidance: n/a"
                        : $"\nGuidance: shown={directionalGuidance.GuidanceShownCount} cleared={directionalGuidance.GuidanceClearedCount} kind={directionalGuidance.LastGuidanceKind} az={directionalGuidance.LastAzimuthText} dist={directionalGuidance.LastDistanceText}";
                    var speechLine = speechOrchestrator == null
                        ? "\nSpeech: n/a"
                        : $"\nSpeech: spoken={speechOrchestrator.SpokenCount} coolDrop={speechOrchestrator.DroppedByCooldownCount} policyDrop={speechOrchestrator.DroppedByPolicyCount} lastKind={speechOrchestrator.LastSpokenKind} lastAt={speechOrchestrator.LastSpokenAtMs}";
                    var intentLine = localIntentController == null
                        ? "\nIntentCtl: n/a"
                        : $"\nIntentCtl: enter={localIntentController.ScanEnterCount} exit={localIntentController.ScanExitCount} ask={localIntentController.AskTriggerCount} blocked={localIntentController.BlockedCount} reason={localIntentController.LastBlockedReason}";
                    var probeLine = gatewayClient == null
                        ? "\nProbe: n/a"
                        : $"\nProbe: health ok/fail={gatewayClient.HealthProbeSuccessCount}/{gatewayClient.HealthProbeFailureCount} readiness ok/fail={gatewayClient.ReadinessProbeSuccessCount}/{gatewayClient.ReadinessProbeFailureCount}";
                    var stateLine = gatewayClient == null
                        ? "\nCapability: n/a"
                        : $"\nCapability: state={gatewayClient.CurrentCapabilityState} reason={gatewayClient.CapabilityTransitionReason} transitions={gatewayClient.CapabilityStateTransitionCount}";
                    debugLines =
                        $"\nGuard: acc={gatewayClient.EventAcceptedCount} exp={gatewayClient.EventDroppedExpiredCount} ooo={gatewayClient.EventDroppedOutOfOrderCount} fb={gatewayClient.EventDroppedByFallbackCount}" +
                        $"\nGate: acc={gatewayClient.ActionPlanGateAcceptedCount} blk={gatewayClient.ActionPlanGateBlockedCount} pat={gatewayClient.ActionPlanGatePatchedCount} reason={gatewayClient.ActionPlanGateLastReason}" +
                        guidanceLine +
                        speechLine +
                        intentLine +
                        probeLine +
                        stateLine +
                        $"\nlastSeqSeen={gatewayClient.EventLastSeqSeen} displayedSeq={displayedEventSeq} lastEventAgeMs={(lastEventAgeMs >= 0 ? lastEventAgeMs.ToString() : "-")}";
                }

                statusText.text =
                    "Gateway HUD\n" +
                    $"WS: {wsState}\n" +
                    $"Reconnects: {reconnectText}\n" +
                    $"LastMsg: {lastMsgAgeText}\n" +
                    $"HealthRTT: {healthRttText}\n" +
                    $"Health: {healthStatus}\n" +
                    $"Reason: {healthReason}\n" +
                    $"Capability: {capabilityText} ({capabilityReason})\n" +
                    $"Readiness: {readinessText}\n" +
                    $"Risk: {riskText}\n" +
                    $"RiskLevel: {riskLevel}\n" +
                    $"Action: {actionSummary}\n" +
                    $"Event: {lastEventType} stage={lastEventStage}\n" +
                    $"Summary: {lastEventSummary}\n" +
                    $"TTFA: {ttfaText} | EMA: {ttfaEmaText}\n" +
                    $"Frames: {captureStats}\n" +
                    $"BytesEMA: {bytesEmaText}\n" +
                    $"Keyframe: {keyframeReasonText}\n" +
                    $"Fallback: {fallbackStateText} since={fallbackSinceText} reason={fallbackReasonText}\n" +
                    $"Intent: {intentText} | Question: {questionText}\n" +
                    $"IntentHint: {localIntentHint}\n" +
                    $"Run: {recStateText} id={runIdText}\n" +
                    $"Replay: {replayStateText} mode={replayModeText} progress={replayProgressText}\n" +
                    $"RunPath: {Truncate(runPathText, 60)}\n" +
                    $"CapHint: {(string.IsNullOrWhiteSpace(capabilityHintText) ? "-" : capabilityHintText)}\n" +
                    $"PendingConfirm: {(string.IsNullOrWhiteSpace(pendingConfirmId) ? "-" : pendingConfirmKind)}" +
                    debugLines +
                    safeBanner;
            }
        }

        private void BindClient()
        {
            if (gatewayClient == null)
            {
                gatewayClient = FindFirstObjectByType<BeYourEyes.Adapters.Networking.GatewayClient>();
            }

            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            gatewayClient.OnGatewayEvent += HandleGatewayEvent;
            gatewayClient.OnCapabilityStateChanged -= HandleCapabilityStateChanged;
            gatewayClient.OnCapabilityStateChanged += HandleCapabilityStateChanged;
            gatewayClient.OnWebSocketStateChanged -= HandleWsStateChanged;
            gatewayClient.OnWebSocketStateChanged += HandleWsStateChanged;
            gatewayClient.OnReplayBlockedNetworkAction -= HandleReplayBlockedNetworkAction;
            gatewayClient.OnReplayBlockedNetworkAction += HandleReplayBlockedNetworkAction;
            wsState = gatewayClient.IsConnected ? "Connected" : "Disconnected";
            capabilityState = gatewayClient.CurrentCapabilityState.ToString();
            capabilityReason = gatewayClient.CapabilityTransitionReason;
        }

        private void UnbindClient()
        {
            if (gatewayClient == null)
            {
                return;
            }

            gatewayClient.OnGatewayEvent -= HandleGatewayEvent;
            gatewayClient.OnCapabilityStateChanged -= HandleCapabilityStateChanged;
            gatewayClient.OnWebSocketStateChanged -= HandleWsStateChanged;
            gatewayClient.OnReplayBlockedNetworkAction -= HandleReplayBlockedNetworkAction;
        }

        private void HandleWsStateChanged(bool connected, string reason)
        {
            wsState = connected ? "Connected" : $"Disconnected ({reason})";
        }

        private void HandleCapabilityStateChanged(BeYourEyes.Adapters.Networking.CapabilityState state, string reason)
        {
            capabilityState = state.ToString();
            capabilityReason = string.IsNullOrWhiteSpace(reason) ? "-" : reason;

            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (nowMs - lastCapabilityHintAtMs < Math.Max(200, capabilityHintCooldownMs))
            {
                return;
            }

            lastCapabilityHintAtMs = nowMs;
            capabilityHintText = BuildCapabilityHint(state);
            capabilityHintUntilMs = nowMs + 1500;
            if (speechOrchestrator != null && !string.IsNullOrWhiteSpace(capabilityHintText))
            {
                speechOrchestrator.SpeakLocalHint(capabilityHintText, flush: false);
            }
        }

        private void HandleReplayBlockedNetworkAction(string action)
        {
            var nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (nowMs - lastReplayBlockHintAtMs < 1200)
            {
                return;
            }

            lastReplayBlockHintAtMs = nowMs;
            capabilityHintText = $"Replay mode: network disabled ({action})";
            capabilityHintUntilMs = nowMs + 1400;
        }

        private void HandleGatewayEvent(JObject evt)
        {
            var type = ReadString(evt, "type");
            var summary = ReadString(evt, "summary");
            if (string.IsNullOrWhiteSpace(summary))
            {
                summary = ReadString(evt, "riskText");
            }
            if (string.IsNullOrWhiteSpace(type))
            {
                return;
            }
            lastEventStage = ReadString(evt, "stage");
            if (string.IsNullOrWhiteSpace(lastEventStage))
            {
                lastEventStage = "-";
            }

            if (!ShouldApplyEventBySeq(type, evt))
            {
                return;
            }

            lastEventType = type;
            lastEventSummary = string.IsNullOrWhiteSpace(summary) ? "-" : summary;
            displayedEventReceivedAtMs = ReadLong(evt, "_receivedAtMs") ?? -1;
            displayedEventTtlMs = ReadInt(evt, "_eventTtlMs", gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500);
            switch (type)
            {
                case "health":
                    healthStatus = ReadString(evt, "healthStatus");
                    if (string.IsNullOrWhiteSpace(healthStatus))
                    {
                        healthStatus = ParseHealthStatusFromSummary(summary);
                    }
                    healthReason = ReadString(evt, "healthReason");
                    if (string.IsNullOrEmpty(healthReason))
                    {
                        healthReason = ParseHealthReasonFromSummary(summary);
                    }
                    if (string.IsNullOrEmpty(healthReason))
                    {
                        healthReason = summary;
                    }
                    break;
                case "risk":
                    riskText = ReadString(evt, "riskText");
                    if (string.IsNullOrEmpty(riskText))
                    {
                        riskText = ReadString(evt, "summary");
                    }
                    riskLevel = ReadString(evt, "riskLevel");
                    if (string.IsNullOrEmpty(riskLevel))
                    {
                        riskLevel = "warn";
                    }
                    actionSummary = "-";
                    break;
                case "action_plan":
                    actionSummary = summary;
                    HandleConfirmPayload(evt);
                    break;
                case "perception":
                    actionSummary = summary;
                    riskText = "-";
                    riskLevel = "-";
                    break;
            }
        }

        private void HandleConfirmPayload(JObject evt)
        {
            if (localSafetyFallback != null && !localSafetyFallback.IsOk)
            {
                return;
            }

            var confirmId = ReadString(evt, "confirmId");
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                return;
            }
            if (expiredConfirmIds.Contains(confirmId))
            {
                return;
            }

            RegisterConfirmFreshness(confirmId, evt);
            ApplyConfirmFreshness(confirmId, evt);
            if (IsEventExpired(evt, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()))
            {
                expiredConfirmIds.Add(confirmId);
                return;
            }
            if (resolvedConfirmIds.Contains(confirmId))
            {
                return;
            }
            if (!string.IsNullOrWhiteSpace(pendingConfirmId) && string.Equals(pendingConfirmId, confirmId, StringComparison.Ordinal))
            {
                return;
            }

            pendingConfirmId = confirmId;
            pendingConfirmKind = ReadString(evt, "confirmKind");
            var prompt = ReadString(evt, "confirmPrompt");
            if (string.IsNullOrWhiteSpace(prompt))
            {
                prompt = ReadString(evt, "summary");
            }

            var options = new List<string>();
            if (evt["confirmOptions"] is JArray arr)
            {
                foreach (var token in arr)
                {
                    var option = token?.ToString().Trim();
                    if (!string.IsNullOrWhiteSpace(option))
                    {
                        options.Add(option);
                    }
                }
            }

            if (options.Count == 0)
            {
                options.Add("yes");
                options.Add("no");
            }

            ShowConfirmPanel(prompt, options);
        }

        private void ShowConfirmPanel(string prompt, List<string> options)
        {
            if (confirmPromptText != null)
            {
                confirmPromptText.text = string.IsNullOrWhiteSpace(prompt) ? "Please confirm" : prompt;
            }

            foreach (var button in confirmButtons)
            {
                if (button != null)
                {
                    Destroy(button.gameObject);
                }
            }
            confirmButtons.Clear();

            if (confirmOptionsRoot == null)
            {
                return;
            }

            foreach (var option in options)
            {
                var optionCopy = option;
                var button = CreateOptionButton(confirmOptionsRoot, optionCopy);
                button.onClick.AddListener(() => OnConfirmChoice(optionCopy));
                confirmButtons.Add(button);
            }

            confirmSubmitting = false;
            SetConfirmButtonsInteractable(true);
            confirmPromptText.gameObject.SetActive(true);
            confirmOptionsRoot.gameObject.SetActive(true);
        }

        private void HideConfirmPanel()
        {
            pendingConfirmId = null;
            pendingConfirmKind = null;
            if (confirmPromptText != null)
            {
                confirmPromptText.text = string.Empty;
                confirmPromptText.gameObject.SetActive(false);
            }
            confirmSubmitting = false;

            if (confirmOptionsRoot != null)
            {
                confirmOptionsRoot.gameObject.SetActive(false);
            }
        }

        private void OnConfirmChoice(string choice)
        {
            if (gatewayClient == null || string.IsNullOrWhiteSpace(pendingConfirmId))
            {
                return;
            }
            if (confirmSubmitting)
            {
                return;
            }

            confirmSubmitting = true;
            SetConfirmButtonsInteractable(false);
            var confirmId = pendingConfirmId;
            gatewayClient.SendConfirm(confirmId, choice, "unity_hud", success =>
            {
                if (success)
                {
                    resolvedConfirmIds.Add(confirmId);
                    confirmFirstSeenAtMs.Remove(confirmId);
                    confirmTtlById.Remove(confirmId);
                    Debug.Log($"[GatewayHUD] confirm submitted: id={confirmId} choice={choice}");
                    HideConfirmPanel();
                }
                else
                {
                    confirmSubmitting = false;
                    SetConfirmButtonsInteractable(true);
                }
            });
        }

        private void StartConfirmPoller()
        {
            if (confirmPollRoutine != null)
            {
                return;
            }

            confirmPollRoutine = StartCoroutine(ConfirmPollLoop());
        }

        private void StopConfirmPoller()
        {
            if (confirmPollRoutine == null)
            {
                return;
            }

            StopCoroutine(confirmPollRoutine);
            confirmPollRoutine = null;
        }

        private IEnumerator ConfirmPollLoop()
        {
            while (true)
            {
                var waitSec = Mathf.Max(0.5f, confirmPollIntervalSec);
                if (localSafetyFallback == null)
                {
                    localSafetyFallback = FindFirstObjectByType<LocalSafetyFallback>();
                }

                if (localSafetyFallback != null && !localSafetyFallback.IsOk)
                {
                    yield return new WaitForSecondsRealtime(waitSec);
                    continue;
                }

                if (gatewayClient != null && gatewayClient.IsReplayMode)
                {
                    yield return new WaitForSecondsRealtime(waitSec);
                    continue;
                }

                if (gatewayClient != null)
                {
                    var capability = gatewayClient.CurrentCapabilityState;
                    if (capability == BeYourEyes.Adapters.Networking.CapabilityState.OFFLINE ||
                        capability == BeYourEyes.Adapters.Networking.CapabilityState.REMOTE_STALE)
                    {
                        yield return new WaitForSecondsRealtime(waitSec);
                        continue;
                    }
                    if (capability == BeYourEyes.Adapters.Networking.CapabilityState.LIMITED_NOT_READY)
                    {
                        waitSec = Mathf.Max(waitSec, Mathf.Max(0.5f, limitedConfirmPollIntervalSec));
                    }
                }

                if (gatewayClient != null)
                {
                    gatewayClient.FetchPendingConfirm((ok, payload) =>
                    {
                        if (!ok || payload == null)
                        {
                            return;
                        }

                        var pendingToken = payload["pending"];
                        if (!(pendingToken is JObject pendingObj))
                        {
                            return;
                        }

                        var confirmId = ReadString(pendingObj, "confirmId");
                        if (string.IsNullOrWhiteSpace(confirmId) || expiredConfirmIds.Contains(confirmId))
                        {
                            return;
                        }

                        RegisterConfirmFreshness(confirmId, pendingObj);
                        ApplyConfirmFreshness(confirmId, pendingObj);
                        if (!gatewayClient.TryAcceptUiEvent(pendingObj, "action_plan", out _, out _, out var rejectReason))
                        {
                            if (string.Equals(rejectReason, "expired", StringComparison.OrdinalIgnoreCase))
                            {
                                expiredConfirmIds.Add(confirmId);
                            }
                            return;
                        }

                        if (resolvedConfirmIds.Contains(confirmId))
                        {
                            return;
                        }

                        if (!string.IsNullOrWhiteSpace(pendingConfirmId) &&
                            string.Equals(confirmId, pendingConfirmId, StringComparison.Ordinal))
                        {
                            return;
                        }

                        gatewayClient.PublishAcceptedUiEvent(pendingObj);
                    });
                }

                yield return new WaitForSecondsRealtime(waitSec);
            }
        }

        private void SetConfirmButtonsInteractable(bool interactable)
        {
            foreach (var button in confirmButtons)
            {
                if (button != null)
                {
                    button.interactable = interactable;
                }
            }
        }

        private void EnsureUi()
        {
            if (statusText != null && confirmPromptText != null && confirmOptionsRoot != null)
            {
                EnsureControlButtons();
                return;
            }

            var canvasObj = new GameObject("ByesGatewayHudCanvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasObj.transform.SetParent(transform, false);
            var canvas = canvasObj.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 800;

            var scaler = canvasObj.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
            scaler.referenceResolution = new Vector2(1920f, 1080f);

            var panel = CreatePanel(canvasObj.transform, new Vector2(12f, -12f), new Vector2(0f, 1f), new Vector2(520f, 360f));
            statusText = CreateText(panel.transform, "StatusText", 18, TextAnchor.UpperLeft);
            statusText.rectTransform.anchorMin = new Vector2(0f, 0.45f);
            statusText.rectTransform.anchorMax = new Vector2(1f, 1f);
            statusText.rectTransform.offsetMin = new Vector2(8f, 8f);
            statusText.rectTransform.offsetMax = new Vector2(-8f, -8f);

            var confirmPanel = CreatePanel(panel.transform, new Vector2(0f, 0f), new Vector2(0f, 0f), new Vector2(0f, 0f));
            var confirmRect = confirmPanel.GetComponent<RectTransform>();
            confirmRect.anchorMin = new Vector2(0f, 0f);
            confirmRect.anchorMax = new Vector2(1f, 0.42f);
            confirmRect.offsetMin = new Vector2(8f, 8f);
            confirmRect.offsetMax = new Vector2(-8f, -8f);

            confirmPromptText = CreateText(confirmPanel.transform, "ConfirmPrompt", 16, TextAnchor.UpperLeft);
            confirmPromptText.rectTransform.anchorMin = new Vector2(0f, 0.45f);
            confirmPromptText.rectTransform.anchorMax = new Vector2(1f, 1f);
            confirmPromptText.rectTransform.offsetMin = new Vector2(6f, 6f);
            confirmPromptText.rectTransform.offsetMax = new Vector2(-6f, -6f);

            var optionsObj = new GameObject("ConfirmOptions", typeof(RectTransform), typeof(HorizontalLayoutGroup));
            optionsObj.transform.SetParent(confirmPanel.transform, false);
            confirmOptionsRoot = optionsObj.GetComponent<RectTransform>();
            confirmOptionsRoot.anchorMin = new Vector2(0f, 0f);
            confirmOptionsRoot.anchorMax = new Vector2(1f, 0.42f);
            confirmOptionsRoot.offsetMin = new Vector2(6f, 6f);
            confirmOptionsRoot.offsetMax = new Vector2(-6f, -6f);

            var layout = optionsObj.GetComponent<HorizontalLayoutGroup>();
            layout.spacing = 8f;
            layout.childForceExpandHeight = true;
            layout.childForceExpandWidth = true;
            layout.childControlHeight = true;
            layout.childControlWidth = true;

            HideConfirmPanel();
            EnsureControlButtons();
        }

        private static GameObject CreatePanel(Transform parent, Vector2 anchoredPos, Vector2 anchor, Vector2 size)
        {
            var obj = new GameObject("Panel", typeof(RectTransform), typeof(Image));
            obj.transform.SetParent(parent, false);
            var rect = obj.GetComponent<RectTransform>();
            rect.anchorMin = anchor;
            rect.anchorMax = anchor;
            rect.pivot = anchor;
            rect.anchoredPosition = anchoredPos;
            rect.sizeDelta = size;

            var image = obj.GetComponent<Image>();
            image.color = new Color(0.05f, 0.08f, 0.12f, 0.82f);
            return obj;
        }

        private static Text CreateText(Transform parent, string name, int fontSize, TextAnchor anchor)
        {
            var obj = new GameObject(name, typeof(RectTransform), typeof(Text));
            obj.transform.SetParent(parent, false);
            var text = obj.GetComponent<Text>();
            var font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (font != null)
            {
                text.font = font;
            }
            text.fontSize = fontSize;
            text.color = Color.white;
            text.alignment = anchor;
            text.horizontalOverflow = HorizontalWrapMode.Wrap;
            text.verticalOverflow = VerticalWrapMode.Overflow;
            text.raycastTarget = false;
            return text;
        }

        private static Button CreateOptionButton(Transform parent, string label)
        {
            var buttonObj = new GameObject($"Option_{label}", typeof(RectTransform), typeof(Image), typeof(Button));
            buttonObj.transform.SetParent(parent, false);

            var image = buttonObj.GetComponent<Image>();
            image.color = new Color(0.2f, 0.45f, 0.8f, 0.95f);

            var button = buttonObj.GetComponent<Button>();
            button.targetGraphic = image;

            var text = CreateText(buttonObj.transform, "Label", 16, TextAnchor.MiddleCenter);
            text.text = label;
            text.rectTransform.anchorMin = Vector2.zero;
            text.rectTransform.anchorMax = Vector2.one;
            text.rectTransform.offsetMin = new Vector2(4f, 4f);
            text.rectTransform.offsetMax = new Vector2(-4f, -4f);
            return button;
        }

        private bool ShouldApplyEventBySeq(string type, JObject evt)
        {
            if (string.Equals(type, "health", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (!string.Equals(type, "risk", StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(type, "perception", StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(type, "action_plan", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }

            if (ReadLong(evt, "seq") is long seq && seq > 0)
            {
                if (latestContentSeq > 0 && seq < latestContentSeq)
                {
                    return false;
                }

                latestContentSeq = seq;
                displayedEventSeq = seq;
                return true;
            }

            return latestContentSeq <= 0;
        }

        private bool IsDisplayedEventExpired(long nowMs)
        {
            if (displayedEventReceivedAtMs <= 0)
            {
                return false;
            }

            var ttlMs = Math.Max(100, displayedEventTtlMs);
            return nowMs - displayedEventReceivedAtMs > ttlMs;
        }

        private void ClearDisplayedContent()
        {
            riskText = "-";
            riskLevel = "-";
            actionSummary = "-";
            lastEventType = "-";
            lastEventSummary = "-";
            lastEventStage = "-";
            displayedEventReceivedAtMs = -1;
            displayedEventTtlMs = gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500;
            displayedEventSeq = -1;
            HideConfirmPanel();
            EnsureControlButtons();
        }

        private void EnsureRiskFeedback()
        {
            if (riskFeedback != null)
            {
                return;
            }

            riskFeedback = GetComponent<RiskFeedback>();
            if (riskFeedback == null)
            {
                riskFeedback = gameObject.AddComponent<RiskFeedback>();
            }
        }

        private void EnsureDirectionalGuidance()
        {
            if (directionalGuidance != null)
            {
                return;
            }

            directionalGuidance = GetComponent<DirectionalGuidance>();
            if (directionalGuidance == null)
            {
                directionalGuidance = gameObject.AddComponent<DirectionalGuidance>();
            }
        }

        private void EnsureSpeechOrchestrator()
        {
            if (speechOrchestrator != null)
            {
                return;
            }

            speechOrchestrator = GetComponent<SpeechOrchestrator>();
            if (speechOrchestrator == null)
            {
                speechOrchestrator = gameObject.AddComponent<SpeechOrchestrator>();
            }
        }

        private void EnsureLocalIntentController()
        {
            if (localIntentController != null)
            {
                return;
            }

            localIntentController = GetComponent<LocalIntentController>();
            if (localIntentController == null)
            {
                localIntentController = gameObject.AddComponent<LocalIntentController>();
            }
        }

        private void EnsureRunTools()
        {
            if (runRecorder == null)
            {
                runRecorder = GetComponent<BeYourEyes.Adapters.Networking.RunRecorder>();
                if (runRecorder == null)
                {
                    runRecorder = gameObject.AddComponent<BeYourEyes.Adapters.Networking.RunRecorder>();
                }
            }

            if (runReplayer == null)
            {
                runReplayer = GetComponent<BeYourEyes.Adapters.Networking.RunReplayer>();
                if (runReplayer == null)
                {
                    runReplayer = gameObject.AddComponent<BeYourEyes.Adapters.Networking.RunReplayer>();
                }
            }
        }

        private void EnsureDevScenarioPanel()
        {
            if (devScenarioPanel != null)
            {
                return;
            }

            devScenarioPanel = GetComponent<DevScenarioPanel>();
            if (devScenarioPanel == null)
            {
                devScenarioPanel = gameObject.AddComponent<DevScenarioPanel>();
            }
        }

        private void EnsureControlButtons()
        {
            if (speechReplayButton != null || statusText == null)
            {
                return;
            }

            EnsureRunTools();
            var panel = statusText.transform.parent;
            if (panel == null)
            {
                return;
            }

            speechReplayButton = CreateOptionButton(panel, "Replay TTS");
            var speechRect = speechReplayButton.GetComponent<RectTransform>();
            speechRect.anchorMin = new Vector2(1f, 1f);
            speechRect.anchorMax = new Vector2(1f, 1f);
            speechRect.pivot = new Vector2(1f, 1f);
            speechRect.anchoredPosition = new Vector2(-10f, -10f);
            speechRect.sizeDelta = new Vector2(120f, 34f);
            speechReplayButton.onClick.AddListener(OnSpeechReplayClicked);

            startRecButton = CreateOptionButton(panel, "Start Rec");
            SetupControlButton(startRecButton, new Vector2(10f, 10f), new Vector2(0f, 0f), new Vector2(92f, 32f), OnStartRecClicked);

            stopRecButton = CreateOptionButton(panel, "Stop Rec");
            SetupControlButton(stopRecButton, new Vector2(108f, 10f), new Vector2(0f, 0f), new Vector2(92f, 32f), OnStopRecClicked);

            replayRunButton = CreateOptionButton(panel, "Replay Last");
            SetupControlButton(replayRunButton, new Vector2(206f, 10f), new Vector2(0f, 0f), new Vector2(108f, 32f), OnReplayRunClicked);

            stopReplayButton = CreateOptionButton(panel, "Stop Replay");
            SetupControlButton(stopReplayButton, new Vector2(320f, 10f), new Vector2(0f, 0f), new Vector2(108f, 32f), OnStopReplayClicked);

            recordFramesButton = CreateOptionButton(panel, "RecordFrames: OFF");
            SetupControlButton(recordFramesButton, new Vector2(10f, 46f), new Vector2(0f, 0f), new Vector2(170f, 30f), OnToggleRecordFramesClicked);
        }

        private static void SetupControlButton(Button button, Vector2 anchoredPosition, Vector2 pivot, Vector2 size, UnityEngine.Events.UnityAction callback)
        {
            if (button == null)
            {
                return;
            }

            var rect = button.GetComponent<RectTransform>();
            rect.anchorMin = new Vector2(0f, 0f);
            rect.anchorMax = new Vector2(0f, 0f);
            rect.pivot = pivot;
            rect.anchoredPosition = anchoredPosition;
            rect.sizeDelta = size;
            button.onClick.RemoveAllListeners();
            button.onClick.AddListener(callback);
        }

        private void OnSpeechReplayClicked()
        {
            if (speechOrchestrator == null)
            {
                EnsureSpeechOrchestrator();
            }

            speechOrchestrator?.ReplayLast();
        }

        private void OnStartRecClicked()
        {
            EnsureRunTools();
            if (runRecorder == null || runRecorder.IsRecording)
            {
                return;
            }

            runRecorder.StartRecording(out var message);
            if (!string.IsNullOrWhiteSpace(message))
            {
                capabilityHintText = $"REC: {message}";
                capabilityHintUntilMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 1800;
            }
        }

        private void OnStopRecClicked()
        {
            EnsureRunTools();
            runRecorder?.StopRecording();
        }

        private void OnReplayRunClicked()
        {
            EnsureRunTools();
            if (runReplayer == null)
            {
                return;
            }

            if (!runReplayer.ReplayLatestRun(out var message))
            {
                capabilityHintText = $"Replay failed: {message}";
                capabilityHintUntilMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() + 1800;
            }
        }

        private void OnStopReplayClicked()
        {
            EnsureRunTools();
            runReplayer?.StopReplay();
        }

        private void OnToggleRecordFramesClicked()
        {
            EnsureRunTools();
            if (runRecorder == null)
            {
                return;
            }

            runRecorder.SetRecordFrames(!runRecorder.RecordFrames);
        }

        private bool IsEventExpired(JObject evt, long nowMs)
        {
            var receivedAt = ReadLong(evt, "_receivedAtMs") ?? nowMs;
            var ttlMs = ReadInt(evt, "_eventTtlMs", gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500);
            return nowMs - receivedAt > Math.Max(100, ttlMs);
        }

        private void RegisterConfirmFreshness(string confirmId, JObject evt)
        {
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                return;
            }

            var ttlMs = ReadInt(evt, "_eventTtlMs", gatewayClient != null ? gatewayClient.EventDefaultTtlMs : 1500);
            confirmTtlById[confirmId] = Math.Max(100, ttlMs);
            if (!confirmFirstSeenAtMs.ContainsKey(confirmId))
            {
                confirmFirstSeenAtMs[confirmId] = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            }
        }

        private void ApplyConfirmFreshness(string confirmId, JObject evt)
        {
            if (string.IsNullOrWhiteSpace(confirmId))
            {
                return;
            }

            if (confirmFirstSeenAtMs.TryGetValue(confirmId, out var firstSeen))
            {
                evt["_receivedAtMs"] = firstSeen;
            }

            if (confirmTtlById.TryGetValue(confirmId, out var ttl))
            {
                evt["_eventTtlMs"] = ttl;
            }
        }

        private static long? ReadLong(JObject obj, string key)
        {
            var token = obj[key];
            if (token == null)
            {
                return null;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<long>();
            }

            return long.TryParse(token.ToString(), out var parsed) ? parsed : (long?)null;
        }

        private static int ReadInt(JObject obj, string key, int defaultValue)
        {
            var token = obj[key];
            if (token == null)
            {
                return defaultValue;
            }

            if (token.Type == JTokenType.Integer || token.Type == JTokenType.Float)
            {
                return token.Value<int>();
            }

            return int.TryParse(token.ToString(), out var parsed) ? parsed : defaultValue;
        }

        private static string ReadString(JObject obj, string key)
        {
            var token = obj[key];
            return token == null ? string.Empty : token.ToString().Trim();
        }

        private static string Truncate(string value, int maxChars)
        {
            if (string.IsNullOrWhiteSpace(value))
            {
                return "-";
            }

            var trimmed = value.Trim();
            if (trimmed.Length <= Math.Max(8, maxChars))
            {
                return trimmed;
            }

            return trimmed.Substring(0, Math.Max(8, maxChars)) + "...";
        }

        private static string BuildCapabilityHint(BeYourEyes.Adapters.Networking.CapabilityState state)
        {
            switch (state)
            {
                case BeYourEyes.Adapters.Networking.CapabilityState.OFFLINE:
                    return "Offline mode. Network unavailable.";
                case BeYourEyes.Adapters.Networking.CapabilityState.REMOTE_STALE:
                    return "Remote stale. Waiting for updates.";
                case BeYourEyes.Adapters.Networking.CapabilityState.REMOTE_SAFE_MODE:
                    return "Remote safe mode active.";
                case BeYourEyes.Adapters.Networking.CapabilityState.LIMITED_NOT_READY:
                    return "Limited mode. Remote tools unavailable.";
                case BeYourEyes.Adapters.Networking.CapabilityState.REMOTE_THROTTLED:
                    return "Remote throttled.";
                case BeYourEyes.Adapters.Networking.CapabilityState.REMOTE_DEGRADED:
                    return "Remote degraded.";
                default:
                    return "Capabilities restored.";
            }
        }

        private static string ParseHealthStatusFromSummary(string summary)
        {
            if (string.IsNullOrWhiteSpace(summary))
            {
                return string.Empty;
            }

            var normalized = summary.Trim().ToLowerInvariant();
            if (normalized.StartsWith("gateway_safe_mode"))
            {
                return "SAFE_MODE";
            }
            if (normalized.StartsWith("gateway_throttled"))
            {
                return "THROTTLED";
            }
            if (normalized.StartsWith("gateway_degraded"))
            {
                return "DEGRADED";
            }
            if (normalized.StartsWith("gateway_waiting_client"))
            {
                return "WAITING_CLIENT";
            }
            if (normalized.StartsWith("gateway_normal"))
            {
                return "NORMAL";
            }

            return string.Empty;
        }

        private static string ParseHealthReasonFromSummary(string summary)
        {
            if (string.IsNullOrWhiteSpace(summary))
            {
                return string.Empty;
            }

            var open = summary.IndexOf('(');
            var close = summary.LastIndexOf(')');
            if (open >= 0 && close > open)
            {
                return summary.Substring(open + 1, close - open - 1).Trim();
            }

            return string.Empty;
        }
    }
}
