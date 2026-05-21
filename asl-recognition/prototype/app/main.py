import asyncio
import base64
import json
import time
import os
from collections import deque

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from prototype.app import config
from prototype.app.services.assembler import LetterAssembler
from prototype.app.services.phrase_mapper import PhraseMapper
from prototype.app.services.recognizer import SignRecognizer
from tts.speech import TTSEngine


app = FastAPI(title="VoFaLink Prototype")
app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

recognizer = SignRecognizer()
phrase_mapper = PhraseMapper(config.PHRASES_FILE)
tts_engine = TTSEngine(voice=os.getenv("VOFALINK_TTS_VOICE", "fr-FR-DeniseNeural"))


@app.get("/")
async def index():
    return FileResponse(str(config.STATIC_DIR / "index.html"))


@app.websocket("/ws")
async def ws_stream(websocket: WebSocket):
    await websocket.accept()
    mode = "alphabet"
    previous_mode = mode
    assembler = LetterAssembler(
        history_size=config.ASSEMBLER_HISTORY,
        min_stable_count=config.ASSEMBLER_MIN_STABLE,
        cooldown_seconds=config.ASSEMBLER_COOLDOWN,
        word_timeout_seconds=config.ASSEMBLER_WORD_TIMEOUT,
    )
    phrase_history = deque(maxlen=config.PHRASE_HISTORY_SIZE)
    last_phrase_ts = 0.0
    last_spoken_phrase = ""

    try:
        while True:
            payload = json.loads(await websocket.receive_text())
            mode = payload.get("mode", mode)
            if mode != previous_mode:
                recognizer.reset_sequence()
                phrase_history.clear()
                previous_mode = mode

            image_data = payload.get("image")
            if not image_data or "," not in image_data:
                continue

            frame_bytes = base64.b64decode(image_data.split(",", 1)[1])
            np_arr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            loop = asyncio.get_running_loop()

            if mode == "phrase":
                raw_label, confidence, margin, rendered = await loop.run_in_executor(None, recognizer.predict_word_gesture, frame)
                accepted_label = None
                if (
                    raw_label
                    and confidence >= config.WORD_THRESHOLD
                    and margin >= config.TOP2_MARGIN
                ):
                    phrase_history.append(raw_label)
                    candidate = max(set(phrase_history), key=phrase_history.count)
                    if phrase_history.count(candidate) >= config.PHRASE_MIN_STABLE:
                        accepted_label = candidate
                elif raw_label:
                    phrase_history.append(raw_label)

                display_label = accepted_label or raw_label
                gesture_phrase = phrase_mapper.phrase_from_gesture(accepted_label)
                audio_b64 = ""
                now = time.time()
                if gesture_phrase:
                    last_phrase_ts = now
                    if gesture_phrase != last_spoken_phrase:
                        audio_b64 = await tts_engine.generate_audio_b64(gesture_phrase)
                        if audio_b64:
                            last_spoken_phrase = gesture_phrase
                elif (now - last_phrase_ts) > 3.0:
                    gesture_phrase = None

                _, jpg = cv2.imencode(".jpg", rendered, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                await websocket.send_json(
                    {
                        "mode": "phrase",
                        "label": display_label,
                        "confidence": confidence,
                        "margin": margin,
                        "phrase": gesture_phrase,
                        "built_text": assembler.update(None, 0.0).built_text,
                        "audio_b64": audio_b64,
                        "image": "data:image/jpeg;base64," + base64.b64encode(jpg).decode("utf-8"),
                    }
                )
                continue

            letter, confidence, rendered = await loop.run_in_executor(None, recognizer.predict_letter, frame)
            state = assembler.update(letter, confidence)
            mapped_phrase = phrase_mapper.phrase_from_word(state.current_word) or phrase_mapper.phrase_from_word(state.built_text)
            audio_b64 = ""
            if mapped_phrase and mapped_phrase != last_spoken_phrase:
                audio_b64 = await tts_engine.generate_audio_b64(mapped_phrase)
                if audio_b64:
                    last_spoken_phrase = mapped_phrase

            _, jpg = cv2.imencode(".jpg", rendered, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            await websocket.send_json(
                {
                    "mode": "alphabet",
                    "letter": letter,
                    "confidence": confidence,
                    "current_word": state.current_word,
                    "built_text": state.built_text,
                    "phrase": mapped_phrase,
                    "audio_b64": audio_b64,
                    "image": "data:image/jpeg;base64," + base64.b64encode(jpg).decode("utf-8"),
                }
            )

    except WebSocketDisconnect:
        recognizer.reset_sequence()
