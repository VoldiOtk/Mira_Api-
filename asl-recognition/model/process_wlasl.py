"""
WLASL Video → MediaPipe Keypoints Extractor
============================================
Lit les vidéos WLASL, extrait les keypoints via MediaPipe Holistic,
et sauvegarde les séquences en fichiers .npy pour l'entraînement.
"""
import os
import sys
import json
import cv2
import numpy as np

# Ajouter le dossier racine du projet au path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.mediapipe_extractor import MediaPipeExtractor

# ──────────── CONFIGURATION ────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WLASL_DIR = os.path.join(BASE_DIR, 'data', 'knowledge', 'asl_videos')
VIDEOS_DIR = os.path.join(WLASL_DIR, 'videos')
CLASS_LIST_FILE = os.path.join(WLASL_DIR, 'wlasl_class_list.txt')
NSLT_FILE = os.path.join(WLASL_DIR, 'nslt_100.json')
LABELS_FILE = os.path.join(BASE_DIR, 'data', 'knowledge', 'labels.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data', 'knowledge', 'asl_data')

SEQUENCE_LENGTH = 30  # Nombre de frames fixe attendu par le LSTM
MAX_VIDEOS_PER_CLASS = 8  # Limiter pour la vitesse du prototype


def load_class_list():
    """Charge le mapping class_id → mot depuis wlasl_class_list.txt"""
    mapping = {}
    with open(CLASS_LIST_FILE, 'r') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) == 2:
                mapping[int(parts[0])] = parts[1].lower()
    return mapping


def load_target_words():
    """Charge les mots cibles depuis labels.json"""
    with open(LABELS_FILE, 'r', encoding='utf-8') as f:
        labels = json.load(f)
    return list(labels.keys())


def load_nslt_mapping():
    """Charge nslt_100.json : video_id → {subset, action: [class_id, start, end]}"""
    with open(NSLT_FILE, 'r') as f:
        return json.load(f)


def resample_sequence(keypoints_list, target_length):
    """
    Ré-échantillonne une liste de keypoints à exactement target_length frames.
    - Si trop long → on sous-échantillonne uniformément
    - Si trop court → on sur-échantillonne uniformément
    """
    n = len(keypoints_list)
    if n == 0:
        return [np.zeros(1662)] * target_length
    if n == target_length:
        return keypoints_list

    indices = np.linspace(0, n - 1, target_length).astype(int)
    return [keypoints_list[i] for i in indices]


def extract_keypoints_from_video(video_path, extractor, start_frame=1, end_frame=None):
    """
    Ouvre une vidéo, extrait les keypoints MediaPipe de chaque frame pertinente.
    Retourne une liste de vecteurs numpy (1662,).
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"  [WARN] Impossible d'ouvrir: {video_path}")
        return None

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if end_frame is None or end_frame > total_frames:
        end_frame = total_frames

    keypoints_list = []
    frame_idx = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        # Ne traiter que les frames dans la plage [start_frame, end_frame]
        if frame_idx < start_frame:
            continue
        if frame_idx > end_frame:
            break

        try:
            _, keypoints = extractor.process_frame(frame)
            keypoints_list.append(keypoints)
        except Exception as e:
            # Si MediaPipe échoue sur une frame, on met des zéros
            keypoints_list.append(np.zeros(1662))

    cap.release()

    if len(keypoints_list) == 0:
        return None

    return keypoints_list


def process_all():
    """Pipeline principal : parse WLASL → extrait keypoints → sauvegarde .npy"""

    print("=" * 60)
    print("[INFO] WLASL → MediaPipe Keypoints Extractor")
    print("=" * 60)

    # 1. Charger les mappings
    class_map = load_class_list()         # {0: "book", 1: "drink", ...}
    target_words = load_target_words()    # ["book", "drink", ...]
    nslt = load_nslt_mapping()            # {"video_id": {"subset": ..., "action": [class, start, end]}}

    # Inverser : mot → class_id
    word_to_class = {}
    for cid, word in class_map.items():
        if word in target_words:
            word_to_class[word] = cid

    print(f"\n[INFO] Mots cibles trouvés dans WLASL: {list(word_to_class.keys())}")
    missing = [w for w in target_words if w not in word_to_class]
    if missing:
        print(f"[WARN] Mots non trouvés dans le dataset: {missing}")

    # 2. Regrouper les vidéos par mot cible
    # nslt format: "video_id" → {"subset": "train", "action": [class_id, start_frame, end_frame]}
    videos_by_word = {word: [] for word in word_to_class}
    for vid_id, info in nslt.items():
        class_id = info['action'][0]
        start = info['action'][1]
        end = info['action'][2]
        # Trouver le mot correspondant
        word = class_map.get(class_id)
        if word and word in word_to_class:
            video_file = os.path.join(VIDEOS_DIR, f"{vid_id}.mp4")
            if os.path.exists(video_file):
                videos_by_word[word].append({
                    'video_id': vid_id,
                    'path': video_file,
                    'start': start,
                    'end': end,
                    'subset': info['subset']
                })

    # 3. Traitement
    extractor = MediaPipeExtractor(mode='holistic')
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Sauvegarder la liste ordonnée des actions
    action_list = sorted(word_to_class.keys())
    actions_file = os.path.join(OUTPUT_DIR, 'actions.json')
    with open(actions_file, 'w', encoding='utf-8') as f:
        json.dump(action_list, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVE] Liste des actions sauvegardée: {actions_file}")
    print(f"   Actions: {action_list}\n")

    total_extracted = 0

    for word in action_list:
        vids = videos_by_word.get(word, [])
        # Garder absolument toutes les vidéos disponibles
        selected = vids

        word_dir = os.path.join(OUTPUT_DIR, word)
        os.makedirs(word_dir, exist_ok=True)

        print(f"[PROCESS] [{word.upper()}] — {len(selected)}/{len(vids)} vidéos disponibles")

        for seq_idx, vid_info in enumerate(selected):
            seq_dir = os.path.join(word_dir, str(seq_idx))
            os.makedirs(seq_dir, exist_ok=True)

            # Vérifier si déjà extrait (reprise après crash)
            if os.path.exists(os.path.join(seq_dir, f"{SEQUENCE_LENGTH - 1}.npy")):
                print(f"  [SKIP] Séquence {seq_idx} déjà extraite, skip.")
                total_extracted += 1
                continue

            print(f"  [VIDEO] Vidéo {vid_info['video_id']}.mp4 (frames {vid_info['start']}-{vid_info['end']})...")

            raw_keypoints = extract_keypoints_from_video(
                vid_info['path'], extractor,
                start_frame=vid_info['start'],
                end_frame=vid_info['end']
            )

            if raw_keypoints is None or len(raw_keypoints) < 3:
                print(f"  [WARN] Pas assez de frames exploitables, skip.")
                continue

            # Ré-échantillonner à exactement 30 frames
            resampled = resample_sequence(raw_keypoints, SEQUENCE_LENGTH)

            for frame_idx, kp in enumerate(resampled):
                npy_path = os.path.join(seq_dir, f"{frame_idx}.npy")
                np.save(npy_path, kp)

            total_extracted += 1
            print(f"  [OK] {SEQUENCE_LENGTH} frames sauvegardées.")

    print(f"\n{'=' * 60}")
    print(f"[DONE] Extraction terminée ! {total_extracted} séquences créées.")
    print(f"   Données dans: {OUTPUT_DIR}")
    print(f"   Prochaine étape: python model/train.py")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    process_all()
