# Mira — Innovation Ideas (v2)

25 ideas for future product evolution across intelligence, UX, and platform axes.

---

## Intelligence & Translation

**1. Contextual Memory Window**  
Carry a rolling "conversation context" across multiple finalize calls in the same session. The LLM receives the last 3 translated sentences, enabling it to resolve pronouns ("she", "it") and maintain dialogue coherence.

**2. Speaker Disambiguation**  
When two signers appear in frame (dual video tracks or split screen), assign a speaker ID to each sequence so translations are labelled "Person A / Person B" in the output.

**3. Intent-Driven Tone Adaptation**  
Map recognized intents (greeting / request_help / question) to tone presets in the LLM prompt: formal for professional queries, warm for greetings, neutral for statements.

**4. KB Auto-Enrichment from Sign Videos**  
Run a background job on each newly uploaded WLASL video: extract motion descriptors, cluster by semantic proximity, and automatically suggest `description` and `related_signs` patches for labels.json.

**5. Cross-Language Sign Borrowing**  
Detect when an ASL sign's closest match is in Langue des Signes Française (LSF) or Kenyan Sign Language (KSL) and flag it in the translation output, supporting multilingual Deaf communities.

**6. Confidence-Weighted LLM Context**  
Sort signs by `confidence` before building the KB context string. Signs with confidence > 0.85 are marked "confirmed"; lower-confidence signs are marked "uncertain — may be wrong" so the LLM can hedge its reconstruction.

**7. Semantic Gap Detection**  
After translation, ask the LLM to list which grammatical slots (subject / verb / object) are empty in the reconstructed sentence. Surface these as `suggested_missing_signs` in the UI.

**8. Emotion Layer from Facial Landmarks**  
Extend MediaPipe extraction to include facial landmark features (brow furrow, mouth corners). Train a lightweight classifier to detect emotion (neutral / happy / urgent / questioning) and inject it into the LLM prompt.

**9. Model Ensemble for Sequence Voting**  
Run two models (holistic + hands) in parallel on the same session. Merge predictions using a Bayesian ensemble: when models agree, boost confidence; when they disagree, request more frames.

**10. Offline LLM via Ollama**  
Wire `OllamaTranslationProvider` into the `get_llm_provider()` factory (provider=`ollama`). The `translate_sequence_structured()` call targets a local Llama / Gemma instance — zero-latency, zero cost, full privacy.

---

## UX & Interface

**11. Signing Speed Meter**  
Calculate signs-per-minute from `timestamp_ms` differences in `get_rich_sequence()`. Display a speed indicator in the live-reconnaissance UI so users can pace themselves for better accuracy.

**12. Live Confidence Heatmap**  
Replace the single confidence bar with a rolling 10-frame heatmap grid (green/yellow/red per frame). Users see at a glance if the detector is struggling.

**13. Sign Suggestion Autocomplete**  
After each confirmed sign, display the top 3 `related_signs` from labels.json as tappable chips. Tapping one injects it as a confirmed sign — useful for users who know approximately what they want to say.

**14. Session Replay Timeline**  
Record the full `get_rich_sequence()` plus frame timestamps as a JSON "replay file". A replay tab in the admin Playground lets reviewers scrub through the session frame-by-frame.

**15. Multi-Sentence Paragraph Mode**  
Add a "paragraph mode" that queues multiple finalized sentences, then calls the LLM once with the full batch: "Rewrite these 3 sentences as a natural paragraph in French." Results in more cohesive multi-sentence output.

**16. Guided Training Drills**  
A "Practice" tab shows a target phrase in French. The user signs it; Mira checks each sign against the target sequence and provides per-sign feedback (✓ / ✗) before the LLM builds the sentence.

**17. Shareable Translation Cards**  
After a finalize, generate a shareable card (PNG export via html2canvas): the ASL sequence chips on top, the natural translation large in the center, a QR code to the Mira public page at the bottom.

---

## Platform & Integrations

**18. WebSocket Realtime Streaming**  
Replace the polling `/frames` REST loop with a WebSocket endpoint (`/ws/realtime/{session_id}`). Each frame is a binary message; the server pushes partial results and the final structured translation as JSON events.

**19. Webhook on Finalize**  
Allow API key holders to register a webhook URL. Each `/finalize` call posts the structured translation JSON to the webhook — enabling Slack bots, accessibility overlays, CRM integrations.

**20. iOS / Android SDK**  
Publish a minimal native SDK (Swift / Kotlin) that wraps: camera capture at 3fps, base64 encoding, session lifecycle, and the /finalize call. Reduces integration time from days to hours.

**21. Browser Extension for Video Calls**  
A Chrome/Firefox extension that captures the local webcam during Zoom / Meet sessions, feeds frames to Mira, and renders captions as a floating overlay — no app switching needed.

**22. Admin Analytics Dashboard**  
Track per-client: average signs/session, most common confirmed signs, LLM provider breakdown (gemini vs local), average reconstruction confidence. Surface insights in a new admin Analytics page.

**23. A/B Testing for LLM Prompts**  
Implement prompt versioning in `gemini_client.py`. Each `translate_sequence_structured()` call logs which prompt version was used. The admin dashboard shows translation quality scores per version.

**24. Rate-Limited Public Demo Endpoint**  
A `/public/demo/translate` endpoint (no auth, 10 calls/day per IP, rate-limited by Redis) that accepts a sign list and returns a translation. Lowers the friction for journalists and researchers to evaluate Mira.

**25. Federated Model Registry**  
Allow partners (e.g., Deaf schools, NGOs) to publish their own ASL models to Mira's model registry via a REST API. Clients can switch between the default Mira model and community-contributed models.
