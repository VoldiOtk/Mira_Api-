# Mira Translation Pipeline — Technical Report (v2)

Branch: `feature/mira-translation-v2`  
Base commit: `f55ace3`

---

## Summary

This branch transforms Mira from a frame-by-frame sign labeller into a full **sequence understanding + natural language reconstruction** pipeline.

---

## Architecture

```
Camera (3fps)
    │
    ▼
realtime_push_frame()
    │   base64 → MediaPipe → predict_frame() → label + confidence
    │
    ▼
SignSequenceBuilder.push_prediction(label, confidence)
    │   smoothing window=5, stable_frames=3, duplicate_cooldown=1500ms
    │   → confirmed_sequence (List[str]), pending_sign
    │
    ▼
POST /realtime/sessions/{sid}/finalize  (user or auto-trigger)
    │
    ├── KnowledgeBaseResolver.resolve_signs(signs)
    │       loads labels.json (64 signs), builds sign_details + literal_sequence
    │
    └── LLMTranslationProvider.translate_sequence(signs, kb_context, lang)
            ├── GeminiTranslationProvider → GeminiTranslator.translate_sequence_structured()
            │       fallback chain: gemma-4 → gemma-3-27b → gemini-2.0-flash → gemini-1.5-flash
            └── LocalFallbackTranslationProvider → rule-based (no external API)
                    returns: natural_translation, literal_translation, intent,
                             confidence, provider, fallback, suggested_missing_signs
```

---

## Components Delivered

### Backend

| File | Description |
|------|-------------|
| `utils/llm_provider.py` | `LLMTranslationProvider` ABC + `GeminiTranslationProvider` + `LocalFallbackTranslationProvider` + `get_llm_provider()` factory |
| `utils/gemini_client.py` | Added `translate_sequence_structured()` — structured JSON output with retry chain |
| `backend/services/sign_sequence_builder.py` | `SignSequenceBuilder` with smoothing, duplicate guard, auto-finalize |
| `backend/services/knowledge_base_resolver.py` | `KnowledgeBaseResolver` loading labels.json, KB context builder |
| `backend/routers/inference_router.py` | New endpoints: `POST /finalize`, `POST /translate/simulate`; updated session CRUD |
| `backend/schemas.py` | `RecognizeResponse` + `confirmed_sequence`, `pending_sign` fields |
| `data/knowledge/labels.json` | 64 signs (was 48), all with description + intent + related_signs |
| `.env.example` | `LLM_PROVIDER`, `LLM_TRANSLATION_ENABLED`, `LLM_TIMEOUT_SECONDS`, `SEQUENCE_*` tunables |

### Frontend

| File | Description |
|------|-------------|
| `frontend/espace-client/live-reconnaissance.html` | AI-Native dark UI: status machine, confidence chips, provider badge, `/finalize` wiring |
| `frontend/dashboardadmin/src/pages/mira/Playground.jsx` | New "Simulation séquence" tab → `/translate/simulate` |

### Tests

| File | Coverage |
|------|----------|
| `tests/test_sign_sequence_builder.py` | Confirmation logic, smoothing, duplicate guard, reset, auto-finalize, registry |
| `tests/test_knowledge_resolver.py` | resolve_signs, build_llm_context, get_translation, analyze_kb |
| `tests/test_llm_provider.py` | LocalFallbackProvider contracts, intent detection, get_llm_provider factory |

---

## New API Endpoints

### `POST /api/v1/realtime/sessions/{session_id}/finalize`

Finalizes an active session by running the full LLM pipeline on the accumulated sign sequence.

**Request body:**
```json
{ "lang": "fr", "force": false }
```

**Response:**
```json
{
  "session_id": "...",
  "signs": ["hello", "want", "water"],
  "natural_translation": "Bonjour, je voudrais de l'eau.",
  "literal_translation": "Bonjour vouloir eau",
  "intent": "request_help",
  "confidence": 0.87,
  "provider": "gemini",
  "fallback": false,
  "reasoning_summary": "...",
  "suggested_missing_signs": ["please"]
}
```

### `POST /api/v1/translate/simulate`

Test the LLM translation pipeline without a camera session.

**Request body:**
```json
{ "signs": ["hello", "want", "food"], "lang": "fr" }
```

---

## SignSequenceBuilder — Design Decisions

- **Smoothing window (5 frames)**: prevents single-frame noise from being confirmed.
- **stable_frames_required (3)**: a sign must dominate 3 of the last 5 frames to be confirmed. Aggressive enough for live use, conservative enough to prevent false positives.
- **duplicate_cooldown_ms (1500)**: the same sign can appear again after 1.5s. Shorter than a natural signing pause, longer than a camera wobble.
- **sequence_timeout_ms (5000)**: 5s of silence triggers `should_auto_finalize()`. The client polls `/results` and triggers `/finalize` automatically.
- **max_sequence_length (20)**: prevents unbounded memory growth in long sessions.

---

## LLM Provider — Fallback Strategy

1. `LLM_TRANSLATION_ENABLED=false` → always `LocalFallback`
2. `LLM_PROVIDER=local` → `LocalFallback`
3. `LLM_PROVIDER=gemini` + no `GEMINI_API_KEY` → `LocalFallback`
4. `LLM_PROVIDER=gemini` + API key set → `GeminiTranslationProvider`
5. Gemini timeout / exception → `LocalFallback` with `fallback=True` in response

---

## Knowledge Base Quality (Post-v2)

| Metric | Value |
|--------|-------|
| Total labels | 64 |
| Labels with description | 64 (100%) |
| Labels with intent | 64 (100%) |
| Labels with French translation | 64 (100%) |
| Labels with Swahili translation | 64 (100%) |

---

## Breaking Changes

- `backend/schemas.py` in the worktree is the full schema (previously a 27-line agent-generated stub). No schema regressions.
- `RecognizeResponse` gains two Optional fields: `confirmed_sequence` and `pending_sign`. Existing clients ignore unknown fields.
- `GET /realtime/sessions/{sid}/results` returns additional keys (`confirmed_sequence`, `should_finalize`, `last_natural_translation`). Backward-compatible addition.
