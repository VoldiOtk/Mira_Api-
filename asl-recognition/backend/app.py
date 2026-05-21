from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
from dotenv import load_dotenv

load_dotenv()
import json
import base64
import cv2
import numpy as np
import torch
import asyncio
import time
from collections import deque

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.mediapipe_extractor import MediaPipeExtractor
from utils.gemini_client import GeminiTranslator
from utils.ollama_client import OllamaTranslator
from model.model import ASLLstmModel, HandSignModel
from tts.speech import TTSEngine

tts = TTSEngine(voice="fr-FR-DeniseNeural")
AI_PROVIDER = os.getenv("AI_PROVIDER", "local").strip().lower()
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:e2b").strip()
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


class TranslatorRouter:
    def __init__(self):
        self.provider = AI_PROVIDER
        self.local_translator = OllamaTranslator(
            model_name=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
        self.cloud_translator = GeminiTranslator()

    async def prepare(self):
        if self.provider in {"local", "auto"}:
            await self.local_translator.check_and_start()

    async def translate_asl(self, sign_sequence):
        if self.provider == "local":
            return await self.local_translator.translate_asl(sign_sequence)
        if self.provider == "cloud":
            return await self.cloud_translator.translate_asl(sign_sequence)

        # mode auto: local d'abord pour éviter les tokens, cloud en secours
        local_sentence = await self.local_translator.translate_asl(sign_sequence)
        if "(Ollama hors-ligne)" not in local_sentence:
            return local_sentence
        return await self.cloud_translator.translate_asl(sign_sequence)


ai_translator = TranslatorRouter()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Servir le frontend directement via FastAPI (comme avant !)
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
async def serve_frontend():
    with open(os.path.join(FRONTEND_DIR, "index.html"), encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.on_event("startup")
async def startup_event():
    await ai_translator.prepare()
    print(f"[AI] Provider actif: {AI_PROVIDER}")

# ──────────── CHARGEMENT DYNAMIQUE ────────────
LABELS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'knowledge', 'labels.json')
META_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'model', 'model_meta.json')
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'model', 'model.pth')
SEQUENCE_LENGTH = 30
PREDICTION_THRESHOLD = float(os.getenv("PREDICTION_THRESHOLD", "0.70"))
STABLE_WORD_THRESHOLD = float(os.getenv("STABLE_WORD_THRESHOLD", "0.82"))
TOP2_MARGIN_THRESHOLD = float(os.getenv("TOP2_MARGIN_THRESHOLD", "0.12"))
PREDICTION_HISTORY_SIZE = int(os.getenv("PREDICTION_HISTORY_SIZE", "5"))
MIN_STABLE_COUNT = int(os.getenv("MIN_STABLE_COUNT", "3"))
BUFFER_SILENCE_SECONDS = float(os.getenv("BUFFER_SILENCE_SECONDS", "3.5"))
MIN_WORD_COOLDOWN_SECONDS = float(os.getenv("MIN_WORD_COOLDOWN_SECONDS", "1.0"))
NON_SIGN_LABELS = {
    token.strip().lower()
    for token in os.getenv("NON_SIGN_LABELS", "space,del,nothing,blank").split(",")
    if token.strip()
}

# ──────────── CHARGEMENT DES MODELES ────────────
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')


def load_state_dict_safely(path):
    try:
        return torch.load(path, map_location=device, weights_only=True)
    except TypeError:
        return torch.load(path, map_location=device)

# 1. Modèle LSTM (Vidéos Mots)
with open(LABELS_FILE, 'r', encoding='utf-8') as f:
    translations = json.load(f)

ACTIONS_HOLISTIC = []
if os.path.exists(META_FILE):
    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)
        ACTIONS_HOLISTIC = meta.get('actions', [])
        print(f"[OK] {len(ACTIONS_HOLISTIC)} actions chargées (LSTM)")
else:
    ACTIONS_HOLISTIC = list(translations.keys())

model_holistic = ASLLstmModel(input_size=1662, num_classes=len(ACTIONS_HOLISTIC)).to(device)
if os.path.exists(MODEL_PATH):
    model_holistic.load_state_dict(load_state_dict_safely(MODEL_PATH))
    print(f"[OK] LSTM chargé.")
else:
    print(f"[WARN] LSTM non trouvé.")
model_holistic.eval()

# 2. Modèle Dense (Alphabet Statique)
META_HANDS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'model', 'model_hands_meta.json')
MODEL_HANDS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'model', 'model_hands.pth')

ACTIONS_HANDS = []
model_hands = None
if os.path.exists(META_HANDS_FILE):
    with open(META_HANDS_FILE, 'r', encoding='utf-8') as f:
        meta_h = json.load(f)
        ACTIONS_HANDS = meta_h.get('actions', [])
        print(f"[OK] {len(ACTIONS_HANDS)} actions chargées (Hands)")
    
    model_hands = HandSignModel(input_size=1662, num_classes=len(ACTIONS_HANDS)).to(device)
    if os.path.exists(MODEL_HANDS_PATH):
        model_hands.load_state_dict(load_state_dict_safely(MODEL_HANDS_PATH))
        print(f"[OK] Modèle statique Hands chargé.")
        model_hands.eval()
    else:
        print("[WARN] Modèle statique non trouvé.")
else:
    print("[WARN] model_hands_meta.json introuvable (pas d'alphabet).")


def find_translation(label_asl):
    """Cherche la traduction d'un label dans labels.json"""
    label_lower = label_asl.lower()
    if label_lower in translations:
        t = translations[label_lower]
        return {"en": t.get("en", label_asl), "fr": t.get("fr", label_asl)}
    return {"fr": label_asl, "en": label_asl}


@app.websocket("/ws/video")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("[WS] Nouvelle connexion WebSocket.")
    
    extractor = MediaPipeExtractor(mode='holistic')
    sequence = []
    
    # Historique pour le lissage (Debouncing)
    prediction_history = deque(maxlen=PREDICTION_HISTORY_SIZE)
    
    # Buffer pour Ollama
    sentence_buffer = []
    last_word_time = time.time()
    last_added_time = 0.0
    last_added_word = ""
    
    try:
        while True:
            data_str = await websocket.receive_text()
            data = json.loads(data_str)
            
            # Gestion bascule Hands vs Holistic
            mode = data.get('mode', 'holistic')
            if extractor.mode != mode:
                extractor = MediaPipeExtractor(mode=mode)
                sequence.clear()
                prediction_history.clear()
                last_added_word = ""
            
            image_b64 = data.get('image', '')
            if not image_b64:
                continue

            if "," not in image_b64:
                continue
            img_data = base64.b64decode(image_b64.split(',', 1)[1])
            np_arr = np.frombuffer(img_data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
            
            # INFERENCE MULTITHREADING : Ne pas bloquer la WebSocket !
            loop = asyncio.get_running_loop()
            image_bgr, keypoints = await loop.run_in_executor(None, extractor.process_frame, frame)
            
            sequence.append(keypoints)
            sequence = sequence[-SEQUENCE_LENGTH:]
            
            prediction_label = ""
            confidence = 0.0
            top2_margin = 0.0
            
            if mode == 'holistic':
                # INFERENCE LSTM SEQUENTIELLE
                if len(sequence) == SEQUENCE_LENGTH and os.path.exists(MODEL_PATH) and len(ACTIONS_HOLISTIC) > 0:
                    with torch.no_grad():
                        res = model_holistic(torch.tensor([sequence], dtype=torch.float32).to(device))[0]
                        probs = torch.softmax(res, dim=0)
                        predicted_idx = torch.argmax(res).item()
                        confidence = probs[predicted_idx].item()

                        top_values = torch.topk(probs, k=min(2, probs.shape[0])).values
                        if top_values.shape[0] >= 2:
                            top2_margin = (top_values[0] - top_values[1]).item()
                        else:
                            top2_margin = top_values[0].item()

                    if (
                        predicted_idx < len(ACTIONS_HOLISTIC)
                        and confidence >= PREDICTION_THRESHOLD
                        and top2_margin >= TOP2_MARGIN_THRESHOLD
                    ):
                        prediction_label = ACTIONS_HOLISTIC[predicted_idx]
            else:
                # INFERENCE STATIQUE (Hands Only)
                if model_hands is not None and len(ACTIONS_HANDS) > 0:
                    current_kp = sequence[-1]
                    with torch.no_grad():
                        res = model_hands(torch.tensor([current_kp], dtype=torch.float32).to(device))[0]
                        probs = torch.softmax(res, dim=0)
                        predicted_idx = torch.argmax(res).item()
                        confidence = probs[predicted_idx].item()

                        top_values = torch.topk(probs, k=min(2, probs.shape[0])).values
                        if top_values.shape[0] >= 2:
                            top2_margin = (top_values[0] - top_values[1]).item()
                        else:
                            top2_margin = top_values[0].item()

                    if (
                        predicted_idx < len(ACTIONS_HANDS)
                        and confidence >= PREDICTION_THRESHOLD
                        and top2_margin >= TOP2_MARGIN_THRESHOLD
                    ):
                        prediction_label = ACTIONS_HANDS[predicted_idx]

            # ================= LISSAGE ET BUFFERING =================
            is_stable = False
            stable_label = ""
            basic_fr = ""
            
            if prediction_label:
                if prediction_label.lower() in NON_SIGN_LABELS:
                    prediction_label = ""
                    prediction_history.clear()
                    stable_label = ""
                    basic_fr = ""
                
            if prediction_label:
                prediction_history.append(prediction_label)
                # Trouver le label le plus fréquent dans l'historique récent
                stable_label = max(set(prediction_history), key=prediction_history.count)
                # Il est stable s'il apparaît au moins 3 fois sur 5
                stable_count = prediction_history.count(stable_label)
                is_stable = stable_count >= MIN_STABLE_COUNT
                
                # Traduction instantanée pour l'UI
                trans = find_translation(stable_label)
                basic_fr = trans['fr']

                # Si stable et nouveau, on l'ajoute au buffer de la phrase
                if (
                    is_stable
                    and stable_label != last_added_word
                    and confidence >= STABLE_WORD_THRESHOLD
                    and top2_margin >= TOP2_MARGIN_THRESHOLD
                    and (time.time() - last_added_time) >= MIN_WORD_COOLDOWN_SECONDS
                ):
                    # Ne pas ajouter le mot s'il signifie le vide ou le repos
                    if stable_label.lower() not in ["space", "del", "nothing"]:
                        sentence_buffer.append(stable_label)
                        last_added_word = stable_label
                        last_word_time = time.time()
                        last_added_time = time.time()

            # ================= EVALUATION OLLAMA / GEMINI (PAUSE DETECTEE) =================
            # Protection Quota (15 req/min) : on attend 3.5 sec de "silence visuel" pour valider une phrase
            if len(sentence_buffer) > 0 and (time.time() - last_word_time > BUFFER_SILENCE_SECONDS):
                full_raw_sequence = " ".join(sentence_buffer)
                
                # Vider le buffer pour la prochaine phrase
                sentence_buffer.clear()
                last_added_word = ""
                
                async def generate_and_send_sentence(raw_sequence):
                    try:
                        final_sentence = await ai_translator.translate_asl(raw_sequence)
                        
                        # Générer l'audio haute qualité avec Edge-TTS Azure
                        audio_b64 = await tts.generate_audio_b64(final_sentence)
                        
                        await websocket.send_json({
                            "sentence": final_sentence + " ✨",
                            "audio_b64": audio_b64
                        })
                    except Exception as e:
                        print(f"[ERR] Asynchrone Gemini API : {e}")
                
                asyncio.create_task(generate_and_send_sentence(full_raw_sequence))

            # ================= ENVOI DE LA VIDEO CHAUDE (UI FEEDBACK) =================
            _, buffer = cv2.imencode('.jpg', image_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            out_img_b64 = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')

            if prediction_label and is_stable:
                await websocket.send_json({
                    "label": stable_label,
                    "fr": basic_fr,
                    "confidence": confidence,
                    "margin": top2_margin,
                    "buffer_text": " ".join(sentence_buffer),
                    "image": out_img_b64
                })
            else:
                await websocket.send_json({
                    "buffer_text": " ".join(sentence_buffer),
                    "image": out_img_b64
                })
                
    except WebSocketDisconnect:
        print("[WS] Client déconnecté.")
    except Exception as e:
        print(f"[ERR] Erreur Backend: {e}")
