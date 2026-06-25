import { useState, useEffect, useRef } from 'react';
import Icon from "@/components/ui/Icon";

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function authHeaders() {
    const token = localStorage.getItem('mira_admin_token') || '';
    return { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' };
}

const LANGS = [
    { code: 'fr', name: 'Français' },
    { code: 'en', name: 'English' },
    { code: 'sw', name: 'Kiswahili' },
];

export default function Playground() {
    const [activeTab, setActiveTab] = useState('realtime');
    const [models, setModels] = useState([]);
    const [modelsLoading, setModelsLoading] = useState(true);
    const [modelsError, setModelsError] = useState(null);
    const [selectedModel, setSelectedModel] = useState('');
    const [targetLang, setTargetLang] = useState('fr');
    const [codeModelId, setCodeModelId] = useState('model_asl_v1');
    const [codeLang, setCodeLang] = useState('fr');
    const [activeCodeTab, setActiveCodeTab] = useState('realtime');

    // Realtime state
    const [stream, setStream] = useState(null);
    const [sessionId, setSessionId] = useState(null);
    const [isRunning, setIsRunning] = useState(false);
    const [isPaused, setIsPaused] = useState(false);
    const [result, setResult] = useState(null);
    const [history, setHistory] = useState([]);
    const [creditsUsed, setCreditsUsed] = useState(0);
    const [rtStatus, setRtStatus] = useState({ msg: '', type: 'info' });
    const [timer, setTimer] = useState(0);

    // Mode state
    const [currentMode, setCurrentMode] = useState('alphabet');
    const [alphaLetters, setAlphaLetters] = useState([]);
    const [alphaWords, setAlphaWords] = useState([]);
    const [convSigns, setConvSigns] = useState([]);
    const [geminiSentence, setGeminiSentence] = useState('');
    const [geminiLoading, setGeminiLoading] = useState(false);
    const alphaLettersRef = useRef([]);
    const alphaWordsRef = useRef([]);
    const convSignsRef = useRef([]);
    const alphaPauseTimerRef = useRef(null);
    const lastAlphaLabelRef = useRef('');
    const lastConvLabelRef = useRef('');

    const videoRef = useRef(null);
    const canvasRef = useRef(null);
    const captureIntervalRef = useRef(null);
    const timerIntervalRef = useRef(null);
    const predHistoryRef = useRef([]);
    const sessionIdRef = useRef(null);

    // Upload state
    const [uploadFile, setUploadFile] = useState(null);
    const [uploadPreview, setUploadPreview] = useState(null);
    const [uploadResult, setUploadResult] = useState(null);
    const [uploadLoading, setUploadLoading] = useState(false);
    const [uploadError, setUploadError] = useState(null);

    // Simulation tab state
    const [simInput, setSimInput] = useState('');
    const [simLang, setSimLang] = useState('fr');
    const [simLoading, setSimLoading] = useState(false);
    const [simResult, setSimResult] = useState(null);
    const [simError, setSimError] = useState(null);

    useEffect(() => {
        loadModels();
        return () => stopSession(true);
    }, []);

    async function loadModels() {
        setModelsLoading(true);
        setModelsError(null);
        try {
            const r = await fetch(API + '/api/v1/admin/models/?status=published', { headers: authHeaders() });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            const data = await r.json();
            const items = data.items || data || [];
            setModels(items);
        } catch (e) {
            setModelsError('Impossible de charger les modèles : ' + e.message);
        } finally {
            setModelsLoading(false);
        }
    }

    // Camera
    async function activateCamera() {
        try {
            const s = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
            setStream(s);
            if (videoRef.current) videoRef.current.srcObject = s;
            setRtStatus({ msg: 'Caméra active. Cliquez sur Démarrer.', type: 'success' });
        } catch (err) {
            let msg = 'Erreur caméra.';
            if (err.name === 'NotAllowedError') msg = 'Permission refusée. Autorisez la caméra dans le navigateur.';
            else if (err.name === 'NotFoundError') msg = 'Aucune caméra détectée.';
            else if (err.name === 'NotReadableError') msg = 'Caméra utilisée par une autre application.';
            setRtStatus({ msg, type: 'error' });
        }
    }

    function deactivateCamera() {
        if (stream) { stream.getTracks().forEach(t => t.stop()); setStream(null); }
        if (videoRef.current) videoRef.current.srcObject = null;
        setRtStatus({ msg: '', type: 'info' });
    }

    function switchMode(mode) {
        setCurrentMode(mode);
        setAlphaLetters([]); alphaLettersRef.current = [];
        setAlphaWords([]); alphaWordsRef.current = [];
        setConvSigns([]); convSignsRef.current = [];
        setGeminiSentence('');
        lastAlphaLabelRef.current = '';
        lastConvLabelRef.current = '';
        if (alphaPauseTimerRef.current) { clearTimeout(alphaPauseTimerRef.current); alphaPauseTimerRef.current = null; }
    }

    function alphaAddLetter(label) {
        if (label === lastAlphaLabelRef.current) return;
        lastAlphaLabelRef.current = label;
        alphaLettersRef.current = [...alphaLettersRef.current, label];
        setAlphaLetters([...alphaLettersRef.current]);
        if (alphaPauseTimerRef.current) clearTimeout(alphaPauseTimerRef.current);
        alphaPauseTimerRef.current = setTimeout(() => alphaCommitWord(), 2000);
    }

    function alphaCommitWord() {
        if (alphaPauseTimerRef.current) { clearTimeout(alphaPauseTimerRef.current); alphaPauseTimerRef.current = null; }
        if (alphaLettersRef.current.length === 0) return;
        const word = alphaLettersRef.current.join('');
        alphaWordsRef.current = [...alphaWordsRef.current, word];
        setAlphaWords([...alphaWordsRef.current]);
        alphaLettersRef.current = [];
        setAlphaLetters([]);
        lastAlphaLabelRef.current = '';
        buildGeminiSentence([...alphaWordsRef.current], 'alphabet');
    }

    function convAddSign(label) {
        if (label === lastConvLabelRef.current) return;
        lastConvLabelRef.current = label;
        const updated = [...convSignsRef.current, label];
        convSignsRef.current = updated;
        setConvSigns([...updated]);
        if (updated.length >= 10) {
            buildGeminiSentence([...updated], 'conversation');
            convSignsRef.current = [];
            setConvSigns([]);
            lastConvLabelRef.current = '';
        }
    }

    async function buildGeminiSentence(signs, mode) {
        if (signs.length === 0) return;
        setGeminiLoading(true);
        try {
            const r = await fetch(API + '/api/v1/translate/build-sentence', {
                method: 'POST',
                headers: authHeaders(),
                body: JSON.stringify({ signs, mode, lang: targetLang }),
            });
            if (r.ok) {
                const data = await r.json();
                setGeminiSentence(data.sentence || '');
            }
        } catch (e) {}
        finally { setGeminiLoading(false); }
    }

    async function startSession() {
        const recogMode = currentMode === 'alphabet' ? 'hands' : 'holistic';
        const params = new URLSearchParams({ mode: recogMode, lang: targetLang, target_language: targetLang });
        if (selectedModel) params.set('model_id', selectedModel);
        try {
            const r = await fetch(API + '/api/v1/realtime/sessions?' + params, {
                method: 'POST', headers: authHeaders(),
            });
            if (!r.ok) { const e = await r.json().catch(() => ({})); setRtStatus({ msg: 'Erreur session: ' + (e.detail || r.status), type: 'error' }); return; }
            const sess = await r.json();
            sessionIdRef.current = sess.session_id;
            setSessionId(sess.session_id);
            setIsRunning(true); setIsPaused(false); setCreditsUsed(0); setHistory([]); setTimer(0); predHistoryRef.current = [];
            setRtStatus({ msg: 'Session démarrée. Faites des signes devant la caméra.', type: 'success' });
            startCapture(); startTimer();
        } catch (ex) { setRtStatus({ msg: 'Erreur réseau: ' + ex.message, type: 'error' }); }
    }

    async function stopSession(silent = false) {
        if (captureIntervalRef.current) { clearInterval(captureIntervalRef.current); captureIntervalRef.current = null; }
        if (timerIntervalRef.current) { clearInterval(timerIntervalRef.current); timerIntervalRef.current = null; }
        if (sessionIdRef.current) {
            try { await fetch(API + '/api/v1/realtime/sessions/' + sessionIdRef.current, { method: 'DELETE', headers: authHeaders() }); } catch (e) {}
            sessionIdRef.current = null; setSessionId(null);
        }
        setIsRunning(false); setIsPaused(false);
        if (!silent) setRtStatus({ msg: 'Session arrêtée.', type: 'info' });
    }

    function startTimer() {
        timerIntervalRef.current = setInterval(() => setTimer(t => t + 1), 1000);
    }

    function startCapture() {
        captureIntervalRef.current = setInterval(() => {
            if (!sessionIdRef.current || !videoRef.current || !canvasRef.current) return;
            const cv = canvasRef.current; const ctx = cv.getContext('2d');
            cv.width = 320; cv.height = 240;
            ctx.drawImage(videoRef.current, 0, 0, 320, 240);
            cv.toBlob(async blob => {
                if (!blob) return;
                const reader = new FileReader();
                reader.onload = async e => {
                    const b64 = e.target.result.split(',')[1];
                    await sendFrame(b64);
                };
                reader.readAsDataURL(blob);
            }, 'image/jpeg', 0.7);
        }, 333);
    }

    async function sendFrame(b64) {
        if (!sessionIdRef.current) return;
        try {
            const r = await fetch(API + '/api/v1/realtime/sessions/' + sessionIdRef.current + '/frames?annotate=false&top_k=3&target_language=' + targetLang, {
                method: 'POST', headers: authHeaders(),
                body: JSON.stringify({ image: b64, lang: targetLang, mode: currentMode === 'alphabet' ? 'hands' : 'holistic', session_id: sessionIdRef.current }),
            });
            if (r.status === 429) { await stopSession(); setRtStatus({ msg: 'Quota épuisé.', type: 'error' }); return; }
            if (!r.ok) return;
            const res = await r.json();
            handleResult(res);
        } catch (e) {}
    }

    function smooth(label) {
        predHistoryRef.current.push(label);
        if (predHistoryRef.current.length > 5) predHistoryRef.current.shift();
        const counts = {};
        predHistoryRef.current.forEach(l => { if (l) counts[l] = (counts[l] || 0) + 1; });
        const best = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
        return (best && best[1] >= 3) ? best[0] : null;
    }

    function handleResult(r) {
        setResult(r);
        const label = r.translated_text || r.label || r.preview_label;
        if (label && smooth(label) === label) {
            setCreditsUsed(c => c + 1);
            setHistory(h => { const nh = [...h, label]; return nh.slice(-20); });
            if (currentMode === 'alphabet') alphaAddLetter(label);
            else convAddSign(label);
        }
    }

    // Upload
    function handleUploadFile(file) {
        setUploadFile(file); setUploadResult(null); setUploadError(null);
        const reader = new FileReader();
        reader.onload = e => setUploadPreview(e.target.result);
        reader.readAsDataURL(file);
    }

    async function runUpload() {
        if (!uploadFile) return;
        setUploadLoading(true); setUploadError(null);
        try {
            const fd = new FormData();
            fd.append('file', uploadFile);
            fd.append('lang', targetLang);
            fd.append('mode', 'holistic');
            const token = localStorage.getItem('mira_admin_token') || '';
            const url = API + '/api/v1/recognize/upload?top_k=5&annotate=true&target_language=' + targetLang + (selectedModel ? '&model_id=' + selectedModel : '');
            const r = await fetch(url, { method: 'POST', headers: { 'Authorization': 'Bearer ' + token }, body: fd });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Erreur ' + r.status);
            setUploadResult(data);
        } catch (e) { setUploadError(e.message); }
        finally { setUploadLoading(false); }
    }

    // Simulation
    async function runSimulate() {
        const signs = simInput.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
        if (signs.length === 0) { setSimError('Entrez au moins un signe.'); return; }
        setSimLoading(true); setSimError(null); setSimResult(null);
        try {
            const r = await fetch(API + '/api/v1/translate/simulate', {
                method: 'POST',
                headers: authHeaders(),
                body: JSON.stringify({ signs, lang: simLang }),
            });
            const data = await r.json();
            if (!r.ok) throw new Error(data.detail || 'Erreur ' + r.status);
            setSimResult(data);
        } catch (e) { setSimError(e.message); }
        finally { setSimLoading(false); }
    }

    // Code examples
    const apiKey = 'mira_admin_sk_YOUR_KEY';
    const modelId = codeModelId || 'model_asl_v1';
    const lang = codeLang;

    const codeExamples = {
        realtime: `# 1. Créer session\ncurl -X POST "${API}/api/v1/realtime/sessions?mode=holistic&lang=${lang}&target_language=${lang}&model_id=${modelId}" \\\n  -H "Authorization: Bearer ${apiKey}"\n\n# 2. Envoyer frame\ncurl -X POST "${API}/api/v1/realtime/sessions/{session_id}/frames?target_language=${lang}" \\\n  -H "Authorization: Bearer ${apiKey}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"image":"<base64>","lang":"${lang}","mode":"holistic"}'\n\n# 3. Résultats\ncurl "${API}/api/v1/realtime/sessions/{session_id}/results" -H "Authorization: Bearer ${apiKey}"\n\n# 4. Supprimer\ncurl -X DELETE "${API}/api/v1/realtime/sessions/{session_id}" -H "Authorization: Bearer ${apiKey}"`,
        upload: `curl -X POST "${API}/api/v1/recognize/upload?target_language=${lang}&top_k=3" \\\n  -H "Authorization: Bearer ${apiKey}" \\\n  -F "file=@sample.jpg" \\\n  -F "lang=${lang}" \\\n  -F "mode=holistic"`,
        python: `import requests, base64\nfrom pathlib import Path\n\nAPI = "${API}"\nHEADERS = {"Authorization": "Bearer ${apiKey}"}\n\n# Session realtime\nsess = requests.post(f"{API}/api/v1/realtime/sessions", params={"lang":"${lang}","target_language":"${lang}","model_id":"${modelId}"}, headers=HEADERS).json()\n\n# Envoyer frame\nb64 = base64.b64encode(Path("frame.jpg").read_bytes()).decode()\nres = requests.post(f"{API}/api/v1/realtime/sessions/{sess['session_id']}/frames", params={"target_language":"${lang}"}, json={"image":b64,"lang":"${lang}","mode":"holistic"}, headers=HEADERS).json()\nprint(res.get("translated_text"), res.get("confidence"))`,
        js: `const API = "${API}";\nconst headers = { "Authorization": "Bearer ${apiKey}" };\n\nconst stream = await navigator.mediaDevices.getUserMedia({ video: true });\nconst sess = await fetch(\`\${API}/api/v1/realtime/sessions?lang=${lang}&target_language=${lang}&model_id=${modelId}\`, { method:"POST", headers }).then(r=>r.json());\n\nconst canvas = document.createElement("canvas");\nconst ctx = canvas.getContext("2d");\nconst video = document.querySelector("video");\n\nsetInterval(async () => {\n  canvas.width=320; canvas.height=240;\n  ctx.drawImage(video, 0, 0, 320, 240);\n  const blob = await new Promise(r => canvas.toBlob(r, "image/jpeg", 0.7));\n  const b64 = btoa(String.fromCharCode(...new Uint8Array(await blob.arrayBuffer())));\n  const res = await fetch(\`\${API}/api/v1/realtime/sessions/\${sess.session_id}/frames?target_language=${lang}\`, {\n    method:"POST", headers:{...headers,"Content-Type":"application/json"},\n    body:JSON.stringify({image:b64,lang:"${lang}",mode:"holistic"})\n  }).then(r=>r.json());\n  console.log(res.translated_text, res.confidence);\n}, 333);`,
    };

    const fmtTimer = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    const confPct = result ? Math.round((result.confidence || 0) * 100) : 0;
    const confColor = confPct >= 80 ? 'bg-green-500' : confPct >= 50 ? 'bg-yellow-500' : 'bg-red-500';

    return (
        <div className="p-6">
            <div className="flex justify-between items-center mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 dark:text-white">API Playground</h1>
                    <p className="text-sm text-slate-500 mt-1">Testez Mira en temps réel ou par upload</p>
                </div>
                <button onClick={loadModels} className="text-sm text-indigo-500 hover:underline flex items-center gap-1">
                    ↻ Actualiser
                </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-slate-200 dark:border-slate-700 mb-6">
                {[
                    { id: 'realtime', label: '📹 Temps réel' },
                    { id: 'upload', label: '📁 Upload test' },
                    { id: 'simulate', label: '✨ Simulation séquence' },
                    { id: 'code', label: '</> Code examples' },
                ].map(tab => (
                    <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                        className={`px-5 py-3 text-sm font-medium border-b-2 transition-colors ${activeTab === tab.id ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-slate-500 hover:text-slate-700'}`}>
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* === TAB REALTIME === */}
            {activeTab === 'realtime' && (
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
                    {/* Config */}
                    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                        <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
                            <h3 className="text-xs font-semibold text-indigo-500 tracking-widest uppercase">Configuration</h3>
                        </div>
                        <div className="p-4 space-y-3">
                            <div>
                                <label className="block text-xs text-slate-500 mb-1 uppercase tracking-wide">Modèle</label>
                                {modelsLoading ? <div className="text-xs text-slate-400">Chargement...</div>
                                    : modelsError ? <div className="text-xs text-red-400">{modelsError}</div>
                                        : <select value={selectedModel} onChange={e => setSelectedModel(e.target.value)}
                                            className="w-full text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2">
                                            <option value="">Modèle par défaut</option>
                                            {models.length === 0 && <option disabled>Aucun modèle publié</option>}
                                            {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                                        </select>}
                                {!modelsLoading && !modelsError && models.length === 0 && (
                                    <p className="text-xs text-amber-500 mt-1">Aucun modèle publié. Publiez un modèle depuis le Registre.</p>
                                )}
                            </div>
                            <div>
                                <label className="block text-xs text-slate-500 mb-1 uppercase tracking-wide">Langue de sortie</label>
                                <select value={targetLang} onChange={e => setTargetLang(e.target.value)}
                                    className="w-full text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2">
                                    {LANGS.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
                                </select>
                            </div>
                            <div>
                                <label className="block text-xs text-slate-500 mb-1 uppercase tracking-wide">Mode</label>
                                <div className="flex gap-1">
                                    {[
                                        { id: 'alphabet', label: 'Alphabet', icon: 'heroicons-outline:pencil-alt', desc: 'Signes lettre par lettre' },
                                        { id: 'conversation', label: 'Conversation', icon: 'heroicons-outline:chat-alt-2', desc: 'Signes mots entiers' }
                                    ].map(m => (
                                        <button key={m.id} onClick={() => !isRunning && switchMode(m.id)} disabled={isRunning}
                                            title={m.desc}
                                            className={`flex-1 py-1.5 text-xs font-semibold rounded-lg border transition-colors disabled:opacity-50 flex items-center justify-center gap-1 ${currentMode === m.id ? 'bg-indigo-600 text-white border-indigo-600' : 'border-slate-300 text-slate-500 hover:border-indigo-400'}`}>
                                            <Icon icon={m.icon} className="text-sm" />
                                            {m.label}
                                        </button>
                                    ))}
                                </div>
                                <p className="text-xs text-slate-400 mt-1">{currentMode === 'alphabet' ? 'Épeler lettre par lettre (pause = mot)' : 'Signer des mots ASL entiers (max 10)'}</p>
                            </div>
                            <div className="flex gap-2 pt-2">
                                <button onClick={stream ? deactivateCamera : activateCamera}
                                    className={`flex-1 py-2 text-xs font-semibold rounded-lg border transition-colors ${stream ? 'border-red-300 text-red-500 hover:bg-red-50' : 'border-indigo-300 text-indigo-500 hover:bg-indigo-50'}`}>
                                    {stream ? '📷 Désactiver' : '📷 Activer caméra'}
                                </button>
                            </div>
                            {!isRunning ? (
                                <button onClick={startSession} disabled={!stream}
                                    className="w-full py-2 text-xs font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed">
                                    ▶ Démarrer
                                </button>
                            ) : (
                                <div className="flex gap-2">
                                    <button onClick={() => setIsPaused(p => !p)} className="flex-1 py-2 text-xs font-semibold border border-slate-300 rounded-lg hover:bg-slate-50">
                                        {isPaused ? '▶ Reprendre' : '⏸ Pause'}
                                    </button>
                                    <button onClick={() => stopSession()} className="flex-1 py-2 text-xs font-semibold bg-red-500 text-white rounded-lg hover:bg-red-600">
                                        ⏹ Arrêter
                                    </button>
                                </div>
                            )}
                            {rtStatus.msg && (
                                <div className={`text-xs p-2 rounded-lg ${rtStatus.type === 'error' ? 'bg-red-50 text-red-500' : rtStatus.type === 'success' ? 'bg-green-50 text-green-600' : 'bg-blue-50 text-blue-500'}`}>
                                    {rtStatus.msg}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Camera */}
                    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                        <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 flex justify-between items-center">
                            <h3 className="text-xs font-semibold text-indigo-500 tracking-widest uppercase">Caméra Live</h3>
                            {isRunning && <span className="flex items-center gap-1 text-xs text-green-500 font-semibold"><span className="w-2 h-2 bg-green-400 rounded-full animate-pulse inline-block"></span>ACTIF {fmtTimer(timer)}</span>}
                        </div>
                        <div className="p-4">
                            <div className="relative bg-slate-900 rounded-lg overflow-hidden" style={{ minHeight: 200 }}>
                                {stream ? (
                                    <video ref={videoRef} autoPlay playsInline className="w-full rounded-lg" />
                                ) : (
                                    <div className="flex flex-col items-center justify-center h-48 text-slate-500">
                                        <span className="text-4xl mb-2">📷</span>
                                        <span className="text-xs">Caméra inactive</span>
                                        <span className="text-xs text-slate-400 mt-1">Cliquez sur "Activer caméra"</span>
                                    </div>
                                )}
                            </div>
                            <canvas ref={canvasRef} className="hidden" />
                            {isRunning && <div className="text-xs text-slate-400 text-center mt-2">Analyse ~3 req/s</div>}
                        </div>
                    </div>

                    {/* Results */}
                    <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                        <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
                            <h3 className="text-xs font-semibold text-indigo-500 tracking-widest uppercase">Traduction en direct</h3>
                        </div>
                        <div className="p-4">
                            <div className="text-center py-4">
                                <div className="text-5xl font-bold text-slate-900 dark:text-white mb-1" style={{ minHeight: 60 }}>
                                    {result?.translated_text || result?.label || '--'}
                                </div>
                                {result?.raw_label && result.raw_label !== (result?.translated_text || result?.label) && (
                                    <div className="text-xs text-slate-400 font-mono">label: {result.raw_label}</div>
                                )}
                                {result?.target_language && (
                                    <div className="text-xs text-indigo-400 mt-1">{LANGS.find(l => l.code === result.target_language)?.name || result.target_language}</div>
                                )}
                            </div>
                            <div className="mb-4">
                                <div className="flex justify-between text-xs text-slate-400 mb-1"><span>CONFIANCE</span><span>{confPct}%</span></div>
                                <div className="bg-slate-100 dark:bg-slate-700 rounded-full h-2"><div className={`h-2 rounded-full transition-all ${confColor}`} style={{ width: confPct + '%' }}></div></div>
                            </div>
                            {result?.top_predictions?.length > 0 && (
                                <div className="space-y-1 mb-4">
                                    {result.top_predictions.slice(0, 3).map((p, i) => (
                                        <div key={i} className="flex items-center gap-2 text-xs">
                                            <span className="text-slate-600 dark:text-slate-300 w-24 truncate font-mono">{p.translated_text || p.label}</span>
                                            <div className="flex-1 bg-slate-100 dark:bg-slate-700 rounded h-1"><div className="h-1 bg-indigo-400 rounded" style={{ width: Math.round((p.confidence || 0) * 100) + '%' }}></div></div>
                                            <span className="text-slate-400 w-8 text-right">{Math.round((p.confidence || 0) * 100)}%</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                            {!result?.hands_detected && isRunning && (
                                <div className="text-xs text-amber-500 bg-amber-50 rounded-lg p-2 mb-3">Aucune main détectée — placez vos mains devant la caméra</div>
                            )}
                            <div className="border-t border-slate-100 dark:border-slate-700 pt-3">
                                <div className="text-xs text-slate-400 mb-2">HISTORIQUE ({creditsUsed} crédits)</div>
                                <div className="flex flex-wrap gap-1">
                                    {history.length === 0 ? <span className="text-xs text-slate-400">Aucun signe détecté</span>
                                        : history.map((s, i) => <span key={i} className="px-2 py-0.5 bg-indigo-50 dark:bg-indigo-900 text-indigo-600 dark:text-indigo-300 rounded-full text-xs">{s}</span>)}
                                </div>
                            </div>

                            {/* Alphabet accumulator */}
                            {currentMode === 'alphabet' && (
                                <div className="border-t border-slate-100 dark:border-slate-700 pt-3 space-y-2">
                                    <div className="text-xs text-slate-400 uppercase tracking-wide">Mode Alphabet (Daktylo)</div>
                                    <div className="flex items-center gap-2 flex-wrap min-h-8">
                                        <span className="text-xs text-slate-400">Lettres:</span>
                                        {alphaLetters.length === 0
                                            ? <span className="text-xs text-slate-300">—</span>
                                            : alphaLetters.map((l, i) => <span key={i} className="px-1.5 py-0.5 bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-300 rounded text-xs font-mono font-bold">{l}</span>)}
                                        {alphaLetters.length > 0 && (
                                            <button onClick={alphaCommitWord} className="text-xs text-indigo-500 underline ml-1">Valider mot</button>
                                        )}
                                    </div>
                                    <div className="flex items-start gap-2 flex-wrap min-h-8">
                                        <span className="text-xs text-slate-400 shrink-0">Mots:</span>
                                        {alphaWords.length === 0
                                            ? <span className="text-xs text-slate-300">—</span>
                                            : alphaWords.map((w, i) => <span key={i} className="px-2 py-0.5 bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300 rounded text-xs font-semibold">{w}</span>)}
                                        {alphaWords.length > 0 && (
                                            <button onClick={() => { buildGeminiSentence([...alphaWords], 'alphabet'); }} className="text-xs text-indigo-500 underline ml-1">Construire phrase</button>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Conversation accumulator */}
                            {currentMode === 'conversation' && (
                                <div className="border-t border-slate-100 dark:border-slate-700 pt-3 space-y-2">
                                    <div className="flex items-center justify-between">
                                        <div className="text-xs text-slate-400 uppercase tracking-wide">Mode Conversation</div>
                                        <span className="text-xs text-slate-400">{convSigns.length}/10</span>
                                    </div>
                                    <div className="flex flex-wrap gap-1 min-h-8">
                                        {convSigns.length === 0
                                            ? <span className="text-xs text-slate-300">Signez des mots ASL...</span>
                                            : convSigns.map((s, i) => <span key={i} className="px-2 py-0.5 bg-purple-50 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 rounded text-xs font-semibold">{s}</span>)}
                                    </div>
                                    {convSigns.length > 0 && (
                                        <button onClick={() => { buildGeminiSentence([...convSigns], 'conversation'); convSignsRef.current = []; setConvSigns([]); lastConvLabelRef.current = ''; }}
                                            className="text-xs bg-purple-500 text-white rounded-lg px-3 py-1 hover:bg-purple-600">
                                            Construire phrase Gemini
                                        </button>
                                    )}
                                </div>
                            )}

                            {/* Gemini sentence box */}
                            <div className="border-t border-slate-100 dark:border-slate-700 pt-3">
                                <div className="flex items-center gap-2 mb-2">
                                    <Icon icon="heroicons-outline:sparkles" className="text-indigo-500 text-sm" />
                                    <span className="text-xs font-semibold text-indigo-500 uppercase tracking-wide">Phrase Gemini</span>
                                    {geminiLoading && <span className="text-xs text-slate-400 animate-pulse">Gemini réfléchit...</span>}
                                </div>
                                <div className="min-h-12 bg-indigo-50 dark:bg-indigo-900/20 rounded-lg p-3 text-sm text-slate-800 dark:text-slate-100 font-medium">
                                    {geminiSentence || <span className="text-slate-400 text-xs">La phrase construite par Gemini apparaîtra ici</span>}
                                </div>
                                {geminiSentence && (
                                    <button onClick={() => setGeminiSentence('')} className="text-xs text-slate-400 mt-1 hover:text-slate-600">Effacer</button>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* === TAB UPLOAD === */}
            {activeTab === 'upload' && (
                <div className="max-w-lg space-y-4">
                    <p className="text-sm text-slate-500">Testez un signe isolé par upload image.</p>
                    <div>
                        <label className="block text-xs text-slate-500 mb-1 uppercase tracking-wide">Langue de sortie</label>
                        <select value={targetLang} onChange={e => setTargetLang(e.target.value)}
                            className="text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2">
                            {LANGS.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
                        </select>
                    </div>
                    <label className="block border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-xl p-8 text-center cursor-pointer hover:border-indigo-400 transition-colors">
                        <input type="file" accept="image/*" className="hidden" onChange={e => e.target.files[0] && handleUploadFile(e.target.files[0])} />
                        <div className="text-3xl mb-2">📁</div>
                        <div className="text-sm text-slate-500">{uploadFile ? uploadFile.name : 'Cliquez ou déposez une image'}</div>
                    </label>
                    {uploadPreview && <img src={uploadPreview} alt="preview" className="max-h-40 rounded-lg mx-auto" />}
                    <button onClick={runUpload} disabled={!uploadFile || uploadLoading}
                        className="w-full py-2 text-sm font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40">
                        {uploadLoading ? 'Analyse...' : 'Analyser'}
                    </button>
                    {uploadError && <div className="text-sm text-red-500 bg-red-50 p-3 rounded-lg">{uploadError}</div>}
                    {uploadResult && (
                        <div className="bg-slate-50 dark:bg-slate-900 rounded-xl p-4 space-y-2">
                            <div className="text-3xl font-bold">{uploadResult.translated_text || uploadResult.label || '—'}</div>
                            {uploadResult.raw_label && <div className="text-xs text-slate-400 font-mono">label: {uploadResult.raw_label}</div>}
                            <div className="text-sm text-slate-500">Confiance: {Math.round((uploadResult.confidence || 0) * 100)}%</div>
                        </div>
                    )}
                </div>
            )}

            {/* === TAB SIMULATION === */}
            {activeTab === 'simulate' && (
                <div className="max-w-2xl space-y-4">
                    <p className="text-sm text-slate-500">Testez le pipeline de traduction LLM avec une séquence de signes saisie manuellement — sans caméra.</p>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <label className="block text-xs text-slate-500 mb-1 uppercase tracking-wide">Signes ASL (séparés par virgule ou espace)</label>
                            <input
                                value={simInput}
                                onChange={e => setSimInput(e.target.value)}
                                placeholder="ex: hello, want, water, please"
                                className="w-full text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2"
                                onKeyDown={e => e.key === 'Enter' && runSimulate()}
                            />
                            <p className="text-xs text-slate-400 mt-1">Les signes connus en KB sont enrichis de contexte pour le LLM.</p>
                        </div>
                        <div>
                            <label className="block text-xs text-slate-500 mb-1 uppercase tracking-wide">Langue de sortie</label>
                            <select value={simLang} onChange={e => setSimLang(e.target.value)}
                                className="w-full text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2">
                                {LANGS.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
                            </select>
                        </div>
                    </div>
                    <button onClick={runSimulate} disabled={simLoading || !simInput.trim()}
                        className="flex items-center gap-2 px-5 py-2 text-sm font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40">
                        <Icon icon="heroicons-outline:sparkles" className="text-sm" />
                        {simLoading ? 'IA en cours…' : 'Simuler la traduction'}
                    </button>
                    {simError && <div className="text-sm text-red-500 bg-red-50 dark:bg-red-900/20 p-3 rounded-lg">{simError}</div>}
                    {simResult && (
                        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                            <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 flex justify-between items-center">
                                <h3 className="text-xs font-semibold text-indigo-500 tracking-widest uppercase">Résultat IA</h3>
                                <span className={`text-xs px-2 py-0.5 rounded-full ${simResult.provider?.includes('gemini') || simResult.provider?.includes('gemma') ? 'bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-300' : 'bg-slate-100 text-slate-500'}`}>
                                    {simResult.provider || 'unknown'}
                                    {simResult.fallback ? ' (fallback)' : ''}
                                </span>
                            </div>
                            <div className="p-4 space-y-3">
                                <div>
                                    <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Traduction naturelle</div>
                                    <div className="text-xl font-semibold text-slate-900 dark:text-white">{simResult.natural_translation || '—'}</div>
                                </div>
                                {simResult.literal_translation && (
                                    <div>
                                        <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Littéral</div>
                                        <div className="text-sm text-slate-600 dark:text-slate-300 italic">{simResult.literal_translation}</div>
                                    </div>
                                )}
                                {simResult.intent && (
                                    <div className="flex items-center gap-2">
                                        <div className="text-xs text-slate-400 uppercase tracking-wide">Intent</div>
                                        <span className="text-xs px-2 py-0.5 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-300 rounded-full font-semibold">{simResult.intent.replace(/_/g,' ')}</span>
                                    </div>
                                )}
                                <div className="flex items-center gap-2">
                                    <div className="text-xs text-slate-400 uppercase tracking-wide">Confiance</div>
                                    <div className="flex-1 bg-slate-100 dark:bg-slate-700 rounded-full h-1.5 max-w-xs">
                                        <div className="h-1.5 rounded-full bg-indigo-500 transition-all" style={{ width: Math.round((simResult.confidence || 0) * 100) + '%' }}></div>
                                    </div>
                                    <span className="text-xs text-slate-500">{Math.round((simResult.confidence || 0) * 100)}%</span>
                                </div>
                                <div>
                                    <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Signes utilisés</div>
                                    <div className="flex flex-wrap gap-1">
                                        {(simResult.signs || simResult.raw_signs || []).map((s, i) => (
                                            <span key={i} className="px-2 py-0.5 bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded text-xs font-mono">{s}</span>
                                        ))}
                                    </div>
                                </div>
                                {simResult.reasoning_summary && (
                                    <div>
                                        <div className="text-xs text-slate-400 uppercase tracking-wide mb-1">Raisonnement IA</div>
                                        <div className="text-xs text-slate-500 italic">{simResult.reasoning_summary}</div>
                                    </div>
                                )}
                                {simResult.suggested_missing_signs?.length > 0 && (
                                    <div>
                                        <div className="text-xs text-amber-500 uppercase tracking-wide mb-1">Signes suggérés manquants</div>
                                        <div className="flex flex-wrap gap-1">
                                            {simResult.suggested_missing_signs.map((s, i) => (
                                                <span key={i} className="px-2 py-0.5 bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-300 rounded text-xs font-mono">{s}</span>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* === TAB CODE === */}
            {activeTab === 'code' && (
                <div className="space-y-4">
                    <div className="flex gap-3 flex-wrap">
                        <div>
                            <label className="block text-xs text-slate-500 mb-1">ID Modèle</label>
                            <input value={codeModelId} onChange={e => setCodeModelId(e.target.value)}
                                className="text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2 w-40"
                                placeholder="model_asl_v1" />
                        </div>
                        <div>
                            <label className="block text-xs text-slate-500 mb-1">Langue de sortie</label>
                            <select value={codeLang} onChange={e => setCodeLang(e.target.value)}
                                className="text-sm bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2">
                                {LANGS.map(l => <option key={l.code} value={l.code}>{l.name}</option>)}
                            </select>
                        </div>
                    </div>
                    <div className="flex gap-2 flex-wrap">
                        {['realtime', 'upload', 'python', 'js'].map(tab => (
                            <button key={tab} onClick={() => setActiveCodeTab(tab)}
                                className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${activeCodeTab === tab ? 'bg-indigo-600 text-white' : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300'}`}>
                                {tab === 'realtime' ? 'Session temps réel' : tab === 'upload' ? 'Upload ponctuel' : tab === 'python' ? 'Python' : 'JavaScript'}
                            </button>
                        ))}
                    </div>
                    <div className="relative bg-slate-900 rounded-xl p-4 overflow-x-auto">
                        <button onClick={() => navigator.clipboard.writeText(codeExamples[activeCodeTab]).catch(() => {})}
                            className="absolute top-3 right-3 text-xs bg-slate-700 hover:bg-slate-600 text-slate-300 px-2 py-1 rounded">
                            Copier
                        </button>
                        <pre className="text-xs text-emerald-400 whitespace-pre overflow-x-auto leading-relaxed">{codeExamples[activeCodeTab]}</pre>
                    </div>
                </div>
            )}

            {/* Privacy notice */}
            <div className="mt-6 text-xs text-slate-400 border-l-2 border-indigo-400 pl-3">
                Les frames capturées sont transmises au serveur Mira pour analyse uniquement. Aucune donnée n'est stockée sans consentement.
            </div>
        </div>
    );
}
