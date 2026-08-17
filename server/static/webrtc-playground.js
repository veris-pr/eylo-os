// =============================================================================
// COMPLETE WEBSOCKET AUDIO CLIENT WITH PCM CONVERSION
// =============================================================================

// =============================================================================
// CONFIGURATION
// =============================================================================
const AUDIO_CONFIG = {
  // Choose audio processing method: 'worklet' (modern) or 'script' (compatible)
  processingMethod: "worklet", // Change to 'script' for older browser support

  // Audio settings to match Deepgram
  targetSampleRate: 16000, // 16kHz for Deepgram
  targetChannels: 1, // Mono
  encoding: "LINEAR16", // PCM format

  // Buffer settings
  bufferDurationMs: 100, // Send audio every 100ms

  // WebSocket settings
  pingInterval: 10000, // 10 seconds
  reconnectDelay: 3000, // 3 seconds
  maxReconnectAttempts: 5,
};

// =============================================================================
// AUDIO PROCESSOR CLASSES
// =============================================================================

// Modern Audio Worklet Processor (preferred)
class WorkletAudioProcessor {
  constructor(socket) {
    this.socket = socket;
    this.audioContext = null;
    this.workletNode = null;
    this.sourceNode = null;
    this.stream = null;
    this.isProcessing = false;
    this.sampleBuffer = [];
    this.bufferSize =
      AUDIO_CONFIG.targetSampleRate * (AUDIO_CONFIG.bufferDurationMs / 1000);

    console.log("WorkletAudioProcessor initialized");
  }

  async initialize() {
    try {
      this.audioContext = new (window.AudioContext ||
        window.webkitAudioContext)();
      console.log(`Audio context created: ${this.audioContext.sampleRate}Hz`);

      // Create and register the worklet
      const workletBlob = this.createWorkletBlob();
      await this.audioContext.audioWorklet.addModule(workletBlob);

      // Create worklet node
      this.workletNode = new AudioWorkletNode(
        this.audioContext,
        "pcm-processor",
        {
          processorOptions: {
            targetSampleRate: AUDIO_CONFIG.targetSampleRate,
            sourceSampleRate: this.audioContext.sampleRate,
          },
        },
      );

      // Handle processed audio data
      this.workletNode.port.onmessage = (event) => {
        if (event.data.type === "audioData") {
          this.handleProcessedAudio(event.data.audioData);
        }
      };

      return true;
    } catch (error) {
      console.error("Failed to initialize WorkletAudioProcessor:", error);
      return false;
    }
  }

  createWorkletBlob() {
    const workletCode = `
      class PCMProcessor extends AudioWorkletProcessor {
        constructor(options) {
          super();

          this.targetSampleRate = options.processorOptions.targetSampleRate;
          this.sourceSampleRate = options.processorOptions.sourceSampleRate;
          this.ratio = this.sourceSampleRate / this.targetSampleRate;

          // Resampling state
          this.phase = 0;

          console.log(\`PCM Worklet: \${this.sourceSampleRate}Hz -> \${this.targetSampleRate}Hz (ratio: \${this.ratio})\`);
        }

        process(inputs, outputs, parameters) {
          const input = inputs[0];
          if (!input || !input[0] || input[0].length === 0) return true;

          const inputData = input[0]; // First channel
          const outputSamples = [];

          // Linear interpolation resampling
          for (let i = 0; i < inputData.length; i++) {
            // Check if we should output a sample
            while (this.phase < (i + 1)) {
              const index = Math.floor(this.phase);
              const fraction = this.phase - index;

              let sample;
              if (index + 1 < inputData.length) {
                // Linear interpolation
                sample = inputData[index] * (1 - fraction) + inputData[index + 1] * fraction;
              } else {
                sample = inputData[index];
              }

              // Convert to 16-bit PCM
              const pcmSample = Math.max(-32768, Math.min(32767, Math.round(sample * 32767)));
              outputSamples.push(pcmSample);

              // Advance phase
              this.phase += this.ratio;
            }
          }

          // Adjust phase for next buffer
          this.phase -= inputData.length;

          if (outputSamples.length > 0) {
            this.port.postMessage({
              type: 'audioData',
              audioData: new Int16Array(outputSamples)
            });
          }

          return true;
        }
      }

      registerProcessor('pcm-processor', PCMProcessor);
    `;

    const blob = new Blob([workletCode], { type: "application/javascript" });
    return URL.createObjectURL(blob);
  }

  async startRecording(deviceId = "default") {
    try {
      if (!this.audioContext) {
        const initialized = await this.initialize();
        if (!initialized) throw new Error("Failed to initialize");
      }

      // Get microphone stream
      const constraints = {
        audio: {
          deviceId: deviceId === "default" ? undefined : { exact: deviceId },
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: { exact: 1 },
        },
      };

      this.stream = await navigator.mediaDevices.getUserMedia(constraints);

      // Log actual settings
      const track = this.stream.getAudioTracks()[0];
      const settings = track.getSettings();
      console.log("Microphone settings:", settings);

      // Connect audio pipeline
      this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);
      this.sourceNode.connect(this.workletNode);

      this.isProcessing = true;
      this.sendAudioConfig();

      console.log("WorkletAudioProcessor started");
      return true;
    } catch (error) {
      console.error("Failed to start WorkletAudioProcessor:", error);
      return false;
    }
  }

  handleProcessedAudio(audioData) {
    if (!this.isProcessing) return;

    // Accumulate samples
    this.sampleBuffer.push(...audioData);

    // Send when buffer is full
    if (this.sampleBuffer.length >= this.bufferSize) {
      this.sendAudioBuffer();
    }
  }

  sendAudioBuffer() {
    if (this.sampleBuffer.length === 0) return;

    const int16Array = new Int16Array(this.sampleBuffer);
    const arrayBuffer = int16Array.buffer.slice();

    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(arrayBuffer);
      addLog(
        "audio-logs",
        `Sent ${this.sampleBuffer.length} samples (${arrayBuffer.byteLength} bytes)`,
        "info",
      );
    }

    this.sampleBuffer = [];
  }

  sendAudioConfig() {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;

    const config = {
      kind: "audio_config",
      data: {
        sample_rate: AUDIO_CONFIG.targetSampleRate,
        encoding: AUDIO_CONFIG.encoding,
        channels: AUDIO_CONFIG.targetChannels,
        language: "en-US",
      },
    };

    this.socket.send(JSON.stringify(config));
    console.log("Audio config sent:", config.data);
  }

  flush() {
    if (this.sampleBuffer.length > 0) {
      this.sendAudioBuffer();
    }
  }

  stopRecording() {
    this.isProcessing = false;

    this.flush();

    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }

    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }

    if (this.audioContext && this.audioContext.state !== "closed") {
      this.audioContext.close();
      this.audioContext = null;
    }

    console.log("WorkletAudioProcessor stopped");
  }
}

// Compatible Script Processor (fallback)
class ScriptAudioProcessor {
  constructor(socket) {
    this.socket = socket;
    this.audioContext = null;
    this.scriptProcessor = null;
    this.sourceNode = null;
    this.stream = null;
    this.isProcessing = false;
    this.sampleBuffer = [];
    this.bufferSize =
      AUDIO_CONFIG.targetSampleRate * (AUDIO_CONFIG.bufferDurationMs / 1000);

    console.log("ScriptAudioProcessor initialized");
  }

  async startRecording(deviceId = "default") {
    try {
      this.audioContext = new (window.AudioContext ||
        window.webkitAudioContext)();
      console.log(`Audio context created: ${this.audioContext.sampleRate}Hz`);

      // Get microphone stream
      const constraints = {
        audio: {
          deviceId: deviceId === "default" ? undefined : { exact: deviceId },
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: { exact: 1 },
        },
      };

      this.stream = await navigator.mediaDevices.getUserMedia(constraints);

      // Log actual settings
      const track = this.stream.getAudioTracks()[0];
      const settings = track.getSettings();
      console.log("Microphone settings:", settings);

      // Create script processor
      const bufferSize = 4096;
      this.scriptProcessor = this.audioContext.createScriptProcessor(
        bufferSize,
        1,
        1,
      );

      const decimationFactor = Math.round(
        this.audioContext.sampleRate / AUDIO_CONFIG.targetSampleRate,
      );
      console.log(`Decimation factor: ${decimationFactor}`);

      this.scriptProcessor.onaudioprocess = (event) => {
        if (!this.isProcessing) return;

        const inputData = event.inputBuffer.getChannelData(0);
        const outputSamples = [];

        // Simple decimation - take every Nth sample
        for (let i = 0; i < inputData.length; i += decimationFactor) {
          const sample = Math.max(
            -32768,
            Math.min(32767, Math.round(inputData[i] * 32767)),
          );
          outputSamples.push(sample);
        }

        this.sampleBuffer.push(...outputSamples);

        if (this.sampleBuffer.length >= this.bufferSize) {
          this.sendAudioBuffer();
        }
      };

      // Connect audio pipeline
      this.sourceNode = this.audioContext.createMediaStreamSource(this.stream);
      this.sourceNode.connect(this.scriptProcessor);
      this.scriptProcessor.connect(this.audioContext.destination);

      this.isProcessing = true;
      this.sendAudioConfig();

      console.log("ScriptAudioProcessor started");
      return true;
    } catch (error) {
      console.error("Failed to start ScriptAudioProcessor:", error);
      return false;
    }
  }

  sendAudioBuffer() {
    if (this.sampleBuffer.length === 0) return;

    const int16Array = new Int16Array(this.sampleBuffer);
    const arrayBuffer = int16Array.buffer.slice();

    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(arrayBuffer);
      addLog(
        "audio-logs",
        `Sent ${this.sampleBuffer.length} samples (${arrayBuffer.byteLength} bytes)`,
        "info",
      );
    }

    this.sampleBuffer = [];
  }

  sendAudioConfig() {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;

    const config = {
      kind: "audio_config",
      data: {
        sample_rate: AUDIO_CONFIG.targetSampleRate,
        encoding: AUDIO_CONFIG.encoding,
        channels: AUDIO_CONFIG.targetChannels,
        language: "en-US",
      },
    };

    this.socket.send(JSON.stringify(config));
    console.log("Audio config sent:", config.data);
  }

  flush() {
    if (this.sampleBuffer.length > 0) {
      this.sendAudioBuffer();
    }
  }

  stopRecording() {
    this.isProcessing = false;

    this.flush();

    if (this.stream) {
      this.stream.getTracks().forEach((track) => track.stop());
      this.stream = null;
    }

    if (this.scriptProcessor) {
      this.scriptProcessor.disconnect();
      this.scriptProcessor = null;
    }

    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }

    if (this.audioContext && this.audioContext.state !== "closed") {
      this.audioContext.close();
      this.audioContext = null;
    }

    console.log("ScriptAudioProcessor stopped");
  }
}

// =============================================================================
// AUDIO PROCESSOR FACTORY
// =============================================================================

function createAudioProcessor(socket) {
  if (AUDIO_CONFIG.processingMethod === "worklet") {
    // Check if AudioWorklet is supported
    if (window.AudioWorklet) {
      addLog("audio-logs", "Using AudioWorklet processor (modern)", "info");
      return new WorkletAudioProcessor(socket);
    } else {
      addLog(
        "audio-logs",
        "AudioWorklet not supported, falling back to ScriptProcessor",
        "warning",
      );
      return new ScriptAudioProcessor(socket);
    }
  } else {
    addLog("audio-logs", "Using ScriptProcessor (compatible mode)", "info");
    return new ScriptAudioProcessor(socket);
  }
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

function uuidv4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
    const r = (Math.random() * 16) | 0,
      v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function formatTimestamp(date) {
  return (
    date.toLocaleTimeString("en-US", { hour12: false }) +
    "." +
    date.getMilliseconds().toString().padStart(3, "0")
  );
}

function addLog(containerId, text, type = "info") {
  const logContainer = document.getElementById(containerId);
  if (!logContainer) return;

  const entry = document.createElement("div");
  entry.className = `log-entry ${type}`;

  const timestamp = document.createElement("span");
  timestamp.className = "timestamp";
  timestamp.textContent = formatTimestamp(new Date());

  const content = document.createElement("span");
  content.textContent = text;

  entry.appendChild(timestamp);
  entry.appendChild(content);

  logContainer.appendChild(entry);
  logContainer.scrollTop = logContainer.scrollHeight;
}

// =============================================================================
// AUDIO PLAYBACK SYSTEM (from your original code)
// =============================================================================

const DEFAULT_VOLUME = 1.0;
const VISUALIZER_FFT_SIZE = 256;
let audioContext = null;
let gainNode = null;
let analyserNode = null;
let audioQueue = [];
let isPlayingAudio = false;
let visualizerContext = null;

function initAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    gainNode = audioContext.createGain();
    gainNode.gain.value = DEFAULT_VOLUME;

    analyserNode = audioContext.createAnalyser();
    analyserNode.fftSize = VISUALIZER_FFT_SIZE;

    gainNode.connect(analyserNode);
    analyserNode.connect(audioContext.destination);
  }

  if (audioContext.state === "suspended") {
    audioContext.resume();
  }
}

function processAudioData(data, config) {
  initAudioContext();

  if (data instanceof Blob) {
    const reader = new FileReader();
    reader.onload = function (event) {
      const arrayBuffer = event.target.result;
      audioQueue.push({
        buffer: arrayBuffer,
        format: data.type.includes("mp3") ? "mp3" : config.format,
        sampleRate: config.sampleRate,
      });

      if (!isPlayingAudio) {
        playNextAudioBuffer();
      }
    };
    reader.readAsArrayBuffer(data);
  } else {
    audioQueue.push({
      buffer: data,
      format: config.format,
      sampleRate: config.sampleRate,
    });

    if (!isPlayingAudio) {
      playNextAudioBuffer();
    }
  }
}

function processBase64AudioData(base64String, config) {
  initAudioContext();

  try {
    let dataUrl;
    if (base64String.startsWith("data:audio/")) {
      dataUrl = base64String;
    } else {
      dataUrl = `data:audio/mp3;base64,${base64String}`;
    }

    addLog(
      "audio-logs",
      `Processing base64 audio (${base64String.substring(0, 20)}...)`,
      "info",
    );

    const audioEl = new Audio(dataUrl);
    const source = audioContext.createMediaElementSource(audioEl);
    source.connect(gainNode);

    audioEl.onended = () => {
      source.disconnect();
      addLog("audio-logs", "Base64 audio playback completed", "info");
    };

    audioEl
      .play()
      .then(() => {
        addLog("audio-logs", "Base64 audio playback started", "info");
      })
      .catch((error) => {
        addLog(
          "audio-logs",
          `Error with direct play, trying ArrayBuffer method: ${error.message}`,
          "warning",
        );

        const base64Data = dataUrl.split(",")[1];
        const binaryString = atob(base64Data);
        const bytes = new Uint8Array(binaryString.length);
        for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
        }

        audioQueue.push({
          buffer: bytes.buffer,
          format: "mp3",
          sampleRate: config.sampleRate,
        });

        if (!isPlayingAudio) {
          playNextAudioBuffer();
        }
      });
  } catch (error) {
    addLog(
      "audio-logs",
      `Error processing base64 audio data: ${error.message}`,
      "error",
    );
  }
}

function playNextAudioBuffer() {
  if (audioQueue.length === 0) {
    isPlayingAudio = false;
    return;
  }

  isPlayingAudio = true;
  const nextItem = audioQueue.shift();

  addLog(
    "audio-logs",
    `Processing audio buffer: format=${nextItem.format || "unknown"}, size=${
      nextItem.buffer.byteLength
    } bytes`,
    "info",
  );

  audioContext.decodeAudioData(
    nextItem.buffer,
    (decodedBuffer) => {
      const source = audioContext.createBufferSource();
      source.buffer = decodedBuffer;
      source.connect(gainNode);

      source.onended = playNextAudioBuffer;
      source.start(0);

      addLog(
        "audio-logs",
        `Started playback: duration=${decodedBuffer.duration.toFixed(
          2,
        )}s, channels=${decodedBuffer.numberOfChannels}`,
        "info",
      );
    },
    (error) => {
      console.error("Error decoding audio data:", error);
      addLog(
        "audio-logs",
        `Failed to decode audio buffer: ${error.message}`,
        "error",
      );
      playNextAudioBuffer();
    },
  );
}

function setupAudioPlayback(socket, options = {}) {
  const config = {
    visualizerCanvasId: options.visualizerCanvasId || "audio-output-visualizer",
    volumeControl: options.volumeControl || "test-volume",
    statusElement: options.statusElement || "tts-status",
    sampleRate: options.sampleRate || 44100,
    format: options.format || "linear16",
  };

  initAudioContext();

  if (config.visualizerCanvasId) {
    const canvas = document.getElementById(config.visualizerCanvasId);
    if (canvas) {
      visualizerContext = canvas.getContext("2d");
      if (!visualizerAnimationFrame) {
        updateVisualizer();
      }
    }
  }

  if (config.volumeControl) {
    const volumeControl = document.getElementById(config.volumeControl);
    if (volumeControl) {
      if (gainNode) {
        gainNode.gain.value = volumeControl.value;
      }

      volumeControl.addEventListener("input", () => {
        if (gainNode) {
          gainNode.gain.value = volumeControl.value;
        }
      });
    }
  }

  function isBytes(data) {
    return (
      data instanceof ArrayBuffer ||
      data instanceof Uint8Array ||
      data instanceof Blob ||
      (typeof Buffer !== "undefined" && data instanceof Buffer)
    );
  }

  const originalOnMessage = socket.onmessage;
  socket.onmessage = function (event) {
    if (isBytes(event.data)) {
      const sizeInfo = event.data.byteLength
        ? `${event.data.byteLength} bytes`
        : `${Math.round(event.data.size / 1024)} KB`;

      addLog("audio-logs", `Received binary audio data: ${sizeInfo}`, "info");

      if (config.statusElement) {
        const statusEl = document.getElementById(config.statusElement);
        if (statusEl) {
          statusEl.textContent = "Playing audio...";
          statusEl.className = "status success";
        }
      }

      processAudioData(event.data, config);
      return;
    }

    if (typeof event.data === "string") {
      try {
        const jsonData = JSON.parse(event.data);

        if (jsonData.audio) {
          addLog(
            "audio-logs",
            `Received base64-encoded audio data (${jsonData.audio.length} chars)`,
            "info",
          );

          if (config.statusElement) {
            const statusEl = document.getElementById(config.statusElement);
            if (statusEl) {
              statusEl.textContent = "Playing audio...";
              statusEl.className = "status success";
            }
          }

          processBase64AudioData(jsonData.audio, config);
          return;
        }
      } catch (error) {
        // Not JSON, continue
      }
    }

    if (originalOnMessage) {
      originalOnMessage.call(this, event);
    }
  };

  return {
    setVolume: (value) => {
      if (gainNode) {
        gainNode.gain.value = value;
      }
    },
    getVolume: () => (gainNode ? gainNode.gain.value : 0),
    stopPlayback: () => {
      audioQueue = [];
      isPlayingAudio = false;
    },
  };
}

let visualizerAnimationFrame = null;

function updateVisualizer() {
  visualizerAnimationFrame = requestAnimationFrame(updateVisualizer);

  if (!analyserNode || !visualizerContext) return;

  const canvas = visualizerContext.canvas;
  visualizerContext.clearRect(0, 0, canvas.width, canvas.height);

  const dataArray = new Uint8Array(analyserNode.frequencyBinCount);
  analyserNode.getByteFrequencyData(dataArray);

  const barWidth = canvas.width / dataArray.length;
  let x = 0;

  visualizerContext.fillStyle = "#4CAF50";
  for (let i = 0; i < dataArray.length; i++) {
    const barHeight = (dataArray[i] / 255) * canvas.height;
    visualizerContext.fillRect(
      x,
      canvas.height - barHeight,
      barWidth,
      barHeight,
    );
    x += barWidth + 1;
  }
}

// =============================================================================
// WEBSOCKET HANDLING
// =============================================================================

let socket = null;
let pingInterval = null;
let reconnectTimeout = null;
let reconnectAttempts = 0;
let wsConfig = { url: "", orgId: "", sessionId: "" };
let wsCreatedForAudio = false;

// Current audio processor instance
let audioProcessor = null;

function startPingPong() {
  if (pingInterval) {
    clearInterval(pingInterval);
  }

  pingInterval = setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      const pingMessage = {
        kind: "ping",
        data: { timestamp: Date.now() },
      };
      socket.send(JSON.stringify(pingMessage));
      addLog("ws-logs", "Ping sent", "info");
    }
  }, AUDIO_CONFIG.pingInterval);

  addLog(
    "ws-logs",
    `Ping-pong heartbeat started (${
      AUDIO_CONFIG.pingInterval / 1000
    }s interval)`,
    "info",
  );
}

function stopPingPong() {
  if (pingInterval) {
    clearInterval(pingInterval);
    pingInterval = null;
    addLog("ws-logs", "Ping-pong heartbeat stopped", "info");
  }
}

function connectWebSocket(url, orgId, sessionId, isReconnect = false) {
  try {
    wsConfig.url = url;
    wsConfig.orgId = orgId;
    wsConfig.sessionId = sessionId;

    let fullUrl = url;
    if (!fullUrl.includes("{organization_id}") && !fullUrl.includes(orgId)) {
      fullUrl = `${url}/${orgId}/${sessionId}`;
    } else {
      fullUrl = fullUrl
        .replace("{organization_id}", orgId)
        .replace("{session_id}", sessionId);
    }

    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
      reconnectTimeout = null;
    }

    const statusEl = document.getElementById("ws-status");
    if (statusEl) {
      statusEl.textContent = isReconnect
        ? `Reconnecting (Attempt ${reconnectAttempts + 1}/${
            AUDIO_CONFIG.maxReconnectAttempts
          })...`
        : "Connecting...";
      statusEl.className = "status warning";
    }

    socket = new WebSocket(fullUrl);

    socket.onopen = function () {
      addLog(
        "ws-logs",
        `${isReconnect ? "Reconnected" : "Connected"} to ${fullUrl}`,
        "info",
      );

      if (statusEl) {
        statusEl.textContent = "Connected";
        statusEl.className = "status success";
      }

      // Update UI elements if they exist
      const connectBtn = document.getElementById("ws-connect");
      const disconnectBtn = document.getElementById("ws-disconnect");
      const sendBtn = document.getElementById("send-message");
      const startRecBtn = document.getElementById("start-recording");
      const audioStatusEl = document.getElementById("audio-status");

      if (connectBtn) connectBtn.disabled = true;
      if (disconnectBtn) disconnectBtn.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
      if (startRecBtn) startRecBtn.disabled = false;
      if (audioStatusEl) {
        audioStatusEl.textContent =
          "Ready to record" +
          (wsCreatedForAudio ? " (dedicated connection)" : "");
      }

      reconnectAttempts = 0;
      startPingPong();
    };

    socket.onmessage = function (event) {
      if (event.data instanceof ArrayBuffer) {
        addLog(
          "audio-logs",
          `Received binary data: ${event.data.byteLength} bytes`,
          "info",
        );
        const ttsStatusEl = document.getElementById("tts-status");
        if (ttsStatusEl) ttsStatusEl.textContent = "Playing audio response...";
        return;
      }

      try {
        const data = JSON.parse(event.data);

        if (data.kind === "error") {
          addLog(
            "ws-logs",
            `ERROR: ${data.data?.message || "Unknown error"}`,
            "error",
          );
          console.error("WebSocket Error:", data);
          return;
        }

        if (data.kind === "pong") {
          addLog("ws-logs", "Pong received", "info");
          if (data.data && data.data.timestamp) {
            const latency = Date.now() - data.data.timestamp;
            addLog("ws-logs", `Latency: ${latency}ms`, "info");
          }
        } else {
          addLog(
            "ws-logs",
            `Received: ${JSON.stringify(data, null, 2)}`,
            "info",
          );
        }

        if (data.kind === "transcription") {
          updateTranscription(data.data);
        } else if (
          data.kind === "audio_response" ||
          data.kind === "audio_response_chunk" ||
          data.kind === "audio_response_start"
        ) {
          addLog("audio-logs", `Received audio response: ${data.kind}`, "info");
          const ttsStatusEl = document.getElementById("tts-status");
          if (ttsStatusEl)
            ttsStatusEl.textContent = "Processing audio response...";

          if (data.audio) {
            addLog("audio-logs", "Message contains base64 audio data", "info");
          }
        } else if (data.kind === "audio_response_end") {
          addLog("audio-logs", "Audio response completed", "info");
          const ttsStatusEl = document.getElementById("tts-status");
          if (ttsStatusEl) ttsStatusEl.textContent = "Audio playback completed";
        }
      } catch (e) {
        addLog(
          "ws-logs",
          `Received non-JSON message: ${
            typeof event.data === "string"
              ? event.data.substring(0, 100) + "..."
              : "non-string data"
          }`,
          "warning",
        );
        console.error("Error parsing WebSocket message:", e);
      }
    };

    // Set up audio playback
    const audioPlaybackControls = setupAudioPlayback(socket, {
      visualizerCanvasId: "audio-output-visualizer",
      volumeControl: "test-volume",
      statusElement: "tts-status",
    });

    socket.onerror = function (error) {
      addLog("ws-logs", "WebSocket error", "error");
      if (statusEl) {
        statusEl.textContent = "Error";
        statusEl.className = "status error";
      }
    };

    socket.onclose = function (event) {
      addLog(
        "ws-logs",
        `WebSocket connection closed: Code ${event.code}${
          event.reason ? " - " + event.reason : ""
        }`,
        "warning",
      );

      if (statusEl) {
        statusEl.textContent = "Disconnected";
        statusEl.className = "status error";
      }

      stopPingPong();

      if (event.code !== 1000 && event.code !== 1001) {
        if (reconnectAttempts < AUDIO_CONFIG.maxReconnectAttempts) {
          reconnectAttempts++;
          const delay =
            AUDIO_CONFIG.reconnectDelay * Math.pow(1.5, reconnectAttempts - 1);

          addLog(
            "ws-logs",
            `Reconnecting in ${
              delay / 1000
            } seconds (attempt ${reconnectAttempts}/${
              AUDIO_CONFIG.maxReconnectAttempts
            })...`,
            "info",
          );

          if (statusEl) {
            statusEl.textContent = `Reconnecting in ${
              delay / 1000
            }s (${reconnectAttempts}/${AUDIO_CONFIG.maxReconnectAttempts})`;
          }

          reconnectTimeout = setTimeout(() => {
            connectWebSocket(
              wsConfig.url,
              wsConfig.orgId,
              wsConfig.sessionId,
              true,
            );
          }, delay);
        } else {
          addLog(
            "ws-logs",
            "Max reconnect attempts reached. Please reconnect manually.",
            "error",
          );
          if (statusEl) statusEl.textContent = "Reconnection failed";
          resetUIAfterDisconnect();
        }
      } else {
        resetUIAfterDisconnect();
      }
    };

    return true;
  } catch (error) {
    addLog("ws-logs", `Failed to create WebSocket: ${error.message}`, "error");
    const statusEl = document.getElementById("ws-status");
    if (statusEl) {
      statusEl.textContent = "Connection failed";
      statusEl.className = "status error";
    }
    resetUIAfterDisconnect();
    return false;
  }
}

function resetUIAfterDisconnect() {
  const connectBtn = document.getElementById("ws-connect");
  const disconnectBtn = document.getElementById("ws-disconnect");
  const sendBtn = document.getElementById("send-message");
  const startRecBtn = document.getElementById("start-recording");
  const stopRecBtn = document.getElementById("stop-recording");

  if (connectBtn) connectBtn.disabled = false;
  if (disconnectBtn) disconnectBtn.disabled = true;
  if (sendBtn) sendBtn.disabled = true;
  if (startRecBtn) startRecBtn.disabled = true;
  if (stopRecBtn) stopRecBtn.disabled = true;

  wsCreatedForAudio = false;
}

function updateTranscription(data) {
  const container = document.getElementById("transcription-container");
  if (!container || !data || !data.text) return;

  const isFinal = data.final !== false;

  if (container.querySelector(".interim") && !isFinal) {
    container.querySelector(".interim").textContent = data.text;
  } else if (container.querySelector(".interim") && isFinal) {
    const finalP = document.createElement("p");
    finalP.className = "final";
    finalP.textContent = data.text;

    container.querySelector(".interim").remove();
    container.appendChild(finalP);

    const interimP = document.createElement("p");
    interimP.className = "interim";
    interimP.textContent = "";
    container.appendChild(interimP);
  } else if (isFinal) {
    const finalP = document.createElement("p");
    finalP.className = "final";
    finalP.textContent = data.text;

    const finals = container.querySelectorAll(".final");
    if (finals.length >= 5) {
      finals[0].remove();
    }

    container.appendChild(finalP);

    if (!container.querySelector(".interim")) {
      const interimP = document.createElement("p");
      interimP.className = "interim";
      interimP.textContent = "";
      container.appendChild(interimP);
    }
  } else {
    container.innerHTML = "";

    const interimP = document.createElement("p");
    interimP.className = "interim";
    interimP.textContent = data.text;
    container.appendChild(interimP);
  }

  if (data.confidence !== undefined) {
    const confidenceIndicator = document.createElement("span");
    confidenceIndicator.className = "confidence";
    confidenceIndicator.textContent = `(${Math.round(data.confidence * 100)}%)`;

    if (isFinal) {
      const finals = container.querySelectorAll(".final");
      if (finals.length > 0) {
        const lastFinal = finals[finals.length - 1];
        lastFinal.appendChild(confidenceIndicator);
      }
    }
  }

  addLog(
    "audio-logs",
    `Transcription received: ${data.text} ${isFinal ? "(final)" : "(interim)"}`,
    "info",
  );
  container.scrollTop = container.scrollHeight;
}

// =============================================================================
// EVENT LISTENERS
// =============================================================================

// Wait for DOM to be ready
document.addEventListener("DOMContentLoaded", function () {
  // Initialize UUIDs if elements exist
  const orgIdEl = document.getElementById("organization-id");
  const sessionIdEl = document.getElementById("session-id");
  const conversationIdEl = document.getElementById("conversation-id");

  if (orgIdEl) orgIdEl.value = uuidv4();
  if (sessionIdEl) sessionIdEl.value = uuidv4();
  if (conversationIdEl) conversationIdEl.value = uuidv4();

  // Tab handling
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", function () {
      const tabId = this.getAttribute("data-tab");

      document
        .querySelectorAll(".tab")
        .forEach((t) => t.classList.remove("active"));
      this.classList.add("active");

      document
        .querySelectorAll(".tab-content")
        .forEach((content) => content.classList.remove("active"));
      const targetContent = document.getElementById(tabId);
      if (targetContent) targetContent.classList.add("active");
    });
  });

  // Clear log buttons
  const clearLogsBtn = document.getElementById("clear-logs");
  const clearAudioLogsBtn = document.getElementById("clear-audio-logs");

  if (clearLogsBtn) {
    clearLogsBtn.addEventListener("click", function () {
      const wsLogs = document.getElementById("ws-logs");
      if (wsLogs) wsLogs.innerHTML = "";
    });
  }

  if (clearAudioLogsBtn) {
    clearAudioLogsBtn.addEventListener("click", function () {
      const audioLogs = document.getElementById("audio-logs");
      if (audioLogs) audioLogs.innerHTML = "";
    });
  }

  // WebSocket connection buttons
  const connectBtn = document.getElementById("ws-connect");
  const disconnectBtn = document.getElementById("ws-disconnect");

  if (connectBtn) {
    connectBtn.addEventListener("click", function () {
      if (socket && socket.readyState === WebSocket.OPEN) {
        addLog("ws-logs", "Already connected to WebSocket", "warning");
        return;
      }

      const wsUrl = document.getElementById("ws-url")?.value;
      const orgId = document.getElementById("organization-id")?.value;
      const sessionId = document.getElementById("session-id")?.value;

      if (!orgId || !sessionId) {
        addLog(
          "ws-logs",
          "Organization ID and Session ID are required",
          "error",
        );
        return;
      }

      connectWebSocket(wsUrl, orgId, sessionId);
    });
  }

  if (disconnectBtn) {
    disconnectBtn.addEventListener("click", function () {
      if (socket) {
        if (reconnectTimeout) {
          clearTimeout(reconnectTimeout);
          reconnectTimeout = null;
        }

        stopPingPong();
        reconnectAttempts = 0;

        if (socket.readyState === WebSocket.OPEN) {
          socket.close(1000, "User initiated disconnect");
        }

        const statusEl = document.getElementById("ws-status");
        if (statusEl) {
          statusEl.textContent = "Disconnected";
          statusEl.className = "status";
        }

        if (wsCreatedForAudio) {
          wsCreatedForAudio = false;
          const audioStatusEl = document.getElementById("audio-status");
          if (audioStatusEl) {
            audioStatusEl.textContent = "WebSocket disconnected";
            audioStatusEl.className = "status error";
          }
        }

        resetUIAfterDisconnect();
        stopRecording();
        addLog("ws-logs", "WebSocket disconnected by user", "info");
      }
    });
  }

  // Message handling
  const messageTypeSelect = document.getElementById("message-type");
  const messagePayloadTextarea = document.getElementById("message-payload");

  if (messageTypeSelect && messagePayloadTextarea) {
    messageTypeSelect.addEventListener("change", function () {
      const messageType = this.value;
      let defaultPayload = {};

      switch (messageType) {
        case "ping":
          defaultPayload = { timestamp: Date.now() };
          break;
        case "message":
          defaultPayload = {
            text: "Hello, world!",
            conversation_id:
              document.getElementById("conversation-id")?.value || uuidv4(),
          };
          break;
        case "identify":
          defaultPayload = { contact_id: uuidv4() };
          break;
        case "start_conversation":
          defaultPayload = {
            from_: { type: "contact", id: uuidv4() },
            to_: { type: "agent", id: "default" },
            context: { source: "webrtc-playground" },
          };
          break;
      }

      messagePayloadTextarea.value = JSON.stringify(defaultPayload, null, 2);
    });

    // Initialize with ping payload
    messagePayloadTextarea.value = JSON.stringify(
      { timestamp: Date.now() },
      null,
      2,
    );
  }

  const sendMessageBtn = document.getElementById("send-message");
  if (sendMessageBtn) {
    sendMessageBtn.addEventListener("click", function () {
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        addLog("ws-logs", "WebSocket is not connected", "error");
        return;
      }

      const messageType = messageTypeSelect?.value;
      let payload;

      try {
        payload = JSON.parse(messagePayloadTextarea?.value || "{}");
      } catch (e) {
        addLog("ws-logs", "Invalid JSON payload", "error");
        return;
      }

      const message = {
        kind: messageType,
        data: payload,
      };

      try {
        socket.send(JSON.stringify(message));
        addLog("ws-logs", `Sent ${messageType} message`, "info");
      } catch (e) {
        addLog("ws-logs", `Failed to send message: ${e.message}`, "error");
      }
    });
  }

  // Audio device loading
  loadAudioDevices();

  // Recording buttons
  const startRecordingBtn = document.getElementById("start-recording");
  const stopRecordingBtn = document.getElementById("stop-recording");

  if (startRecordingBtn) {
    startRecordingBtn.addEventListener("click", async function () {
      // Check WebSocket connection
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        addLog(
          "audio-logs",
          "WebSocket not connected, establishing connection...",
          "info",
        );

        const wsUrl = document.getElementById("ws-url")?.value;
        const orgId = document.getElementById("organization-id")?.value;
        const sessionId = document.getElementById("session-id")?.value;

        if (!orgId || !sessionId) {
          addLog(
            "audio-logs",
            "Organization ID and Session ID are required",
            "error",
          );
          return;
        }

        const connected = connectWebSocket(wsUrl, orgId, sessionId);
        if (!connected) {
          addLog(
            "audio-logs",
            "Failed to establish WebSocket connection",
            "error",
          );
          return;
        }

        wsCreatedForAudio = true;
        await new Promise((resolve) => setTimeout(resolve, 500));

        if (!socket || socket.readyState !== WebSocket.OPEN) {
          addLog(
            "audio-logs",
            "WebSocket connection failed to establish",
            "error",
          );
          return;
        }

        addLog(
          "audio-logs",
          "WebSocket connection established for audio session",
          "success",
        );
      }

      try {
        // Create audio processor based on config
        audioProcessor = createAudioProcessor(socket);

        const deviceId =
          document.getElementById("audio-device")?.value || "default";
        const success = await audioProcessor.startRecording(deviceId);

        if (success) {
          startRecordingBtn.disabled = true;
          if (stopRecordingBtn) stopRecordingBtn.disabled = false;

          const audioStatusEl = document.getElementById("audio-status");
          if (audioStatusEl) {
            audioStatusEl.textContent =
              `Recording (${AUDIO_CONFIG.processingMethod}, ${AUDIO_CONFIG.targetSampleRate}Hz)...` +
              (wsCreatedForAudio ? " (dedicated connection)" : "");
            audioStatusEl.className = "status success";
          }

          addLog(
            "audio-logs",
            `Started recording with ${AUDIO_CONFIG.processingMethod} processor`,
            "info",
          );
        } else {
          throw new Error("Failed to start audio processor");
        }
      } catch (error) {
        addLog(
          "audio-logs",
          `Failed to start recording: ${error.message}`,
          "error",
        );
        const audioStatusEl = document.getElementById("audio-status");
        if (audioStatusEl) {
          audioStatusEl.textContent = `Error: ${error.message}`;
          audioStatusEl.className = "status error";
        }
      }
    });
  }

  if (stopRecordingBtn) {
    stopRecordingBtn.addEventListener("click", function () {
      stopRecording();
    });
  }

  // Pipeline test button
  const testPipelineBtn = document.getElementById("test-pipeline");
  if (testPipelineBtn) {
    testPipelineBtn.addEventListener("click", async function () {
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        addLog(
          "audio-logs",
          "WebSocket not connected, establishing connection...",
          "info",
        );

        const wsUrl = document.getElementById("ws-url")?.value;
        const orgId = document.getElementById("organization-id")?.value;
        const sessionId = document.getElementById("session-id")?.value;

        if (!orgId || !sessionId) {
          addLog(
            "audio-logs",
            "Organization ID and Session ID are required",
            "error",
          );
          return;
        }

        connectWebSocket(wsUrl, orgId, sessionId);
        await new Promise((resolve) => setTimeout(resolve, 500));

        if (!socket || socket.readyState !== WebSocket.OPEN) {
          addLog(
            "audio-logs",
            "WebSocket connection failed to establish",
            "error",
          );
          return;
        }
      }

      const testMessage = {
        kind: "start_conversation",
        data: {
          from_: { type: "contact", id: uuidv4() },
          to_: { type: "agent", id: "default" },
          context: {
            source: "webrtc-playground",
            initial_message:
              "Hello, this is a pipeline test. Can you respond with audio?",
          },
        },
      };

      try {
        socket.send(JSON.stringify(testMessage));
        addLog(
          "audio-logs",
          "Sent test message to trigger STT -> TTS pipeline",
          "info",
        );
        const ttsStatusEl = document.getElementById("tts-status");
        if (ttsStatusEl)
          ttsStatusEl.textContent = "Waiting for audio response...";
      } catch (e) {
        addLog(
          "audio-logs",
          `Failed to send test message: ${e.message}`,
          "error",
        );
      }
    });
  }
});

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

async function loadAudioDevices() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const audioInputs = devices.filter(
      (device) => device.kind === "audioinput",
    );
    const audioDeviceSelect = document.getElementById("audio-device");
    if (!audioDeviceSelect) return;

    audioDeviceSelect.innerHTML = "";

    const defaultOption = document.createElement("option");
    defaultOption.value = "default";
    defaultOption.textContent = "Default Microphone";
    audioDeviceSelect.appendChild(defaultOption);

    audioInputs.forEach((device) => {
      const option = document.createElement("option");
      option.value = device.deviceId;
      option.textContent =
        device.label || `Microphone ${audioDeviceSelect.options.length}`;
      audioDeviceSelect.appendChild(option);
    });
  } catch (e) {
    addLog("audio-logs", `Failed to load audio devices: ${e.message}`, "error");
  }
}

function stopRecording() {
  try {
    if (audioProcessor) {
      audioProcessor.flush();
      audioProcessor.stopRecording();
      audioProcessor = null;
    }

    if (wsCreatedForAudio && socket && socket.readyState === WebSocket.OPEN) {
      addLog(
        "audio-logs",
        "Disconnecting WebSocket created for audio session",
        "info",
      );
      socket.close(1000, "Audio session ended");
      wsCreatedForAudio = false;
    }

    const startRecordingBtn = document.getElementById("start-recording");
    const stopRecordingBtn = document.getElementById("stop-recording");
    const audioStatusEl = document.getElementById("audio-status");

    if (!wsCreatedForAudio) {
      if (startRecordingBtn)
        startRecordingBtn.disabled =
          !socket || socket.readyState !== WebSocket.OPEN;
    }
    if (stopRecordingBtn) stopRecordingBtn.disabled = true;
    if (audioStatusEl) {
      audioStatusEl.textContent = wsCreatedForAudio
        ? "Disconnecting..."
        : "Stopped";
      audioStatusEl.className = "status";
    }

    addLog("audio-logs", "Stopped recording audio", "info");
  } catch (e) {
    addLog("audio-logs", `Error stopping recording: ${e.message}`, "error");
  }
}

// =============================================================================
// CONFIGURATION DISPLAY
// =============================================================================

console.log("WebSocket Audio Client Loaded");
console.log("Current Configuration:", AUDIO_CONFIG);
console.log(
  'Change AUDIO_CONFIG.processingMethod to "script" for compatibility mode',
);
