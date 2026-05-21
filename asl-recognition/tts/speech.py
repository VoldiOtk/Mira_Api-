import edge_tts
import asyncio
import base64

class TTSEngine:
    def __init__(self, voice="fr-FR-DeniseNeural", rate="+0%"):
        self.voice = voice
        self.rate = rate

    async def generate_audio_b64(self, text):
        """
        Génère un fichier audio MP3 de manière asynchrone via Edge TTS (Microsoft Azure Neural)
        et le convertit en Base64 pour contourner les API vocales basiques du navigateur.
        """
        if not text:
            return ""
        
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        
        audio_data = b""
        try:
            # On récupère les bytes de l'audio directement en mémoire, sans écrire de fichier
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data += chunk["data"]
            
            # Encodage en base64 pour un transfert propre via le JSON du WebSocket
            b64 = base64.b64encode(audio_data).decode('utf-8')
            return b64
        except Exception as e:
            print(f"[TTS] Erreur de génération Edge-TTS: {e}")
            return ""

    def speak(self, text):
        # Fonction désactivée.
        # L'ancienne méthode "speak" bloquante (pyttsx3) est conservée vide 
        # pour la compatibilité avec d'autres vieux morceaux du code.
        pass
