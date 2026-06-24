const video = document.getElementById("video");
const annotated = document.getElementById("annotated");
const canvas = document.getElementById("captureCanvas");
const liveOverlay = document.getElementById("liveOverlay");
const startCamera = document.getElementById("startCamera");
const serverCameraButton = document.getElementById("serverCameraButton");
const browserCameraButton = document.getElementById("browserCameraButton");
const serverCameraIndex = document.getElementById("serverCameraIndex");
const askButton = document.getElementById("askButton");
const micButton = document.getElementById("micButton");
const audioInputSelect = document.getElementById("audioInputSelect");
const refreshAudioDevices = document.getElementById("refreshAudioDevices");
const question = document.getElementById("question");
const assistGoal = document.getElementById("assistGoal");
const setAssistGoal = document.getElementById("setAssistGoal");
const clearAssistGoal = document.getElementById("clearAssistGoal");
const answer = document.getElementById("answer");
const actionBadge = document.getElementById("actionBadge");
const latency = document.getElementById("latency");
const evidenceList = document.getElementById("evidenceList");
const evidenceCount = document.getElementById("evidenceCount");
const safetyState = document.getElementById("safetyState");
const qualityState = document.getElementById("qualityState");
const plannerState = document.getElementById("plannerState");
const systemStatus = document.getElementById("systemStatus");
const cameraStatus = document.getElementById("cameraStatus");
const safetyLoop = document.getElementById("safetyLoop");
const reachLoop = document.getElementById("reachLoop");
const ptzAuto = document.getElementById("ptzAuto");
const audioGuide = document.getElementById("audioGuide");
const resetEvidence = document.getElementById("resetEvidence");
const voiceRate = document.getElementById("voiceRate");
const voiceRateValue = document.getElementById("voiceRateValue");
const audioGuideVolume = document.getElementById("audioGuideVolume");
const audioGuideVolumeValue = document.getElementById("audioGuideVolumeValue");

const SPEECH_RATE_KEY = "bye:speechRate";
const CAMERA_SOURCE_KEY = "bye:cameraSource";
const SERVER_CAMERA_INDEX_KEY = "bye:serverCameraIndex";
const AUDIO_INPUT_KEY = "bye:audioInputDeviceId";
const ASSIST_GOAL_KEY = "bye:assistGoal";
const PTZ_AUTO_KEY = "bye:ptzAuto";
const AUDIO_GUIDE_KEY = "bye:audioGuide";
const AUDIO_GUIDE_VOLUME_KEY = "bye:audioGuideVolume";
const CONTINUOUS_ASSIST_INTERVAL_MS = 2300;
const MAX_RECORDING_MS = 5000;
const ASR_TIMEOUT_MS = 35000;
const PTZ_MIN_INTERVAL_MS = 110;
const PTZ_TRACK_INTERVAL_MS = 85;
const TRACK_LOOP_INTERVAL_MS = 85;
const TRACKER_INIT_MIN_INTERVAL_MS = 850;
const TRACKER_DETECTOR_SWITCH_DISTANCE = 0.22;
const TRACKER_DETECTOR_REINIT_DISTANCE = 0.1;
const TRACKER_DETECTOR_CONFIRM_MS = 5200;
const AUDIO_GUIDE_MIN_INTERVAL_MS = 120;
const VIEW_REPAIR_MIN_INTERVAL_MS = 1600;
const VIEW_REPAIR_SETTLE_MS = 900;
const VIEW_REPAIR_MAX_ATTEMPTS = 2;
const PTZ_SOFT_MARGIN = { pan: 0.04, tilt: 0.14, zoom: 0.02 };
const PTZ_SIGNAL_RECOVER_MIN_INTERVAL_MS = 1800;

let stream = null;
let busy = false;
let safetyTimer = null;
let lastSafetySpeech = 0;
let reachTimer = null;
let trackerTimer = null;
let lastReachSpeech = 0;
let lastReachSpeechText = "";
let cameraMode = "none";
let streamResumeTimer = null;
let mediaRecorder = null;
let audioChunks = [];
let audioContext = null;
let recorderNode = null;
let recorderSource = null;
let recorderStream = null;
let pcmChunks = [];
let pcmInputSampleRate = 48000;
let recording = false;
let recordingTimer = null;
let currentSpeechText = "";
let speechRestartTimer = null;
let ttsAudio = null;
let ttsObjectUrl = "";
let usingLocalTts = false;
let speechSeq = 0;
let speechPending = false;
let activeAssistGoal = "";
let ptzState = {
  supported: false,
  capabilities: {},
  lastMoveAt: 0,
  scanDirection: 1,
  lastScanAt: 0,
  servoErrorX: 0,
  servoErrorY: 0,
  servoIntegralX: 0,
  servoIntegralY: 0,
  lastSignalRecoverAt: 0,
};
let viewRepairState = {
  key: "",
  attempts: 0,
  timer: null,
  lastMoveAt: 0,
};
let trackerState = {
  active: false,
  busy: false,
  bbox: null,
  label: "",
  detectorBbox: null,
  initPending: false,
  lastInitAt: 0,
  lastErrorAt: 0,
  lastTrackAt: 0,
  lostCount: 0,
  candidateKey: "",
  candidateCount: 0,
  candidateAt: 0,
};
let guideAudio = {
  ctx: null,
  master: null,
  timer: null,
  pattern: null,
  scanPan: -0.85,
  lastContactAt: 0,
  lastDangerAt: 0,
  lastPhase: "",
  lastPhaseToneAt: 0,
  lastTargetSeen: false,
};

function initVoiceRate() {
  const saved = Number(localStorage.getItem(SPEECH_RATE_KEY));
  const rate = Number.isFinite(saved) ? clampSpeechRate(saved) : 1.05;
  voiceRate.value = String(rate);
  updateVoiceRateLabel(rate);
}

function getSpeechRate() {
  return clampSpeechRate(Number(voiceRate.value || 1.05));
}

function clampSpeechRate(rate) {
  return Math.min(1.8, Math.max(0.7, rate));
}

function updateVoiceRateLabel(rate = getSpeechRate()) {
  voiceRateValue.textContent = `${rate.toFixed(2)}x`;
}

function initAudioGuideSettings() {
  if (!audioGuideVolume) return;
  const saved = Number(localStorage.getItem(AUDIO_GUIDE_VOLUME_KEY));
  const volume = Number.isFinite(saved) ? clampGuideVolume(saved) : 0.75;
  audioGuideVolume.value = String(volume);
  updateAudioGuideVolumeLabel(volume);
}

function getAudioGuideVolume() {
  return clampGuideVolume(Number(audioGuideVolume?.value || 0.75));
}

function clampGuideVolume(volume) {
  return Math.min(1, Math.max(0, volume));
}

function updateAudioGuideVolumeLabel(volume = getAudioGuideVolume()) {
  if (audioGuideVolumeValue) audioGuideVolumeValue.textContent = `${Math.round(volume * 100)}%`;
}

function applyAudioGuideVolume() {
  if (guideAudio.master) {
    guideAudio.master.gain.setTargetAtTime(0.25 * getAudioGuideVolume(), guideAudio.ctx.currentTime, 0.025);
  }
}

function speechIsActive() {
  const localPlaying = ttsAudio && !ttsAudio.paused && !ttsAudio.ended;
  const browserSpeaking =
    "speechSynthesis" in window &&
    (window.speechSynthesis.speaking || window.speechSynthesis.pending);
  return Boolean(speechPending || localPlaying || browserSpeaking);
}

function initAssistGoal() {
  activeAssistGoal = localStorage.getItem(ASSIST_GOAL_KEY) || "";
  renderAssistGoal();
}

function renderAssistGoal() {
  assistGoal.textContent = activeAssistGoal || "未设置";
  assistGoal.title = activeAssistGoal || "";
}

function saveAssistGoal(text) {
  activeAssistGoal = String(text || "").trim();
  if (activeAssistGoal) {
    localStorage.setItem(ASSIST_GOAL_KEY, activeAssistGoal);
  } else {
    localStorage.removeItem(ASSIST_GOAL_KEY);
  }
  renderAssistGoal();
  return activeAssistGoal;
}

function currentAssistGoal() {
  return activeAssistGoal || question.value.trim();
}

async function loadAudioDevices(requestPermission = false) {
  if (!navigator.mediaDevices?.enumerateDevices) {
    audioInputSelect.innerHTML = '<option value="">当前浏览器不支持麦克风列表</option>';
    audioInputSelect.disabled = true;
    refreshAudioDevices.disabled = true;
    return;
  }

  let permissionStream = null;
  if (requestPermission && navigator.mediaDevices.getUserMedia) {
    try {
      permissionStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (err) {
      answer.textContent = `麦克风权限不可用：${err.message}`;
    } finally {
      if (permissionStream) permissionStream.getTracks().forEach((track) => track.stop());
    }
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const audioInputs = devices.filter((device) => device.kind === "audioinput");
  const preferred = localStorage.getItem(AUDIO_INPUT_KEY) || audioInputSelect.value || "";
  audioInputSelect.innerHTML = "";
  audioInputSelect.appendChild(new Option("系统默认麦克风", ""));
  audioInputs.forEach((device, index) => {
    const label = device.label || `麦克风 ${index + 1}`;
    audioInputSelect.appendChild(new Option(label, device.deviceId));
  });
  if (audioInputs.some((device) => device.deviceId === preferred)) {
    audioInputSelect.value = preferred;
  } else {
    audioInputSelect.value = "";
    localStorage.removeItem(AUDIO_INPUT_KEY);
  }
  audioInputSelect.disabled = false;
  refreshAudioDevices.disabled = false;
}

function selectedAudioConstraints() {
  const deviceId = audioInputSelect.value || "";
  const constraints = {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  };
  if (deviceId) constraints.deviceId = { exact: deviceId };
  return constraints;
}

async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    systemStatus.textContent = data.deepseek_enabled
      ? `DeepSeek ${data.deepseek_model}`
      : "本地规则模式";
    if (
      data.camera?.index !== undefined &&
      document.activeElement !== serverCameraIndex &&
      !localStorage.getItem(SERVER_CAMERA_INDEX_KEY)
    ) {
      serverCameraIndex.value = String(data.camera.index);
      localStorage.setItem(SERVER_CAMERA_INDEX_KEY, String(data.camera.index));
    }
  } catch (err) {
    systemStatus.textContent = "后端未连接";
  }
}

async function openCamera() {
  const source = localStorage.getItem(CAMERA_SOURCE_KEY) || "server";
  if (source === "browser") {
    await openBrowserCamera();
  } else {
    await startServerCamera("default backend camera");
  }
}

async function openBrowserCamera() {
  try {
    stopBrowserCamera();
    stopServerStream();
    await stopServerCamera();
    stream = await openBrowserVideoStream();
    cameraMode = "browser";
    localStorage.setItem(CAMERA_SOURCE_KEY, "browser");
    video.srcObject = stream;
    video.style.display = "block";
    annotated.style.display = "none";
    clearLiveOverlay();
    setCameraSourceActive();
    await initializePtzControl();
    cameraStatus.textContent = ptzState.supported
      ? "浏览器摄像头运行中，云台可控"
      : "浏览器摄像头运行中";
  } catch (err) {
    cameraStatus.textContent = `浏览器摄像头不可用，已切回后端：${err.message}`;
    await startServerCamera(err.message);
  }
}

async function openBrowserVideoStream() {
  const base = { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "environment" };
  try {
    return await navigator.mediaDevices.getUserMedia({
      video: { ...base, pan: true, tilt: true, zoom: true },
      audio: false,
    });
  } catch (err) {
    return await navigator.mediaDevices.getUserMedia({
      video: base,
      audio: false,
    });
  }
}

function browserVideoTrack() {
  return stream?.getVideoTracks?.()[0] || null;
}

async function initializePtzControl() {
  ptzState = {
    supported: false,
    capabilities: {},
    lastMoveAt: 0,
    scanDirection: 1,
    lastScanAt: 0,
    servoErrorX: 0,
    servoErrorY: 0,
    servoIntegralX: 0,
    servoIntegralY: 0,
    lastSignalRecoverAt: 0,
  };
  const track = browserVideoTrack();
  if (!track || !track.getCapabilities) return;
  const capabilities = track.getCapabilities();
  const supported = Boolean(capabilities.pan || capabilities.tilt || capabilities.zoom);
  ptzState.supported = supported;
  ptzState.capabilities = capabilities || {};
}

function stopServerStream() {
  if (streamResumeTimer) {
    window.clearTimeout(streamResumeTimer);
    streamResumeTimer = null;
  }
  annotated.removeAttribute("src");
}

async function stopServerCamera() {
  try {
    await fetch("/api/server-camera/stop", { method: "POST" });
  } catch (err) {
    // The browser camera can still work if this request races with a server restart.
  }
}

async function startServerCamera(reason = "") {
  stopBrowserCamera();
  cameraMode = "server";
  localStorage.setItem(CAMERA_SOURCE_KEY, "server");
  video.style.display = "none";
  annotated.style.display = "block";
  setCameraSourceActive();
  await applyServerCameraIndex(false);
  cameraStatus.textContent = reason ? "后端摄像头运行中" : "后端摄像头运行中";
  startServerStream();
}

function stopBrowserCamera() {
  if (stream) {
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }
  ptzState.supported = false;
  video.srcObject = null;
  clearLiveOverlay();
  stopTrackerLoop(true);
}

function setCameraSourceActive() {
  serverCameraButton.classList.toggle("active", cameraMode === "server");
  browserCameraButton.classList.toggle("active", cameraMode === "browser");
}

async function applyServerCameraIndex(restartStream = true) {
  const index = Math.max(0, Math.min(10, Number(serverCameraIndex.value || 0)));
  serverCameraIndex.value = String(index);
  localStorage.setItem(SERVER_CAMERA_INDEX_KEY, String(index));
  const res = await fetch("/api/server-camera/select", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ index }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text);
  }
  const data = await res.json();
  cameraStatus.textContent = data.camera?.error
    ? `后端摄像头 ${index} 错误：${data.camera.error}`
    : `后端摄像头 ${index} 运行中`;
  if (restartStream && cameraMode === "server") startServerStream();
}

function startServerStream() {
  if (streamResumeTimer) {
    window.clearTimeout(streamResumeTimer);
    streamResumeTimer = null;
  }
  annotated.src = `/api/server-camera/stream.mjpg?ts=${Date.now()}`;
  clearLiveOverlay();
}

function resumeServerStreamSoon(delay = 1600) {
  if (cameraMode !== "server") return;
  if (streamResumeTimer) window.clearTimeout(streamResumeTimer);
  streamResumeTimer = window.setTimeout(() => {
    if (!busy && cameraMode === "server") startServerStream();
  }, delay);
}

function captureFrame() {
  if (cameraMode === "none") {
    startServerCamera("auto fallback").catch((err) => {
      cameraStatus.textContent = `启动后端摄像头失败：${err.message}`;
    });
    return "server_camera";
  }
  if (cameraMode === "server") {
    return "server_camera";
  }
  if (!stream || video.readyState < 2) {
    startServerCamera("browser camera is not ready").catch((err) => {
      cameraStatus.textContent = `启动后端摄像头失败：${err.message}`;
    });
    return "server_camera";
  }
  return captureBrowserFrame(0, 0.88).imageData;
}

function captureBrowserFrame(maxWidth = 0, quality = 0.82, includeSignal = false) {
  const srcW = video.videoWidth || 1280;
  const srcH = video.videoHeight || 720;
  const scale = maxWidth && srcW > maxWidth ? maxWidth / srcW : 1;
  const w = Math.max(1, Math.round(srcW * scale));
  const h = Math.max(1, Math.round(srcH * scale));
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, w, h);
  const result = {
    imageData: canvas.toDataURL("image/jpeg", quality),
    width: w,
    height: h,
    scaleX: w / Math.max(1, srcW),
    scaleY: h / Math.max(1, srcH),
    sourceWidth: srcW,
    sourceHeight: srcH,
  };
  if (includeSignal) result.signal = estimateCanvasSignal(ctx, w, h);
  return result;
}

function estimateCanvasSignal(ctx, width, height) {
  try {
    const image = ctx.getImageData(0, 0, width, height).data;
    const strideX = Math.max(1, Math.floor(width / 32));
    const strideY = Math.max(1, Math.floor(height / 18));
    let count = 0;
    let sum = 0;
    let sumSq = 0;
    for (let y = 0; y < height; y += strideY) {
      for (let x = 0; x < width; x += strideX) {
        const offset = (y * width + x) * 4;
        const lum = 0.2126 * image[offset] + 0.7152 * image[offset + 1] + 0.0722 * image[offset + 2];
        count += 1;
        sum += lum;
        sumSq += lum * lum;
      }
    }
    const mean = count ? sum / count : 0;
    const variance = count ? Math.max(0, sumSq / count - mean * mean) : 0;
    return { mean, contrast: Math.sqrt(variance), usable: mean > 6 && Math.sqrt(variance) > 2.2 };
  } catch (err) {
    return { mean: 255, contrast: 255, usable: true };
  }
}

async function analyze(mode = "ask", overrideQuestion = "") {
  if (busy) return;
  busy = true;
  const started = performance.now();
  const backgroundMode = mode === "auto_safety" || mode === "auto_reach" || mode === "auto_assist";
  if (!backgroundMode) setButtonsDisabled(true);
  try {
    const imageData = captureFrame();
    const q = overrideQuestion || question.value.trim();
    if (!q && !["safety", "auto_safety", "describe"].includes(mode)) {
      question.value = defaultQuestion(mode);
    }
    const payload = {
      image_data: imageData,
      question: q || defaultQuestion(mode),
      mode,
    };
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text);
    }
    const data = await res.json();
    renderResult(data, Math.round(performance.now() - started), mode);
  } catch (err) {
    if (!backgroundMode) {
      answer.textContent = `出错：${err.message}`;
      actionBadge.textContent = "错误";
    }
  } finally {
    if (!backgroundMode) setButtonsDisabled(false);
    busy = false;
  }
}

function setButtonsDisabled(disabled) {
  document.querySelectorAll("button").forEach((button) => {
    if (button.id !== "startCamera") button.disabled = disabled;
  });
}

function defaultQuestion(mode) {
  if (mode === "auto_assist") return defaultQuestion("ask");
  if (mode === "ocr") return "请读出画面里的文字";
  if (mode === "safety" || mode === "auto_safety") return "前方是否有明显障碍？";
  if (mode === "gesture") return "我的手是什么手势？";
  if (mode === "auto_reach" || mode === "reach") return "引导我的手拿起红色罐子";
  if (mode === "memory") return "刚才你看到过什么？";
  if (mode === "find") return "帮我找水杯";
  return "前面有什么？";
}

function renderResult(data, elapsedMs, mode) {
  const keepLivePreview = mode === "auto_safety" || mode === "auto_reach" || mode === "auto_assist";
  if (!keepLivePreview) {
    annotated.src = data.annotated_image;
    annotated.style.display = "block";
    if (cameraMode === "server") {
      resumeServerStreamSoon(data.action === "safety_alert" ? 650 : 1200);
    } else if (cameraMode === "browser") {
      resumeBrowserPreviewSoon(1200);
    }
  } else if (cameraMode === "browser") {
    annotated.style.display = "none";
    drawLiveOverlay(data);
  }
  actionBadge.textContent = actionLabel(data.action);
  actionBadge.className = `state-${data.action}`;
  answer.textContent = data.speech;
  latency.textContent = `${data.stats.latency_ms || elapsedMs} ms`;
  safetyState.textContent = safetyLabel(data.safety.risk_level);
  safetyState.className = `state-${data.safety.risk_level}`;
  qualityState.textContent = data.quality.usable ? "可用" : "需重观察";
  qualityState.className = data.quality.usable ? "state-low" : "state-medium";
  const phase = data.agent?.phase_zh || data.plan?.agent?.phase_zh || "";
  const targetKind = data.agent?.target_kind || data.plan?.agent?.target_kind || "";
  const targetPosition = data.agent?.target_position || data.plan?.agent?.target_position || "";
  const targetLock = data.agent?.target_locked || data.plan?.agent?.target_locked
    ? `${targetKind === "weak" ? "疑似目标" : "确认目标"}${targetPosition ? `@${targetPosition}` : ""}`
    : "";
  plannerState.textContent = [phase, targetLock, data.planner || data.plan.planner || "unknown"]
    .filter(Boolean)
    .join(" / ");
  renderEvidence(data.evidence || []);
  updateTrackerTarget(data, mode);
  autoControlPtz(data, mode).catch(() => {});
  updateAudioGuide(data, mode);
  if (mode === "auto_reach" || mode === "auto_assist") {
    maybeSpeakReach(data);
  } else if (mode !== "auto_safety") {
    speak(data.speech);
  } else if (data.action === "safety_alert" || data.action === "reobserve") {
    const now = Date.now();
    if (now - lastSafetySpeech > 6500) {
      speak(data.speech);
      lastSafetySpeech = now;
    }
  }
}

function maybeSpeakReach(data) {
  const now = Date.now();
  const speech = String(data.speech || "").trim();
  if (!speech) return;
  if (data.agent && data.agent.should_speak === false) return;
  const urgent = data.action === "safety_alert";
  if (!urgent && speechIsActive()) return;
  const changed = speech !== lastReachSpeechText;
  const cooldown = urgent ? 1600 : changed ? 2200 : 5600;
  if (now - lastReachSpeech < cooldown) return;
  speak(speech, { interrupt: urgent });
  lastReachSpeech = now;
  lastReachSpeechText = speech;
}

function updateAudioGuide(data, mode) {
  if (!audioGuide?.checked || (mode !== "auto_assist" && mode !== "auto_reach")) {
    stopAudioGuide();
    return;
  }
  if (data.action === "safety_alert" || data.safety?.blocking) {
    playDangerGuide();
    setGuidePattern({
      kind: "danger",
      pan: 0,
      frequency: 260,
      durationMs: 120,
      intervalMs: 430,
      gain: 0.12,
      wave: "square",
    });
    return;
  }

  handleGuidePhase(data);
  const pattern = buildGuidePattern(data);
  if (!pattern) {
    stopAudioGuide();
    return;
  }
  setGuidePattern(pattern);
}

function handleGuidePhase(data) {
  const agent = data.agent || data.plan?.agent || {};
  const phase = String(agent.phase || "");
  const hasTarget = Boolean(primaryTargetEvidence(data));
  if (!phase) return;

  if (guideAudio.lastTargetSeen && !hasTarget && Date.now() - guideAudio.lastPhaseToneAt > 1400) {
    playGuideEarcon([
      { frequency: 540, durationMs: 70, pan: -0.35, gain: 0.07 },
      { frequency: 360, durationMs: 110, pan: 0.35, gain: 0.075 },
    ]);
    guideAudio.lastPhaseToneAt = Date.now();
  }
  guideAudio.lastTargetSeen = hasTarget;

  if (phase === guideAudio.lastPhase) return;
  guideAudio.lastPhase = phase;
  const now = Date.now();
  if (now - guideAudio.lastPhaseToneAt < 550) return;
  guideAudio.lastPhaseToneAt = now;

  if (phase === "search_target" || phase === "confirm_target") {
    playGuideEarcon([{ frequency: 430, durationMs: 90, pan: 0, gain: 0.075 }]);
  } else if (phase === "bring_hand") {
    playGuideEarcon([
      { frequency: 560, durationMs: 70, pan: -0.25, gain: 0.06 },
      { frequency: 560, durationMs: 70, pan: 0.25, gain: 0.06 },
    ]);
  } else if (phase === "align_hand" || phase === "approach_target") {
    playGuideEarcon([{ frequency: 650, durationMs: 70, pan: 0, gain: 0.065 }]);
  } else if (phase === "prepare_grasp" || phase === "close_fingers") {
    playGuideEarcon([
      { frequency: 740, durationMs: 55, pan: 0, gain: 0.075 },
      { frequency: 900, durationMs: 65, pan: 0, gain: 0.08 },
    ]);
  } else if (phase === "hold" || phase === "lift") {
    playGuideEarcon([
      { frequency: 760, durationMs: 65, pan: 0, gain: 0.085 },
      { frequency: 1040, durationMs: 90, pan: 0, gain: 0.085 },
    ]);
  }
}

function buildGuidePattern(data) {
  const agent = data.agent || data.plan?.agent || {};
  const phase = String(agent.phase || "");
  const relation = agent.hand_target || {};
  const target = primaryTargetEvidence(data);

  if (relation.contact) {
    playContactGuide();
    return {
      kind: "contact",
      pan: 0,
      frequency: 720,
      durationMs: 55,
      intervalMs: 1500,
      gain: 0.055,
      wave: "sine",
    };
  }

  if (Number.isFinite(Number(relation.distance))) {
    return relationGuidePattern(relation);
  }

  if (target?.bbox?.length >= 4) {
    const pan = targetPanFromFrame(target.bbox);
    const searching = phase === "search_target" || phase === "confirm_target";
    return {
      kind: phase === "bring_hand" ? "bring_hand" : "target",
      pan,
      frequency: searching ? 480 : 560,
      durationMs: 70,
      intervalMs: searching ? 820 : 650,
      gain: 0.065,
      wave: "sine",
    };
  }

  return {
    kind: "scan",
    pan: 0,
    frequency: 410,
    durationMs: 65,
    intervalMs: 950,
    gain: 0.055,
    wave: "sine",
    scan: true,
  };
}

function relationGuidePattern(relation) {
  const distance = clampNumber(Number(relation.distance || 0.35), 0.035, 0.36);
  const t = clampNumber((distance - 0.035) / 0.325, 0, 1);
  const normDx = Number(relation.norm_dx || 0);
  const normDy = Number(relation.norm_dy || 0);
  const pan = clampNumber(normDx * 5.5, -1, 1);
  const verticalShift = normDy < -0.1 ? 130 : normDy > 0.1 ? -110 : 0;
  const movingAwayShift = relation.moving_away ? -120 : 0;
  const sameDepth = relation.same_depth_layer !== false;
  if (!sameDepth) {
    return {
      kind: "depth",
      pan,
      frequency: 315,
      durationMs: 90,
      intervalMs: 620,
      gain: 0.075,
      wave: "triangle",
    };
  }
  return {
    kind: relation.near ? "near" : "approach",
    pan,
    frequency: clampNumber(790 - t * 330 + verticalShift + movingAwayShift, 320, 920),
    durationMs: relation.near ? 52 : 68,
    intervalMs: Math.max(AUDIO_GUIDE_MIN_INTERVAL_MS, Math.round(180 + t * 760)),
    gain: relation.near ? 0.075 : 0.065,
    wave: "sine",
  };
}

function primaryTargetEvidence(data) {
  const evidence = data.evidence || [];
  return evidence
    .filter((item) => item.type === "object" && item.bbox?.length >= 4)
    .filter((item) => isTargetEvidence(item))
    .sort((a, b) => targetEvidenceScore(b) - targetEvidenceScore(a))[0] || null;
}

function primaryHandEvidence(data) {
  const evidence = data.evidence || [];
  return evidence
    .filter((item) => item.type === "hand" && item.bbox?.length >= 4)
    .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))[0] || null;
}

function targetEvidenceScore(item) {
  const attrs = item.attributes || {};
  let score = Number(item.confidence || 0);
  if (attrs.agent_primary_target) score += 3.0;
  if (attrs.agent_locked) score += 2.2;
  if (attrs.target_match) score += 1.8;
  if (attrs.weak_target_match) score += 0.9;
  if (attrs.tracked_from_memory) score -= 0.2;
  return score;
}

function isTargetEvidence(item) {
  const attrs = item.attributes || {};
  return Boolean(
    attrs.agent_primary_target ||
    attrs.agent_locked ||
    attrs.target_match ||
    attrs.weak_target_match
  );
}

function targetPanFromFrame(bbox) {
  const frame = currentVideoFrameSize();
  const cx = (Number(bbox[0]) + Number(bbox[2])) / 2;
  return clampNumber((cx - frame.width / 2) / Math.max(1, frame.width / 2), -1, 1);
}

function drawLiveOverlay(data) {
  if (!liveOverlay || cameraMode !== "browser") return;
  const ctx = liveOverlay.getContext("2d");
  if (!ctx) return;
  const rect = liveOverlay.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (liveOverlay.width !== width || liveOverlay.height !== height) {
    liveOverlay.width = width;
    liveOverlay.height = height;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const frame = currentVideoFrameSize();
  const viewport = containedViewport(rect.width, rect.height, frame.width, frame.height);
  const evidence = data.evidence || [];
  const target = primaryTargetEvidence(data);
  const hand = primaryHandEvidence(data);
  for (const item of evidence) {
    if (item === target || item === hand || !item.bbox?.length) continue;
    if (item.type !== "object" || !item.attributes?.depth_obstacle) continue;
    drawOverlayBox(ctx, viewport, frame, item.bbox, "#c7b300", item.attributes?.label_zh || item.label, 0.82);
  }
  if (hand?.bbox?.length) {
    drawOverlayBox(ctx, viewport, frame, hand.bbox, "#2b7fff", "hand", 0.9);
  }
  if (target?.bbox?.length) {
    drawOverlayBox(ctx, viewport, frame, target.bbox, "#27c167", target.attributes?.label_zh || target.label, 1);
    drawOverlayCenter(ctx, viewport, frame, target.bbox, "#27c167");
  }
}

function clearLiveOverlay() {
  if (!liveOverlay) return;
  const ctx = liveOverlay.getContext("2d");
  if (ctx) ctx.clearRect(0, 0, liveOverlay.width, liveOverlay.height);
}

function containedViewport(viewWidth, viewHeight, frameWidth, frameHeight) {
  const scale = Math.min(viewWidth / Math.max(1, frameWidth), viewHeight / Math.max(1, frameHeight));
  const width = frameWidth * scale;
  const height = frameHeight * scale;
  return {
    x: (viewWidth - width) / 2,
    y: (viewHeight - height) / 2,
    width,
    height,
    scale,
  };
}

function mapFramePoint(viewport, x, y) {
  return [viewport.x + Number(x) * viewport.scale, viewport.y + Number(y) * viewport.scale];
}

function drawOverlayBox(ctx, viewport, frame, bbox, color, label, alpha = 1) {
  const [x1, y1] = mapFramePoint(viewport, bbox[0], bbox[1]);
  const [x2, y2] = mapFramePoint(viewport, bbox[2], bbox[3]);
  const w = Math.max(1, x2 - x1);
  const h = Math.max(1, y2 - y1);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.strokeRect(x1, y1, w, h);
  if (label) {
    ctx.font = "600 14px Segoe UI, Microsoft YaHei, sans-serif";
    const text = String(label).slice(0, 28);
    const metrics = ctx.measureText(text);
    const labelWidth = Math.min(w, metrics.width + 12);
    const labelY = Math.max(0, y1 - 24);
    ctx.globalAlpha = 0.9;
    ctx.fillRect(x1, labelY, Math.max(44, labelWidth), 22);
    ctx.fillStyle = "#07120d";
    ctx.globalAlpha = 1;
    ctx.fillText(text, x1 + 6, labelY + 16);
  }
  ctx.restore();
}

function drawOverlayCenter(ctx, viewport, frame, bbox, color) {
  const cx = (Number(bbox[0]) + Number(bbox[2])) / 2;
  const cy = (Number(bbox[1]) + Number(bbox[3])) / 2;
  const [x, y] = mapFramePoint(viewport, cx, cy);
  const [fx, fy] = mapFramePoint(viewport, frame.width / 2, frame.height / 2);
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.globalAlpha = 0.95;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(x, y, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(fx - 10, fy);
  ctx.lineTo(fx + 10, fy);
  ctx.moveTo(fx, fy - 10);
  ctx.lineTo(fx, fy + 10);
  ctx.stroke();
  ctx.setLineDash([5, 6]);
  ctx.beginPath();
  ctx.moveTo(fx, fy);
  ctx.lineTo(x, y);
  ctx.stroke();
  ctx.restore();
}

function updateTrackerTarget(data, mode) {
  if (mode !== "auto_assist" && mode !== "auto_reach") return;
  if (cameraMode !== "browser" || !ptzAuto?.checked) return;
  const target = primaryTargetEvidence(data);
  if (!target?.bbox?.length) return;
  const label = target.attributes?.label_zh || target.label || "";
  const now = Date.now();
  const strongTarget = target.attributes?.target_match || target.attributes?.agent_primary_target;
  const labelChanged = String(label) !== String(trackerState.label || "");
  const trackerFresh = trackerState.active && trackerState.bbox?.length && now - trackerState.lastTrackAt < 2200;
  if (trackerFresh) {
    const iou = bboxIou(target.bbox, trackerState.bbox);
    const distance = bboxCenterDistance(target.bbox, trackerState.bbox);
    if (iou < 0.18 && distance > 0.12) {
      startTrackerLoop();
      return;
    }
    trackerState.detectorBbox = target.bbox.map(Number);
    if (!trackerState.label) trackerState.label = String(label);
    startTrackerLoop();
    return;
  }
  if (!strongTarget && Number(target.confidence || 0) < 0.22) return;
  const distanceToTrack = trackerFresh ? bboxCenterDistance(target.bbox, trackerState.bbox) : 0;
  const farSwitch = trackerFresh && !labelChanged && distanceToTrack > TRACKER_DETECTOR_SWITCH_DISTANCE;
  if (farSwitch && !confirmDetectorCandidate(target, label, now)) {
    startTrackerLoop();
    return;
  }
  const changed =
    !trackerState.detectorBbox ||
    bboxCenterDistance(target.bbox, trackerState.detectorBbox) > TRACKER_DETECTOR_REINIT_DISTANCE ||
    labelChanged ||
    farSwitch;
  trackerState.detectorBbox = target.bbox.map(Number);
  trackerState.label = String(label);
  if (!trackerState.active || changed || now - trackerState.lastInitAt > 4200) {
    trackerState.initPending = now - trackerState.lastInitAt > TRACKER_INIT_MIN_INTERVAL_MS;
  }
  startTrackerLoop();
}

function bboxIou(a, b) {
  if (!a?.length || !b?.length) return 0;
  const ax1 = Number(a[0]), ay1 = Number(a[1]), ax2 = Number(a[2]), ay2 = Number(a[3]);
  const bx1 = Number(b[0]), by1 = Number(b[1]), bx2 = Number(b[2]), by2 = Number(b[3]);
  const ix1 = Math.max(ax1, bx1);
  const iy1 = Math.max(ay1, by1);
  const ix2 = Math.min(ax2, bx2);
  const iy2 = Math.min(ay2, by2);
  const inter = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1);
  const areaA = Math.max(0, ax2 - ax1) * Math.max(0, ay2 - ay1);
  const areaB = Math.max(0, bx2 - bx1) * Math.max(0, by2 - by1);
  const union = areaA + areaB - inter;
  return union > 0 ? inter / union : 0;
}

function confirmDetectorCandidate(target, label, now) {
  const key = detectorCandidateKey(target, label);
  if (key && key === trackerState.candidateKey && now - trackerState.candidateAt < TRACKER_DETECTOR_CONFIRM_MS) {
    trackerState.candidateCount += 1;
  } else {
    trackerState.candidateKey = key;
    trackerState.candidateCount = 1;
  }
  trackerState.candidateAt = now;
  return trackerState.candidateCount >= 2;
}

function detectorCandidateKey(target, label) {
  const bbox = target?.bbox || [];
  if (bbox.length < 4) return "";
  const frame = currentVideoFrameSize();
  const cx = (Number(bbox[0]) + Number(bbox[2])) / 2;
  const cy = (Number(bbox[1]) + Number(bbox[3])) / 2;
  const bucketX = Math.round(cx / Math.max(48, frame.width * 0.12));
  const bucketY = Math.round(cy / Math.max(36, frame.height * 0.12));
  return `${String(label || target.label || "")}:${bucketX}:${bucketY}`;
}

function bboxCenterDistance(a, b) {
  const frame = currentVideoFrameSize();
  const acx = (Number(a[0]) + Number(a[2])) / 2;
  const acy = (Number(a[1]) + Number(a[3])) / 2;
  const bcx = (Number(b[0]) + Number(b[2])) / 2;
  const bcy = (Number(b[1]) + Number(b[3])) / 2;
  const dx = (acx - bcx) / Math.max(1, frame.width);
  const dy = (acy - bcy) / Math.max(1, frame.height);
  return Math.hypot(dx, dy);
}

function startTrackerLoop() {
  if (trackerTimer || cameraMode !== "browser") return;
  trackerTimer = window.setInterval(() => {
    tickTrackerLoop().catch(() => {});
  }, TRACK_LOOP_INTERVAL_MS);
}

function stopTrackerLoop(resetRemote = false) {
  if (trackerTimer) {
    window.clearInterval(trackerTimer);
    trackerTimer = null;
  }
  trackerState.active = false;
  trackerState.busy = false;
  trackerState.bbox = null;
  trackerState.detectorBbox = null;
  trackerState.initPending = false;
  trackerState.lastTrackAt = 0;
  trackerState.lostCount = 0;
  trackerState.candidateKey = "";
  trackerState.candidateCount = 0;
  trackerState.candidateAt = 0;
  if (resetRemote) {
    fetch("/api/tracker/reset", { method: "POST" }).catch(() => {});
  }
}

async function tickTrackerLoop() {
  if (trackerState.busy || cameraMode !== "browser" || !reachLoop.checked || !ptzAuto?.checked) return;
  if (Date.now() - trackerState.lastErrorAt < 1200) return;
  if (!trackerState.detectorBbox && !trackerState.active) return;
  const track = browserVideoTrack();
  if (!track?.applyConstraints || !track.getSettings) return;
  const capture = captureBrowserFrame(480, 0.62, true);
  if (capture.signal && !capture.signal.usable) {
    await recoverPtzFromSignalLoss(track, ptzState.capabilities || track.getCapabilities?.() || {}, Date.now());
    return;
  }
  const payload = {
    image_data: capture.imageData,
    label: trackerState.label,
  };
  if (trackerState.initPending && trackerState.detectorBbox) {
    payload.bbox = scaleBbox(trackerState.detectorBbox, capture.scaleX, capture.scaleY);
    trackerState.initPending = false;
    trackerState.lastInitAt = Date.now();
  }
  trackerState.busy = true;
  try {
    const res = await fetch("/api/track", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      trackerState.lastErrorAt = Date.now();
      return;
    }
    const data = await res.json();
    if (data.state === "lost") {
      trackerState.lostCount += 1;
      if (trackerState.lostCount >= 3) trackerState.active = false;
    }
    if (!data.bbox?.length) return;
    const bbox = scaleBbox(data.bbox, 1 / Math.max(capture.scaleX, 1e-6), 1 / Math.max(capture.scaleY, 1e-6));
    trackerState.active = true;
    trackerState.lostCount = 0;
    trackerState.lastTrackAt = Date.now();
    trackerState.bbox = bbox;
    drawTrackerOverlay(bbox, data.label || trackerState.label);
    const capabilities = ptzState.capabilities || track.getCapabilities?.() || {};
    await servoPtzToBox(track, capabilities, bbox, currentVideoFrameSize(), Date.now(), 0.035);
  } finally {
    trackerState.busy = false;
  }
}

function scaleBbox(bbox, sx, sy) {
  return [
    Number(bbox[0]) * sx,
    Number(bbox[1]) * sy,
    Number(bbox[2]) * sx,
    Number(bbox[3]) * sy,
  ];
}

function drawTrackerOverlay(bbox, label) {
  if (!liveOverlay || cameraMode !== "browser") return;
  const ctx = liveOverlay.getContext("2d");
  if (!ctx) return;
  const rect = liveOverlay.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * dpr));
  const height = Math.max(1, Math.round(rect.height * dpr));
  if (liveOverlay.width !== width || liveOverlay.height !== height) {
    liveOverlay.width = width;
    liveOverlay.height = height;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const frame = currentVideoFrameSize();
  const viewport = containedViewport(rect.width, rect.height, frame.width, frame.height);
  drawOverlayBox(ctx, viewport, frame, bbox, "#27c167", label || "tracked", 1);
  drawOverlayCenter(ctx, viewport, frame, bbox, "#27c167");
}

function setGuidePattern(pattern) {
  if (!audioGuide?.checked || !reachLoop.checked) {
    stopAudioGuide();
    return;
  }
  const previous = guideAudio.pattern;
  guideAudio.pattern = pattern;
  const changed =
    !previous ||
    previous.kind !== pattern.kind ||
    Math.abs(Number(previous.pan || 0) - Number(pattern.pan || 0)) > 0.22 ||
    Math.abs(Number(previous.frequency || 0) - Number(pattern.frequency || 0)) > 120 ||
    Math.abs(Number(previous.intervalMs || 0) - Number(pattern.intervalMs || 0)) > 220;
  if (changed || !guideAudio.timer) {
    if (guideAudio.timer) window.clearTimeout(guideAudio.timer);
    scheduleGuidePulse(0);
  }
}

function scheduleGuidePulse(delayMs) {
  guideAudio.timer = window.setTimeout(async () => {
    guideAudio.timer = null;
    if (!audioGuide?.checked || !reachLoop.checked || !guideAudio.pattern) {
      stopAudioGuide();
      return;
    }
    await resumeGuideAudio();
    playGuidePulse(guideAudio.pattern);
    const interval = Math.max(AUDIO_GUIDE_MIN_INTERVAL_MS, Number(guideAudio.pattern.intervalMs || 600));
    scheduleGuidePulse(interval);
  }, Math.max(0, delayMs));
}

function stopAudioGuide() {
  if (guideAudio.timer) {
    window.clearTimeout(guideAudio.timer);
    guideAudio.timer = null;
  }
  guideAudio.pattern = null;
}

function resetAudioGuideState() {
  stopAudioGuide();
  guideAudio.lastPhase = "";
  guideAudio.lastTargetSeen = false;
  guideAudio.lastContactAt = 0;
}

async function resumeGuideAudio() {
  if (!audioGuide?.checked) return null;
  const ctx = ensureGuideAudioContext();
  if (ctx?.state === "suspended") {
    try {
      await ctx.resume();
    } catch (err) {
      // Browsers only unlock audio after a user gesture; the next click will retry.
    }
  }
  return ctx;
}

function ensureGuideAudioContext() {
  if (guideAudio.ctx) return guideAudio.ctx;
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) return null;
  const ctx = new AudioContextClass();
  const master = ctx.createGain();
  master.gain.value = 0.25 * getAudioGuideVolume();
  master.connect(ctx.destination);
  guideAudio.ctx = ctx;
  guideAudio.master = master;
  return ctx;
}

function playGuidePulse(pattern) {
  const ctx = guideAudio.ctx;
  if (!ctx || ctx.state !== "running" || !guideAudio.master) return;
  const now = ctx.currentTime;
  const duration = clampNumber(Number(pattern.durationMs || 70), 35, 180) / 1000;
  const pan = pattern.scan ? nextScanPan() : clampNumber(Number(pattern.pan || 0), -1, 1);
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  const panner = ctx.createStereoPanner ? ctx.createStereoPanner() : null;
  osc.type = pattern.wave || "sine";
  osc.frequency.setValueAtTime(clampNumber(Number(pattern.frequency || 520), 180, 1200), now);
  const duck = speechIsActive() ? 0.36 : 1;
  const peakGain = clampNumber(Number(pattern.gain || 0.06) * duck, 0.012, 0.16);
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(peakGain, now + 0.018);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
  if (panner) {
    panner.pan.setValueAtTime(pan, now);
    osc.connect(gain);
    gain.connect(panner);
    panner.connect(guideAudio.master);
  } else {
    osc.connect(gain);
    gain.connect(guideAudio.master);
  }
  osc.start(now);
  osc.stop(now + duration + 0.025);
}

function playGuideEarcon(steps) {
  resumeGuideAudio().then(() => {
    steps.forEach((step, index) => {
      window.setTimeout(() => playGuidePulse(step), index * 105);
    });
  });
}

function playDangerGuide() {
  const now = Date.now();
  if (now - guideAudio.lastDangerAt < 1200) return;
  guideAudio.lastDangerAt = now;
  playGuideEarcon([
    { pan: 0, frequency: 230, durationMs: 110, gain: 0.13, wave: "square" },
    { pan: 0, frequency: 230, durationMs: 110, gain: 0.13, wave: "square" },
  ]);
}

function playContactGuide() {
  const now = Date.now();
  if (now - guideAudio.lastContactAt < 1800) return;
  guideAudio.lastContactAt = now;
  resumeGuideAudio().then(() => {
    playGuidePulse({ pan: 0, frequency: 760, durationMs: 65, gain: 0.1, wave: "sine" });
    window.setTimeout(() => {
      playGuidePulse({ pan: 0, frequency: 980, durationMs: 85, gain: 0.095, wave: "sine" });
    }, 90);
  });
}

function nextScanPan() {
  guideAudio.scanPan = guideAudio.scanPan > 0 ? -0.85 : 0.85;
  return guideAudio.scanPan;
}

function clampNumber(value, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return min;
  return Math.min(max, Math.max(min, n));
}

async function autoControlPtz(data, mode) {
  if (!ptzAuto?.checked || cameraMode !== "browser" || !ptzState.supported) return;
  const now = Date.now();
  if (now - ptzState.lastMoveAt < PTZ_MIN_INTERVAL_MS) return;

  const track = browserVideoTrack();
  if (!track?.applyConstraints || !track.getSettings) return;
  const capabilities = ptzState.capabilities || track.getCapabilities?.() || {};

  const repair = selectedViewRepair(data, mode);
  if (repair) {
    const moved = await applyAutoViewRepair(track, capabilities, repair, now);
    if (moved) scheduleViewRepairAnalyze(data, mode);
    return;
  }

  const frame = currentVideoFrameSize();
  const targetBox = selectedPtzBox(data, mode);
  const trackingMode = mode === "auto_assist" || mode === "auto_reach";
  if (data.safety?.blocking && !(trackingMode && targetBox)) return;
  if (!targetBox) {
    if (mode === "auto_assist" || mode === "auto_reach" || mode === "find") {
      await scanPtz(track, capabilities, now);
    }
    return;
  }

  await servoPtzToBox(track, capabilities, targetBox, frame, now, 0.1);
}

async function servoPtzToBox(track, capabilities, targetBox, frame, now, deadband = 0.13) {
  if (!targetBox?.length) return false;
  if (now - ptzState.lastMoveAt < PTZ_TRACK_INTERVAL_MS) return false;
  const [x1, y1, x2, y2] = targetBox.map(Number);
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  const errX = (cx - frame.width / 2) / Math.max(1, frame.width / 2);
  const errY = (cy - frame.height / 2) / Math.max(1, frame.height / 2);
  const activeErrX = Math.abs(errX) < deadband ? 0 : errX;
  const activeErrY = Math.abs(errY) < deadband ? 0 : errY;
  ptzState.servoErrorX = activeErrX ? ptzState.servoErrorX * 0.35 + activeErrX * 0.65 : ptzState.servoErrorX * 0.45;
  ptzState.servoErrorY = activeErrY ? ptzState.servoErrorY * 0.35 + activeErrY * 0.65 : ptzState.servoErrorY * 0.45;
  ptzState.servoIntegralX = activeErrX ? clampNumber(ptzState.servoIntegralX + activeErrX * 0.18, -0.55, 0.55) : ptzState.servoIntegralX * 0.55;
  ptzState.servoIntegralY = activeErrY ? clampNumber(ptzState.servoIntegralY + activeErrY * 0.18, -0.55, 0.55) : ptzState.servoIntegralY * 0.55;
  const controlX = ptzState.servoErrorX + ptzState.servoIntegralX * 0.24;
  const controlY = ptzState.servoErrorY + ptzState.servoIntegralY * 0.24;
  if (Math.abs(controlX) < deadband * 0.55 && Math.abs(controlY) < deadband * 0.55) return false;
  const next = {};
  const settings = track.getSettings();
  addPtzAdjustment(next, settings, capabilities, "pan", controlX, 0.07);
  addPtzAdjustment(next, settings, capabilities, "tilt", -controlY, 0.06);
  if (!Object.keys(next).length) return false;

  await track.applyConstraints({ advanced: [next] });
  ptzState.lastMoveAt = now;
  return true;
}

function selectedViewRepair(data, mode) {
  if (!shouldRepairView(data, mode)) return null;
  const evidence = data.evidence || [];
  const ocrMode =
    data.plan?.context_probe ||
    data.plan?.intent === "visual_question" ||
    data.plan?.intent === "read_text" ||
    (data.plan?.tools || []).includes("ocr");
  const frame = currentVideoFrameSize();
  const textBoxes = evidence
    .filter((item) => item.type === "text" && item.bbox?.length >= 4)
    .map((item) => item.bbox);
  const objectBoxes = evidence
    .filter((item) => item.type === "object" && item.bbox?.length >= 4 && !item.attributes?.target_distractor)
    .map((item) => item.bbox);
  const boxes = ocrMode && textBoxes.length ? textBoxes : objectBoxes;
  if (boxes.length) {
    const box = unionBboxes(boxes);
    const directive = repairDirectiveFromBox(box, frame, ocrMode);
    if (directive) return directive;
  }
  return repairDirectiveFromText(`${question.value || ""} ${data.speech || ""}`);
}

function shouldRepairView(data, mode) {
  if (mode === "auto_assist" || mode === "auto_reach" || mode === "auto_safety") return false;
  if (data.safety?.risk_level === "high" && !data.plan?.context_probe) return false;
  if (data.action !== "reobserve" && data.action !== "refuse_uncertain") return false;
  return Boolean(
    data.plan?.context_probe ||
    data.plan?.intent === "visual_question" ||
    data.plan?.intent === "read_text" ||
    data.plan?.intent === "find_object" ||
    (data.plan?.tools || []).includes("ocr")
  );
}

function repairDirectiveFromBox(box, frame, preferZoom) {
  const [x1, y1, x2, y2] = box.map(Number);
  const cx = (x1 + x2) / 2;
  const cy = (y1 + y2) / 2;
  const width = Math.max(1, x2 - x1);
  const height = Math.max(1, y2 - y1);
  const edge = {
    left: x1 / frame.width,
    right: x2 / frame.width,
    top: y1 / frame.height,
    bottom: y2 / frame.height,
  };
  let pan = 0;
  let tilt = 0;
  if (edge.left < 0.08) pan = -1;
  else if (edge.right > 0.92) pan = 1;
  else {
    const errX = (cx - frame.width / 2) / Math.max(1, frame.width / 2);
    if (Math.abs(errX) > 0.22) pan = Math.sign(errX);
  }
  if (edge.top < 0.10) tilt = 1;
  else if (edge.bottom > 0.82) tilt = -1;
  else {
    const errY = (cy - frame.height / 2) / Math.max(1, frame.height / 2);
    if (Math.abs(errY) > 0.24) tilt = -Math.sign(errY);
  }
  const areaRatio = (width * height) / Math.max(1, frame.width * frame.height);
  const zoom = preferZoom && areaRatio > 0 && areaRatio < 0.07 && !pan && !tilt ? 1 : 0;
  if (!pan && !tilt && !zoom) return null;
  return { pan, tilt, zoom, fraction: zoom ? 0.08 : 0.075, reason: "evidence_box" };
}

function repairDirectiveFromText(text) {
  const value = normalizedVoiceText(text);
  const left = containsAny(value, ["左侧", "左边", "左上", "左下", "往左", "向左"]);
  const right = containsAny(value, ["右侧", "右边", "右上", "右下", "往右", "向右"]);
  const up = containsAny(value, ["上方", "上面", "顶部", "往上", "向上"]);
  const down = containsAny(value, ["下方", "下面", "底部", "往下", "向下"]);
  const zoom = containsAny(value, ["靠近", "近一点", "放大", "小字", "看清", "看不清"]) ? 1 : 0;
  const pan = right ? 1 : left ? -1 : 0;
  const tilt = up ? 1 : down ? -1 : 0;
  if (!pan && !tilt && !zoom) return { pan: 1, tilt: 0, zoom: 0, fraction: 0.065, reason: "scan" };
  return { pan, tilt, zoom, fraction: 0.075, reason: "speech_hint" };
}

async function applyAutoViewRepair(track, capabilities, repair, now) {
  if (now - viewRepairState.lastMoveAt < VIEW_REPAIR_MIN_INTERVAL_MS) return false;
  const settings = track.getSettings();
  const next = {};
  let changed = false;
  if (repair.pan) changed = addPtzDelta(next, settings, capabilities, "pan", repair.pan, repair.fraction) || changed;
  if (repair.tilt) changed = addPtzDelta(next, settings, capabilities, "tilt", repair.tilt, repair.fraction) || changed;
  if (repair.zoom) changed = addPtzDelta(next, settings, capabilities, "zoom", repair.zoom, repair.fraction) || changed;
  if (!changed || !Object.keys(next).length) return false;
  await track.applyConstraints({ advanced: [next] });
  ptzState.lastMoveAt = now;
  viewRepairState.lastMoveAt = now;
  actionBadge.textContent = "补视角";
  cameraStatus.textContent = `正在自动补全视角：${viewRepairLabel(repair)}`;
  return true;
}

function scheduleViewRepairAnalyze(data, mode) {
  const key = `${mode}:${question.value.trim()}:${data.plan?.intent || ""}:${data.plan?.ocr_focus || ""}`;
  if (viewRepairState.key !== key) {
    viewRepairState.key = key;
    viewRepairState.attempts = 0;
  }
  if (viewRepairState.attempts >= VIEW_REPAIR_MAX_ATTEMPTS) return;
  viewRepairState.attempts += 1;
  if (viewRepairState.timer) window.clearTimeout(viewRepairState.timer);
  viewRepairState.timer = window.setTimeout(() => {
    viewRepairState.timer = null;
    if (!busy && cameraMode === "browser") {
      analyze(mode, question.value.trim());
    }
  }, VIEW_REPAIR_SETTLE_MS);
}

function viewRepairLabel(repair) {
  const parts = [];
  if (repair.pan > 0) parts.push("向右");
  if (repair.pan < 0) parts.push("向左");
  if (repair.tilt > 0) parts.push("向上");
  if (repair.tilt < 0) parts.push("向下");
  if (repair.zoom > 0) parts.push("放大");
  if (repair.zoom < 0) parts.push("缩小");
  return parts.join("、") || "扫描";
}

function selectedPtzBox(data, mode) {
  const evidence = data.evidence || [];
  const target = evidence
    .filter((item) => item.type === "object" && item.bbox?.length >= 4)
    .filter((item) => item.attributes?.agent_primary_target || item.attributes?.target_match)
    .sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0))[0];
  if (!target) return null;
  return target.bbox;
}

function unionBboxes(boxes) {
  return boxes.reduce((acc, box) => unionBbox(acc, box), boxes[0]);
}

function unionBbox(a, b) {
  return [
    Math.min(Number(a[0]), Number(b[0])),
    Math.min(Number(a[1]), Number(b[1])),
    Math.max(Number(a[2]), Number(b[2])),
    Math.max(Number(a[3]), Number(b[3])),
  ];
}

function currentVideoFrameSize() {
  return {
    width: video.videoWidth || canvas.width || 1280,
    height: video.videoHeight || canvas.height || 720,
  };
}

function addPtzAdjustment(next, settings, capabilities, name, error, fraction) {
  const cap = capabilities[name];
  if (!cap || typeof cap.min !== "number" || typeof cap.max !== "number") return;
  const range = Math.max(1, cap.max - cap.min);
  const baseStep = typeof cap.step === "number" && cap.step > 0 ? cap.step : range / 120;
  const maxDelta = Math.max(baseStep, range * (name === "pan" ? 0.12 : 0.1));
  const rawDelta = error * range * (name === "pan" ? Math.max(fraction, 0.13) : Math.max(fraction, 0.11));
  const delta = clampValue(rawDelta, -maxDelta, maxDelta);
  if (Math.abs(delta) < baseStep * 0.45) return;
  const current = typeof settings[name] === "number" ? settings[name] : (cap.min + cap.max) / 2;
  next[name] = softClampPtzValue(name, current + delta, cap);
}

function addPtzDelta(next, settings, capabilities, name, direction, fraction) {
  const cap = capabilities[name];
  if (!cap || typeof cap.min !== "number" || typeof cap.max !== "number") return false;
  const range = Math.max(1, cap.max - cap.min);
  const baseStep = typeof cap.step === "number" && cap.step > 0 ? cap.step : range / 120;
  const current = typeof settings[name] === "number" ? settings[name] : (cap.min + cap.max) / 2;
  const raw = direction * Math.max(baseStep, range * fraction);
  next[name] = softClampPtzValue(name, current + raw, cap);
  return Math.abs(next[name] - current) >= baseStep * 0.2;
}

function softClampPtzValue(name, value, cap) {
  const range = Math.max(1, cap.max - cap.min);
  const margin = range * (PTZ_SOFT_MARGIN[name] ?? 0.03);
  return clampValue(value, cap.min + margin, cap.max - margin);
}

async function recoverPtzFromSignalLoss(track, capabilities, now) {
  if (now - ptzState.lastSignalRecoverAt < PTZ_SIGNAL_RECOVER_MIN_INTERVAL_MS) return false;
  const settings = track.getSettings?.() || {};
  const next = {};
  let changed = false;
  if (capabilities.tilt && typeof capabilities.tilt.min === "number" && typeof capabilities.tilt.max === "number") {
    const mid = (capabilities.tilt.min + capabilities.tilt.max) / 2;
    const current = typeof settings.tilt === "number" ? settings.tilt : mid;
    if (Math.abs(current - mid) > Math.max(1, (capabilities.tilt.max - capabilities.tilt.min) * 0.04)) {
      next.tilt = mid;
      changed = true;
    }
  }
  if (capabilities.zoom && typeof capabilities.zoom.min === "number" && typeof capabilities.zoom.max === "number") {
    const current = typeof settings.zoom === "number" ? settings.zoom : capabilities.zoom.min;
    if (current > capabilities.zoom.min) {
      next.zoom = capabilities.zoom.min;
      changed = true;
    }
  }
  if (!changed) return false;
  await track.applyConstraints({ advanced: [next] });
  ptzState.lastMoveAt = now;
  ptzState.lastSignalRecoverAt = now;
  trackerState.active = false;
  trackerState.initPending = false;
  cameraStatus.textContent = "画面信号异常，已把云台拉回安全角度";
  return true;
}

function addPtzCenter(next, capabilities, name) {
  const cap = capabilities[name];
  if (!cap || typeof cap.min !== "number" || typeof cap.max !== "number") return false;
  next[name] = (cap.min + cap.max) / 2;
  return true;
}

async function scanPtz(track, capabilities, now) {
  if (now - ptzState.lastScanAt < 3200) return;
  const cap = capabilities.pan;
  if (!cap || typeof cap.min !== "number" || typeof cap.max !== "number") return;
  const settings = track.getSettings();
  const range = Math.max(1, cap.max - cap.min);
  const current = typeof settings.pan === "number" ? settings.pan : (cap.min + cap.max) / 2;
  let nextPan = current + ptzState.scanDirection * range * 0.08;
  if (nextPan >= cap.max || nextPan <= cap.min) {
    ptzState.scanDirection *= -1;
  }
  nextPan = softClampPtzValue("pan", nextPan, cap);
  await track.applyConstraints({ advanced: [{ pan: nextPan }] });
  ptzState.lastMoveAt = now;
  ptzState.lastScanAt = now;
}

function clampValue(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function resumeBrowserPreviewSoon(delay = 1200) {
  if (streamResumeTimer) window.clearTimeout(streamResumeTimer);
  streamResumeTimer = window.setTimeout(() => {
    if (!busy && cameraMode === "browser") {
      annotated.style.display = "none";
      clearLiveOverlay();
    }
  }, delay);
}

function renderEvidence(items) {
  const visibleItems = items.filter((item) => {
    if (item.type !== "object") return true;
    if (isTargetEvidence(item) || item.attributes?.depth_obstacle) return true;
    return Number(item.confidence || 0) >= 0.16;
  });
  evidenceCount.textContent = String(visibleItems.length);
  evidenceList.innerHTML = "";
  for (const item of visibleItems.slice(0, 30)) {
    const node = document.createElement("div");
    node.className = `evidence-item ${item.type}`;
    const label = item.text || item.attributes?.label_zh || item.label;
    node.innerHTML = `
      <strong>${escapeHtml(label)}</strong>
      <div class="meta">${escapeHtml(item.type)} · ${escapeHtml(item.source)} · ${escapeHtml(item.position || "unknown")} · conf ${Number(item.confidence || 0).toFixed(2)} · age ${Number(item.age || 0).toFixed(1)}s</div>
    `;
    evidenceList.appendChild(node);
  }
}

function actionLabel(action) {
  return {
    answer: "回答",
    reobserve: "重观察",
    refuse_uncertain: "不确定",
    safety_alert: "安全提示",
  }[action] || action;
}

function safetyLabel(level) {
  return { low: "低风险", medium: "注意", high: "停止" }[level] || "未知";
}

async function speak(text, options = {}) {
  if (!text) return false;
  const interrupt = options.interrupt !== false;
  if (!interrupt && speechIsActive()) return false;
  currentSpeechText = String(text);
  const rate = getSpeechRate();
  const seq = ++speechSeq;
  if (speechRestartTimer) window.clearTimeout(speechRestartTimer);
  if (interrupt && "speechSynthesis" in window) window.speechSynthesis.cancel();
  speechPending = true;

  try {
    if (!ttsAudio) ttsAudio = new Audio();
    if (interrupt) {
      ttsAudio.pause();
      ttsAudio.currentTime = 0;
    }
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: currentSpeechText, rate }),
    });
    if (!res.ok) throw new Error(await res.text());
    const serverRateApplied = res.headers.get("X-TTS-Rate-Applied") === "1";
    const blob = await res.blob();
    if (seq !== speechSeq) {
      return false;
    }
    if (ttsObjectUrl) URL.revokeObjectURL(ttsObjectUrl);
    ttsObjectUrl = URL.createObjectURL(blob);
    ttsAudio.src = ttsObjectUrl;
    ttsAudio.preservesPitch = false;
    ttsAudio.playbackRate = serverRateApplied ? 1 : rate;
    ttsAudio.volume = 1;
    usingLocalTts = true;
    await ttsAudio.play();
    speechPending = false;
    return true;
  } catch (err) {
    if (seq === speechSeq) speechPending = false;
    usingLocalTts = false;
    return browserSpeak(currentSpeechText, { interrupt });
  }
}

function browserSpeak(text, options = {}) {
  if (!("speechSynthesis" in window) || !text) return false;
  const interrupt = options.interrupt !== false;
  if (!interrupt && speechIsActive()) return false;
  if (interrupt) window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(String(text));
  utter.lang = "zh-CN";
  utter.rate = getSpeechRate();
  utter.pitch = 1;
  utter.volume = 1;
  window.speechSynthesis.speak(utter);
  return true;
}

function restartSpeechWithCurrentRate() {
  if (ttsAudio) ttsAudio.playbackRate = getSpeechRate();
  if (usingLocalTts) return;
  if (!("speechSynthesis" in window) || !currentSpeechText) return;
  if (speechRestartTimer) window.clearTimeout(speechRestartTimer);
  speechRestartTimer = window.setTimeout(() => {
    if (window.speechSynthesis.speaking || window.speechSynthesis.pending) {
      speak(currentSpeechText);
    }
  }, 80);
}

async function handleMicButton() {
  if (recording && mediaRecorder) {
    mediaRecorder.stop();
    return;
  }
  if ("MediaRecorder" in window && navigator.mediaDevices?.getUserMedia) {
    try {
      await startLocalRecording();
      return;
    } catch (err) {
      answer.textContent = "本地录音不可用，尝试浏览器语音识别。";
    }
  }
  startBrowserRecognition();
}

async function startLocalRecording() {
  const audioStream = await navigator.mediaDevices.getUserMedia({
    audio: selectedAudioConstraints(),
    video: false,
  });
  loadAudioDevices(false).catch(() => {});
  const mimeType = pickAudioMimeType();
  mediaRecorder = mimeType
    ? new MediaRecorder(audioStream, { mimeType })
    : new MediaRecorder(audioStream);
  audioChunks = [];
  recording = true;
  micButton.textContent = "停止";
  micButton.classList.add("recording");
  actionBadge.textContent = "聆听中";
  answer.textContent = "正在录音，再次点击麦克风结束。";

  mediaRecorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) audioChunks.push(event.data);
  };

  mediaRecorder.onstop = async () => {
    if (recordingTimer) {
      window.clearTimeout(recordingTimer);
      recordingTimer = null;
    }
    recording = false;
    micButton.textContent = "麦克风";
    micButton.classList.remove("recording");
    audioStream.getTracks().forEach((track) => track.stop());
    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
    audioChunks = [];
    await transcribeBlob(blob);
  };

  mediaRecorder.start();
  recordingTimer = window.setTimeout(() => {
    if (recording && mediaRecorder?.state === "recording") mediaRecorder.stop();
  }, 7000);
}

function pickAudioMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

async function transcribeBlob(blob) {
  try {
    setButtonsDisabled(true);
    micButton.disabled = true;
    answer.textContent = "正在本地识别语音...";
    const audioData = await blobToDataUrl(blob);
    const res = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_data: audioData }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text);
    }
    const data = await res.json();
    const text = String(data.text || "").trim();
    if (!text) {
      answer.textContent = "我没听清，可以再说一遍。";
      actionBadge.textContent = "重观察";
      return;
    }
    question.value = text;
    if (handleVoiceControlCommand(text)) return;
    await analyze("ask", text);
  } catch (err) {
    const message = String(err.message || err);
    answer.textContent = message.includes("Failed to fetch")
      ? "语音识别出错：后端连接中断或服务未运行，请稍等几秒后重试。"
      : `语音识别出错：${message}`;
    actionBadge.textContent = "错误";
  } finally {
    micButton.disabled = false;
    setButtonsDisabled(false);
  }
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function handleMicButton() {
  if (recording) {
    stopActiveRecording();
    return;
  }
  if (navigator.mediaDevices?.getUserMedia) {
    try {
      await startLocalRecording();
      return;
    } catch (err) {
      answer.textContent = "\u672c\u5730\u5f55\u97f3\u4e0d\u53ef\u7528\uff0c\u5c1d\u8bd5\u6d4f\u89c8\u5668\u8bed\u97f3\u8bc6\u522b\u3002";
    }
  }
  startBrowserRecognition();
}

async function startLocalRecording() {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (AudioContextCtor) {
    await startPcmWavRecording(AudioContextCtor);
    return;
  }
  if (!("MediaRecorder" in window)) throw new Error("local audio recording is not available");
  await startMediaRecorderRecording();
}

async function startPcmWavRecording(AudioContextCtor) {
  const audioStream = await navigator.mediaDevices.getUserMedia({
    audio: selectedAudioConstraints(),
    video: false,
  });
  loadAudioDevices(false).catch(() => {});
  audioContext = new AudioContextCtor();
  if (audioContext.state === "suspended") await audioContext.resume();
  recorderStream = audioStream;
  recorderSource = audioContext.createMediaStreamSource(audioStream);
  recorderNode = audioContext.createScriptProcessor(4096, 1, 1);
  pcmInputSampleRate = audioContext.sampleRate || 48000;
  pcmChunks = [];

  recorderNode.onaudioprocess = (event) => {
    if (!recording) return;
    const input = event.inputBuffer.getChannelData(0);
    pcmChunks.push(new Float32Array(input));
    event.outputBuffer.getChannelData(0).fill(0);
  };

  recorderSource.connect(recorderNode);
  recorderNode.connect(audioContext.destination);
  beginRecordingUi();
  recordingTimer = window.setTimeout(() => {
    if (recording) stopPcmWavRecording();
  }, MAX_RECORDING_MS);
}

async function startMediaRecorderRecording() {
  const audioStream = await navigator.mediaDevices.getUserMedia({
    audio: selectedAudioConstraints(),
    video: false,
  });
  loadAudioDevices(false).catch(() => {});
  const mimeType = pickAudioMimeType();
  mediaRecorder = mimeType
    ? new MediaRecorder(audioStream, { mimeType })
    : new MediaRecorder(audioStream);
  audioChunks = [];
  beginRecordingUi();

  mediaRecorder.ondataavailable = (event) => {
    if (event.data && event.data.size > 0) audioChunks.push(event.data);
  };

  mediaRecorder.onstop = async () => {
    if (recordingTimer) {
      window.clearTimeout(recordingTimer);
      recordingTimer = null;
    }
    recording = false;
    micButton.textContent = "\u9ea6\u514b\u98ce";
    micButton.classList.remove("recording");
    audioStream.getTracks().forEach((track) => track.stop());
    const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || "audio/webm" });
    audioChunks = [];
    await transcribeBlob(blob);
  };

  mediaRecorder.start();
  recordingTimer = window.setTimeout(() => {
    if (recording && mediaRecorder?.state === "recording") mediaRecorder.stop();
  }, MAX_RECORDING_MS);
}

function beginRecordingUi() {
  recording = true;
  micButton.textContent = "\u505c\u6b62";
  micButton.classList.add("recording");
  actionBadge.textContent = "\u8046\u542c\u4e2d";
  answer.textContent = "\u6b63\u5728\u5f55\u97f3\uff0c\u518d\u6b21\u70b9\u51fb\u9ea6\u514b\u98ce\u7ed3\u675f\u3002";
}

function stopActiveRecording() {
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }
  if (recorderNode) stopPcmWavRecording();
}

async function stopPcmWavRecording() {
  if (recordingTimer) {
    window.clearTimeout(recordingTimer);
    recordingTimer = null;
  }
  recording = false;
  micButton.textContent = "\u9ea6\u514b\u98ce";
  micButton.classList.remove("recording");
  try {
    if (recorderNode) recorderNode.disconnect();
    if (recorderSource) recorderSource.disconnect();
  } catch (err) {
    // The browser may already have torn down the audio graph.
  }
  if (recorderStream) recorderStream.getTracks().forEach((track) => track.stop());
  const chunks = pcmChunks;
  pcmChunks = [];
  recorderNode = null;
  recorderSource = null;
  recorderStream = null;
  if (audioContext) {
    const ctx = audioContext;
    audioContext = null;
    ctx.close().catch(() => {});
  }
  const blob = encodeWavBlob(chunks, pcmInputSampleRate, 16000);
  await transcribeBlob(blob);
}

async function transcribeBlob(blob) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), ASR_TIMEOUT_MS);
  try {
    setButtonsDisabled(true);
    micButton.disabled = true;
    answer.textContent = "\u6b63\u5728\u672c\u5730\u8bc6\u522b\u8bed\u97f3...";
    const audioData = await blobToDataUrl(blob);
    const res = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_data: audioData }),
      signal: controller.signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text);
    }
    const data = await res.json();
    const text = String(data.text || "").trim();
    if (!text) {
      answer.textContent = "\u6211\u6ca1\u542c\u6e05\uff0c\u53ef\u4ee5\u518d\u8bf4\u4e00\u904d\u3002";
      actionBadge.textContent = "\u91cd\u8bd5";
      return;
    }
    question.value = text;
    if (handleVoiceControlCommand(text)) return;
    await analyze("ask", text);
  } catch (err) {
    const message = String(err.message || err);
    answer.textContent = err.name === "AbortError"
      ? "\u8bed\u97f3\u8bc6\u522b\u8d85\u65f6\uff0c\u8bf7\u7b49\u9884\u70ed\u5b8c\u6210\u540e\u518d\u8bd5\u3002"
      : message.includes("Failed to fetch")
        ? "\u8bed\u97f3\u8bc6\u522b\u51fa\u9519\uff1a\u540e\u7aef\u8fde\u63a5\u4e2d\u65ad\u6216\u670d\u52a1\u672a\u8fd0\u884c\uff0c\u8bf7\u7a0d\u7b49\u51e0\u79d2\u540e\u91cd\u8bd5\u3002"
        : `\u8bed\u97f3\u8bc6\u522b\u51fa\u9519\uff1a${message}`;
    actionBadge.textContent = "\u9519\u8bef";
  } finally {
    window.clearTimeout(timeout);
    micButton.disabled = false;
    setButtonsDisabled(false);
  }
}

function encodeWavBlob(chunks, inputSampleRate, outputSampleRate) {
  const samples = mergeFloat32Chunks(chunks);
  const resampled = resampleFloat32(samples, inputSampleRate, outputSampleRate);
  const buffer = new ArrayBuffer(44 + resampled.length * 2);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + resampled.length * 2, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, outputSampleRate, true);
  view.setUint32(28, outputSampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, resampled.length * 2, true);
  let offset = 44;
  for (const sample of resampled) {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

function mergeFloat32Chunks(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  return merged;
}

function resampleFloat32(samples, inputRate, outputRate) {
  if (!samples.length || inputRate === outputRate) return samples;
  const ratio = inputRate / outputRate;
  const length = Math.max(1, Math.round(samples.length / ratio));
  const result = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const sourceIndex = i * ratio;
    const left = Math.floor(sourceIndex);
    const right = Math.min(samples.length - 1, left + 1);
    const weight = sourceIndex - left;
    result[i] = samples[left] * (1 - weight) + samples[right] * weight;
  }
  return result;
}

function writeAscii(view, offset, value) {
  for (let i = 0; i < value.length; i += 1) {
    view.setUint8(offset + i, value.charCodeAt(i));
  }
}

function warmupVoice() {
  fetch("/api/voice/warmup", { method: "POST" }).catch(() => {});
}

function normalizedVoiceText(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/[，。！？、,.!?;；：:"“”'‘’（）()]/g, "");
}

function containsAny(value, words) {
  return words.some((word) => value.includes(word));
}

function isStopTrackingCommand(text) {
  const value = normalizedVoiceText(text);
  const strongStops = [
    "\u505c\u6b62\u8ffd\u8e2a",
    "\u505c\u6b62\u8ddf\u8e2a",
    "\u6682\u505c\u8ffd\u8e2a",
    "\u6682\u505c\u8ddf\u8e2a",
    "\u505c\u6b62\u5f15\u5bfc",
    "\u6682\u505c\u5f15\u5bfc",
    "\u5173\u95ed\u4e91\u53f0",
    "\u5173\u95ed\u8fde\u7eed\u8f85\u52a9",
    "\u53d6\u6d88\u76ee\u6807",
    "\u6e05\u9664\u76ee\u6807",
    "\u522b\u8ffd\u4e86",
    "\u4e0d\u7528\u8ffd\u4e86",
  ];
  if (containsAny(value, strongStops)) return true;
  if (!reachLoop.checked && !activeAssistGoal) return false;
  const stopWords = ["\u505c\u4e0b\u6765", "\u505c\u4e00\u4e0b", "\u6682\u505c", "\u505c\u6b62"];
  const trackingWords = [
    "\u8ffd\u8e2a",
    "\u8ddf\u8e2a",
    "\u5f15\u5bfc",
    "\u4e91\u53f0",
    "\u8fde\u7eed\u8f85\u52a9",
    "\u76ee\u6807",
  ];
  return containsAny(value, stopWords) && (reachLoop.checked || containsAny(value, trackingWords));
}

function isStartTrackingCommand(text) {
  const value = normalizedVoiceText(text);
  if (!value || isStopTrackingCommand(text)) return false;
  const metaQuestionWords = [
    "\u4e3a\u4ec0\u4e48",
    "\u600e\u4e48",
    "\u5982\u4f55",
    "\u80fd\u4e0d\u80fd",
    "\u80fd\u5426",
    "\u53ef\u4ee5\u5417",
    "\u652f\u6301\u5417",
  ];
  if (containsAny(value, metaQuestionWords)) return false;
  const startWords = [
    "\u8ffd\u8e2a",
    "\u8ddf\u8e2a",
    "\u76ef\u4f4f",
    "\u9501\u5b9a",
    "\u5bf9\u51c6",
    "\u770b\u7740",
    "\u8ddf\u7740",
    "\u5e2e\u6211\u627e",
    "\u627e\u4e00\u4e0b",
    "\u627e\u5230",
    "\u5e2e\u6211\u8ffd",
    "\u5f15\u5bfc",
    "\u62ff\u8d77",
    "\u6293\u4f4f",
    "\u62ff\u5230",
    "\u591f\u5230",
    "\u6478\u5230",
    "\u53d6\u5230",
    "\u4f38\u624b",
    "\u9760\u8fd1",
  ];
  return containsAny(value, startWords) || value.startsWith("\u627e");
}

function deriveVoiceTrackingGoal(text) {
  const raw = String(text || "").trim();
  const value = normalizedVoiceText(raw);
  const genericCommands = [
    "\u8ffd\u8e2a",
    "\u8ddf\u8e2a",
    "\u9501\u5b9a",
    "\u76ef\u4f4f",
    "\u5f00\u59cb\u8ffd\u8e2a",
    "\u5f00\u59cb\u8ddf\u8e2a",
    "\u7ee7\u7eed\u8ffd\u8e2a",
    "\u7ee7\u7eed\u8ddf\u8e2a",
    "\u8ffd\u8e2a\u5b83",
    "\u8ddf\u8e2a\u5b83",
    "\u9501\u5b9a\u5b83",
    "\u76ef\u4f4f\u5b83",
    "\u8ffd\u8e2a\u8fd9\u4e2a",
    "\u8ddf\u8e2a\u8fd9\u4e2a",
  ];
  if (genericCommands.includes(value)) {
    return activeAssistGoal || "\u753b\u9762\u4e2d\u5fc3\u7684\u76ee\u6807";
  }
  return raw;
}

function setPtzAutoEnabled(enabled) {
  if (!ptzAuto) return;
  ptzAuto.checked = Boolean(enabled);
  localStorage.setItem(PTZ_AUTO_KEY, ptzAuto.checked ? "1" : "0");
}

function activateVoiceTracking(goal) {
  const cleanGoal = String(goal || "").trim();
  if (!cleanGoal) {
    actionBadge.textContent = "\u9700\u8981\u76ee\u6807";
    answer.textContent = "\u8bf7\u8bf4\u51fa\u8981\u8ffd\u8e2a\u6216\u5f15\u5bfc\u62ff\u53d6\u7684\u7269\u4f53\u3002";
    speak(answer.textContent, { interrupt: true });
    return true;
  }
  saveAssistGoal(cleanGoal);
  question.value = cleanGoal;
  setPtzAutoEnabled(true);
  if (safetyLoop.checked) {
    safetyLoop.checked = false;
    if (safetyTimer) {
      window.clearInterval(safetyTimer);
      safetyTimer = null;
    }
  }
  if (reachLoop.checked) {
    stopReachLoop();
    reachLoop.checked = false;
  }
  lastReachSpeech = 0;
  lastReachSpeechText = "";
  reachLoop.checked = true;
  reachLoop.dispatchEvent(new Event("change"));
  actionBadge.textContent = "\u8ffd\u8e2a";
  answer.textContent = `\u5df2\u5f00\u59cb\u81ea\u52a8\u8ffd\u8e2a\u548c\u5f15\u5bfc\uff1a${cleanGoal}`;
  speak(`\u5f00\u59cb\u8ffd\u8e2a${cleanGoal}`, { interrupt: true });
  return true;
}

function stopVoiceTracking() {
  stopReachLoop();
  reachLoop.checked = false;
  setPtzAutoEnabled(false);
  saveAssistGoal("");
  lastReachSpeech = 0;
  lastReachSpeechText = "";
  actionBadge.textContent = "\u5df2\u505c\u6b62";
  answer.textContent = "\u5df2\u505c\u6b62\u8ffd\u8e2a\u3001\u8fde\u7eed\u5f15\u5bfc\u548c\u81ea\u52a8\u4e91\u53f0\u3002";
  speak(answer.textContent, { interrupt: true });
  return true;
}

function parsePtzCommand(text) {
  const value = normalizedVoiceText(text);
  if (!value) return null;

  const hasCameraContext = containsAny(value, [
    "\u4e91\u53f0",
    "\u6444\u50cf\u5934",
    "\u955c\u5934",
    "\u89c6\u89d2",
    "\u753b\u9762",
    "\u770b",
    "\u8f6c",
    "\u79fb",
    "\u62ac\u5934",
    "\u4f4e\u5934",
  ]);
  const hasMoveWord = containsAny(value, [
    "\u5f80",
    "\u5411",
    "\u671d",
    "\u770b\u5411",
    "\u770b\u770b",
    "\u770b\u4e00\u4e0b",
    "\u8f6c",
    "\u79fb",
    "\u4e0a\u79fb",
    "\u4e0b\u79fb",
    "\u5de6\u79fb",
    "\u53f3\u79fb",
    "\u62ac\u5934",
    "\u4f4e\u5934",
    "\u653e\u5927",
    "\u7f29\u5c0f",
    "\u62c9\u8fd1",
    "\u62c9\u8fdc",
    "\u56de\u4e2d",
    "\u590d\u4f4d",
  ]);
  const asksAbility = containsAny(value, ["\u80fd\u4e0d\u80fd", "\u80fd\u5426", "\u53ef\u4ee5\u5417", "\u80fd\u5417"]);
  if (!hasCameraContext && !hasMoveWord && !asksAbility) return null;

  const reset = containsAny(value, ["\u56de\u4e2d", "\u5c45\u4e2d", "\u590d\u4f4d", "\u56de\u5230\u4e2d\u95f4", "\u56de\u6b63"]);
  const zoomIn = containsAny(value, ["\u653e\u5927", "\u62c9\u8fd1", "\u653e\u8fd1", "\u770b\u8fd1", "\u9760\u8fd1"]);
  const zoomOut = containsAny(value, ["\u7f29\u5c0f", "\u62c9\u8fdc", "\u770b\u8fdc", "\u8fdc\u4e00\u70b9"]);
  const left = containsAny(value, ["\u5f80\u5de6", "\u5411\u5de6", "\u671d\u5de6", "\u770b\u5de6", "\u5de6\u8fb9", "\u5de6\u4fa7", "\u5de6\u79fb", "\u5de6\u8f6c"]);
  const right = containsAny(value, ["\u5f80\u53f3", "\u5411\u53f3", "\u671d\u53f3", "\u770b\u53f3", "\u53f3\u8fb9", "\u53f3\u4fa7", "\u53f3\u79fb", "\u53f3\u8f6c"]);
  const up = containsAny(value, ["\u5f80\u4e0a", "\u5411\u4e0a", "\u671d\u4e0a", "\u770b\u4e0a", "\u4e0a\u9762", "\u4e0a\u65b9", "\u4e0a\u79fb", "\u62ac\u5934"]);
  const down = containsAny(value, ["\u5f80\u4e0b", "\u5411\u4e0b", "\u671d\u4e0b", "\u770b\u4e0b", "\u4e0b\u9762", "\u4e0b\u65b9", "\u4e0b\u79fb", "\u4f4e\u5934"]);
  if (!reset && !zoomIn && !zoomOut && !left && !right && !up && !down) return null;

  const small = containsAny(value, ["\u4e00\u70b9", "\u4e00\u4e0b", "\u5fae", "\u7a0d\u5fae", "\u5c0f\u5e45"]);
  const large = containsAny(value, ["\u591a\u4e00\u70b9", "\u5927\u5e45", "\u7ee7\u7eed", "\u518d", "\u5f88"]);
  return {
    pan: right ? 1 : left ? -1 : 0,
    tilt: up ? 1 : down ? -1 : 0,
    zoom: zoomIn ? 1 : zoomOut ? -1 : 0,
    reset,
    fraction: large ? 0.18 : small ? 0.06 : 0.11,
  };
}

async function movePtzFromCommand(command) {
  if (!command) return false;
  if (cameraMode !== "browser") {
    actionBadge.textContent = "\u4e91\u53f0";
    answer.textContent = "\u8bf7\u5148\u5207\u5230\u201c\u6d4f\u89c8\u5668\u201d\u6444\u50cf\u5934\uff0c\u540e\u7aef\u6444\u50cf\u5934\u6d41\u4e0d\u80fd\u5728\u7f51\u9875\u91cc\u76f4\u63a5\u63a7\u5236\u4e91\u53f0\u3002";
    speak(answer.textContent, { interrupt: true });
    return true;
  }
  const track = browserVideoTrack();
  if (!track?.applyConstraints || !track.getSettings) {
    actionBadge.textContent = "\u4e91\u53f0";
    answer.textContent = "\u5f53\u524d\u6d4f\u89c8\u5668\u6ca1\u6709\u63d0\u4f9b\u53ef\u63a7\u5236\u7684\u6444\u50cf\u5934\u8f68\u9053\u3002";
    speak(answer.textContent, { interrupt: true });
    return true;
  }
  const capabilities = ptzState.capabilities || track.getCapabilities?.() || {};
  if (!ptzState.supported || !Object.keys(capabilities).some((name) => ["pan", "tilt", "zoom"].includes(name))) {
    await initializePtzControl();
  }
  const caps = ptzState.capabilities || capabilities;
  const settings = track.getSettings();
  const next = {};
  let changed = false;
  if (command.reset) {
    changed = addPtzCenter(next, caps, "pan") || changed;
    changed = addPtzCenter(next, caps, "tilt") || changed;
    changed = addPtzCenter(next, caps, "zoom") || changed;
  } else {
    if (command.pan) changed = addPtzDelta(next, settings, caps, "pan", command.pan, command.fraction) || changed;
    if (command.tilt) changed = addPtzDelta(next, settings, caps, "tilt", command.tilt, command.fraction) || changed;
    if (command.zoom) changed = addPtzDelta(next, settings, caps, "zoom", command.zoom, command.fraction) || changed;
  }
  if (!changed || !Object.keys(next).length) {
    const missing = [];
    if (command.pan && !caps.pan) missing.push("\u5de6\u53f3");
    if (command.tilt && !caps.tilt) missing.push("\u4e0a\u4e0b");
    if (command.zoom && !caps.zoom) missing.push("\u7f29\u653e");
    answer.textContent = missing.length
      ? `\u6d4f\u89c8\u5668\u6ca1\u6709\u66b4\u9732${missing.join("\u3001")}\u4e91\u53f0\u63a7\u5236\u6743\u9650\u3002`
      : "\u4e91\u53f0\u5df2\u7ecf\u5230\u8fbe\u53ef\u63a7\u8303\u56f4\u8fb9\u754c\u3002";
    actionBadge.textContent = "\u4e91\u53f0";
    speak(answer.textContent, { interrupt: true });
    return true;
  }

  try {
    await track.applyConstraints({ advanced: [next] });
    ptzState.lastMoveAt = Date.now();
    const label = command.reset ? "\u5df2\u56de\u5230\u4e2d\u95f4" : ptzCommandLabel(command);
    actionBadge.textContent = "\u4e91\u53f0";
    answer.textContent = label;
    speak(label, { interrupt: true });
  } catch (err) {
    actionBadge.textContent = "\u4e91\u53f0";
    answer.textContent = `\u4e91\u53f0\u79fb\u52a8\u5931\u8d25\uff1a${err.message || err}`;
    speak(answer.textContent, { interrupt: true });
  }
  return true;
}

function ptzCommandLabel(command) {
  const parts = [];
  if (command.pan > 0) parts.push("\u5411\u53f3");
  if (command.pan < 0) parts.push("\u5411\u5de6");
  if (command.tilt > 0) parts.push("\u5411\u4e0a");
  if (command.tilt < 0) parts.push("\u5411\u4e0b");
  if (command.zoom > 0) parts.push("\u653e\u5927");
  if (command.zoom < 0) parts.push("\u7f29\u5c0f");
  return parts.length ? `\u5df2${parts.join("\u3001")}\u79fb\u52a8\u4e91\u53f0` : "\u5df2\u79fb\u52a8\u4e91\u53f0";
}

function handleClientControlCommand(text) {
  const ptzCommand = parsePtzCommand(text);
  if (ptzCommand) {
    movePtzFromCommand(ptzCommand).catch((err) => {
      actionBadge.textContent = "\u4e91\u53f0";
      answer.textContent = `\u4e91\u53f0\u6307\u4ee4\u5931\u8d25\uff1a${err.message || err}`;
    });
    return true;
  }
  if (isStopTrackingCommand(text)) return stopVoiceTracking();
  if (!isStartTrackingCommand(text)) return false;
  return activateVoiceTracking(deriveVoiceTrackingGoal(text));
}

function handleVoiceControlCommand(text) {
  return handleClientControlCommand(text);
}

function startBrowserRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    answer.textContent = "当前浏览器不支持语音输入，请直接打字。";
    return;
  }
  const recog = new Recognition();
  recog.lang = "zh-CN";
  recog.interimResults = false;
  recog.maxAlternatives = 1;
  recog.onstart = () => {
    micButton.textContent = "聆听中";
  };
  recog.onend = () => {
    micButton.textContent = "麦克风";
  };
  recog.onresult = (event) => {
    const text = event.results[0][0].transcript;
    question.value = text;
    if (handleVoiceControlCommand(text)) return;
    analyze("ask", text);
  };
  recog.start();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

startCamera.addEventListener("click", () => openCamera());

serverCameraButton.addEventListener("click", () => startServerCamera("manual source"));

browserCameraButton.addEventListener("click", () => openBrowserCamera());

serverCameraIndex.addEventListener("change", async () => {
  try {
    if (cameraMode !== "server") {
      localStorage.setItem(SERVER_CAMERA_INDEX_KEY, String(serverCameraIndex.value || 0));
      return;
    }
    await applyServerCameraIndex(true);
  } catch (err) {
    cameraStatus.textContent = `切换后端摄像头失败：${err.message}`;
  }
});

audioInputSelect.addEventListener("change", () => {
  const deviceId = audioInputSelect.value || "";
  if (deviceId) {
    localStorage.setItem(AUDIO_INPUT_KEY, deviceId);
  } else {
    localStorage.removeItem(AUDIO_INPUT_KEY);
  }
});

refreshAudioDevices.addEventListener("click", () => {
  loadAudioDevices(true).catch((err) => {
    answer.textContent = `刷新麦克风列表失败：${err.message}`;
    actionBadge.textContent = "错误";
  });
});

if (navigator.mediaDevices?.addEventListener) {
  navigator.mediaDevices.addEventListener("devicechange", () => {
    loadAudioDevices(false).catch(() => {});
  });
}

askButton.addEventListener("click", () => {
  const text = question.value.trim();
  if (handleClientControlCommand(text)) return;
  analyze("ask");
});

micButton.addEventListener("click", handleMicButton);

document.querySelectorAll("[data-mode]").forEach((button) => {
  button.addEventListener("click", () => {
    const mode = button.dataset.mode;
    if (!question.value.trim()) question.value = defaultQuestion(mode);
    analyze(mode);
  });
});

safetyLoop.addEventListener("change", () => {
  if (safetyLoop.checked) {
    if (reachLoop.checked) {
      reachLoop.checked = false;
      stopReachLoop();
    }
    safetyTimer = window.setInterval(() => analyze("auto_safety"), 1800);
  } else if (safetyTimer) {
    window.clearInterval(safetyTimer);
    safetyTimer = null;
  }
});

function stopReachLoop() {
  if (reachTimer) {
    window.clearInterval(reachTimer);
    reachTimer = null;
  }
  stopTrackerLoop(true);
  resetAudioGuideState();
}

reachLoop.addEventListener("change", () => {
  if (reachLoop.checked) {
    if (safetyLoop.checked) {
      safetyLoop.checked = false;
      if (safetyTimer) {
        window.clearInterval(safetyTimer);
        safetyTimer = null;
      }
    }
    const goal = currentAssistGoal();
    if (!goal) {
      reachLoop.checked = false;
      actionBadge.textContent = "需要目标";
      answer.textContent = "请先输入目标，例如：引导我的手拿起红色罐子，然后点“设目标”或重新打开连续辅助。";
      return;
    }
    if (!activeAssistGoal) saveAssistGoal(goal);
    lastReachSpeech = 0;
    lastReachSpeechText = "";
    analyze("auto_assist", activeAssistGoal);
    reachTimer = window.setInterval(() => {
      if (!activeAssistGoal) {
        reachLoop.checked = false;
        stopReachLoop();
        return;
      }
      analyze("auto_assist", activeAssistGoal);
    }, CONTINUOUS_ASSIST_INTERVAL_MS);
  } else {
    stopReachLoop();
  }
});

setAssistGoal.addEventListener("click", () => {
  const goal = question.value.trim();
  if (!goal) {
    actionBadge.textContent = "需要目标";
    answer.textContent = "请先输入一句目标，例如：引导我的手拿起红色罐子。";
    return;
  }
  saveAssistGoal(goal);
  actionBadge.textContent = "目标已设";
  answer.textContent = `当前连续辅助目标：${goal}`;
  if (reachLoop.checked) {
    lastReachSpeech = 0;
    lastReachSpeechText = "";
    analyze("auto_assist", activeAssistGoal);
  }
});

clearAssistGoal.addEventListener("click", () => {
  saveAssistGoal("");
  stopReachLoop();
  reachLoop.checked = false;
  actionBadge.textContent = "目标已清除";
  answer.textContent = "当前没有连续辅助目标。";
});

resetEvidence.addEventListener("click", async () => {
  await fetch("/api/reset", { method: "POST" });
  stopTrackerLoop(true);
  evidenceList.innerHTML = "";
  evidenceCount.textContent = "0";
});

voiceRate.addEventListener("input", () => {
  const rate = getSpeechRate();
  localStorage.setItem(SPEECH_RATE_KEY, String(rate));
  updateVoiceRateLabel(rate);
  restartSpeechWithCurrentRate();
});

ptzAuto.addEventListener("change", () => {
  localStorage.setItem(PTZ_AUTO_KEY, ptzAuto.checked ? "1" : "0");
  if (!ptzAuto.checked) stopTrackerLoop(true);
});

audioGuide?.addEventListener("change", () => {
  localStorage.setItem(AUDIO_GUIDE_KEY, audioGuide.checked ? "1" : "0");
  if (audioGuide.checked) {
    resumeGuideAudio().catch(() => {});
  } else {
    stopAudioGuide();
  }
});

audioGuideVolume?.addEventListener("input", () => {
  const volume = getAudioGuideVolume();
  localStorage.setItem(AUDIO_GUIDE_VOLUME_KEY, String(volume));
  updateAudioGuideVolumeLabel(volume);
  applyAudioGuideVolume();
});

document.addEventListener("pointerdown", () => {
  resumeGuideAudio().catch(() => {});
}, { capture: true });

document.addEventListener("keydown", () => {
  resumeGuideAudio().catch(() => {});
}, { capture: true });

question.addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const text = question.value.trim();
  if (handleClientControlCommand(text)) return;
  analyze("ask");
});

serverCameraIndex.value = localStorage.getItem(SERVER_CAMERA_INDEX_KEY) || serverCameraIndex.value;
setCameraSourceActive();
initVoiceRate();
initAudioGuideSettings();
initAssistGoal();
ptzAuto.checked = localStorage.getItem(PTZ_AUTO_KEY) === "1";
if (audioGuide) audioGuide.checked = localStorage.getItem(AUDIO_GUIDE_KEY) !== "0";
loadAudioDevices(false).catch(() => {});
window.setTimeout(warmupVoice, 1500);
loadStatus();
