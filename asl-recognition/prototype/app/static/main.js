const video = document.getElementById("video");
const outputImage = document.getElementById("outputImage");
const letterEl = document.getElementById("letter");
const confidenceEl = document.getElementById("confidence");
const currentWordEl = document.getElementById("currentWord");
const builtTextEl = document.getElementById("builtText");
const phraseEl = document.getElementById("phrase");
const modeLabelEl = document.getElementById("modeLabel");
const statusEl = document.getElementById("status");
const btnAlphabet = document.getElementById("modeAlphabet");
const btnPhrase = document.getElementById("modePhrase");
const btnAudio = document.getElementById("audioToggle");

const canvas = document.createElement("canvas");
const ctx = canvas.getContext("2d", { willReadFrequently: true });

let ws = null;
let connected = false;
let mode = "alphabet";
let audioEnabled = true;
let activeAudio = null;

btnAlphabet.addEventListener("click", () => {
  mode = "alphabet";
  btnAlphabet.classList.add("active");
  btnPhrase.classList.remove("active");
  modeLabelEl.textContent = mode;
});

btnPhrase.addEventListener("click", () => {
  mode = "phrase";
  btnPhrase.classList.add("active");
  btnAlphabet.classList.remove("active");
  modeLabelEl.textContent = mode;
});

btnAudio.addEventListener("click", () => {
  audioEnabled = !audioEnabled;
  btnAudio.textContent = audioEnabled ? "Audio: Actif" : "Audio: Muet";
});

async function setupCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { width: 640, height: 480 },
  });
  video.srcObject = stream;
  await new Promise((resolve) => (video.onloadedmetadata = resolve));
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
}

function connect() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${protocol}://${window.location.host}/ws`);

  ws.onopen = () => {
    connected = true;
    statusEl.textContent = "Connecté";
    sendFrame();
  };

  ws.onclose = () => {
    connected = false;
    statusEl.textContent = "Reconnexion...";
    setTimeout(connect, 1500);
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    outputImage.src = data.image || "";

    letterEl.textContent = data.letter || data.label || "--";
    confidenceEl.textContent = `${((data.confidence || 0) * 100).toFixed(0)}%`;
    currentWordEl.textContent = data.current_word || "--";
    builtTextEl.textContent = data.built_text || "--";
    phraseEl.textContent = data.phrase || "--";
    modeLabelEl.textContent = data.mode || mode;
    if (data.audio_b64 && audioEnabled) {
      if (activeAudio) {
        activeAudio.pause();
      }
      activeAudio = new Audio(`data:audio/mp3;base64,${data.audio_b64}`);
      activeAudio.play().catch((err) => console.error("Lecture audio impossible:", err));
    }

    requestAnimationFrame(sendFrame);
  };
}

function sendFrame() {
  if (!connected || ws.readyState !== WebSocket.OPEN) return;
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  ws.send(
    JSON.stringify({
      mode,
      image: canvas.toDataURL("image/jpeg", 0.82),
    })
  );
}

(async () => {
  try {
    await setupCamera();
    connect();
  } catch (e) {
    statusEl.textContent = "Erreur caméra";
    console.error(e);
  }
})();
