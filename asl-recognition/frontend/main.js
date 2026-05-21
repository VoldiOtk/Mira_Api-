const video = document.getElementById('videoElement');
const outputImage = document.getElementById('outputImage');
const connStatus = document.getElementById('connStatus');
const signValue = document.getElementById('detectedSign');
const frValue = document.getElementById('translationFr');
const confidenceFill = document.getElementById('confidenceFill');
const wordBuffer = document.getElementById('wordBuffer');
const aiSentence = document.getElementById('aiSentence');
const btnHands = document.getElementById('btnHands');
const btnHolistic = document.getElementById('btnHolistic');
const btnAudio = document.getElementById('btnAudio');

let ws;
let currentMode = 'holistic';
const FPS = 10; 
let isConnected = false;
let isAudioEnabled = true;

btnAudio.addEventListener('click', () => {
    isAudioEnabled = !isAudioEnabled;
    if (isAudioEnabled) {
        btnAudio.textContent = '🔊 Audio: Actif';
        btnAudio.classList.remove('muted');
    } else {
        btnAudio.textContent = '🔇 Audio: Muet';
        btnAudio.classList.add('muted');
    }
});

// Elements drawing canvas invisible
const canvas = document.createElement('canvas');
const ctx = canvas.getContext('2d', { willReadFrequently: true });

async function setupCamera() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ 
            video: { width: 640, height: 480 } 
        });
        video.srcObject = stream;
        await new Promise(resolve => video.onloadedmetadata = resolve);
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        connectWebSocket();
    } catch (e) {
        console.error("Erreur caméra", e);
        connStatus.textContent = "Erreur (Testez sur Firefox/Chrome avec permissions !)";
    }
}

function connectWebSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${wsProtocol}://${window.location.host}/ws/video`;
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        isConnected = true;
        connStatus.textContent = "Connecté & Prêt";
        connStatus.classList.add('connected');
        sendFrames();
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if(data.image) {
            outputImage.src = data.image;
        }
        
        if (data.buffer_text !== undefined) {
            wordBuffer.textContent = data.buffer_text ? `[ ${data.buffer_text} ]` : "[ ... ]";
        }
        
        if (data.sentence) {
            aiSentence.textContent = data.sentence;
        }

        if (data.audio_b64 && isAudioEnabled) {
            // Lecture du fichier audio (Studio Quality) envoyé par le serveur Python !
            let audioPlayer = new Audio("data:audio/mp3;base64," + data.audio_b64);
            audioPlayer.play().catch(e => console.error("Erreur de lecture audio:", e));
        }

        if(data.label && data.confidence > 0.1) {
            signValue.textContent = data.label + ` (${(data.confidence*100).toFixed(0)}%)`;
            if (data.fr) {
                frValue.textContent = data.fr;
                // Note : On ne prononce plus le mot isolé "à la volée", on attend la phrase !
            }
            confidenceFill.style.width = `${Math.min(100, data.confidence * 100)}%`;
        } else if(data.label) {
            signValue.textContent = data.label + " (incertain)";
            confidenceFill.style.width = '5%';
        } else {
            signValue.textContent = "--";
            frValue.textContent = "Prêt.";
            confidenceFill.style.width = '0%';
        }

        // 🚀 PING-PONG SYNC + DEBOUNCING
        // On attend 40ms avant la prochaine capture pour forcer ~25 FPS max.
        // Cela libère complétement la charge sur le Processeur et GPU.
        setTimeout(() => { requestAnimationFrame(sendFrames); }, 40);
    };

    ws.onclose = () => {
        isConnected = false;
        connStatus.textContent = "Déconnecté. Reconnexion...";
        connStatus.classList.remove('connected');
        setTimeout(connectWebSocket, 3000); 
    };
}

function sendFrames() {
    if (!isConnected) return;

    // Draw the current video frame on the canvas to encode it as JPEG base64
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const jpegBase64 = canvas.toDataURL('image/jpeg', 0.8);

    ws.send(JSON.stringify({
        mode: currentMode,
        image: jpegBase64
    }));
    // Note: Plus de setTimeout() aveugle ! La boucle est gérée par onmessage.
}

btnHands.addEventListener('click', () => {
    currentMode = 'hands';
    btnHands.classList.add('active');
    btnHolistic.classList.remove('active');
});

btnHolistic.addEventListener('click', () => {
    currentMode = 'holistic';
    btnHolistic.classList.add('active');
    btnHands.classList.remove('active');
});

setupCamera();
