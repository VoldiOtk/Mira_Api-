"""
WLASL Video → MediaPipe Keypoints Extractor
============================================
Lit les vidéos WLASL, extrait les keypoints via MediaPipe Holistic,
et sauvegarde les séquences en fichiers .npy pour l'entraînement.

Modes (variables d'environnement):
  WLASL_NSLT=nslt_100.json          # palier vocabulaire
  WLASL_USE_ALL_CLASSES=1           # toutes les classes du palier (pas seulement labels.json)
  WLASL_MAX_VIDEOS_PER_CLASS=0      # 0 = toutes les vidéos disponibles par mot
"""
import os
import sys
import json
import cv2
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.mediapipe_extractor import MediaPipeExtractor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WLASL_DIR = os.path.join(BASE_DIR, "data", "knowledge", "asl_videos")
VIDEOS_DIR = os.path.join(WLASL_DIR, "videos")
CLASS_LIST_FILE = os.path.join(WLASL_DIR, "wlasl_class_list.txt")
LABELS_FILE = os.path.join(BASE_DIR, "data", "knowledge", "labels.json")
OUTPUT_DIR = os.path.join(BASE_DIR, "data", "knowledge", "asl_data")

NSLT_FILE = os.path.join(WLASL_DIR, os.getenv("WLASL_NSLT", "nslt_100.json"))
USE_ALL_CLASSES = os.getenv("WLASL_USE_ALL_CLASSES", "0").strip() in {"1", "true", "yes"}
MAX_VIDEOS_PER_CLASS = int(os.getenv("WLASL_MAX_VIDEOS_PER_CLASS", "0"))
SEQUENCE_LENGTH = 30


def load_class_list():
    mapping = {}
    with open(CLASS_LIST_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) == 2:
                mapping[int(parts[0])] = parts[1].lower()
    return mapping


def load_target_words_from_labels():
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        labels = json.load(f)
    return list(labels.keys())


def load_nslt_mapping():
    with open(NSLT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_target_words(class_map, nslt):
    """Détermine la liste des mots à extraire."""
    if USE_ALL_CLASSES:
        active_ids = {info["action"][0] for info in nslt.values() if "action" in info}
        return sorted({class_map[cid] for cid in active_ids if cid in class_map})

    return load_target_words_from_labels()


def resample_sequence(keypoints_list, target_length):
    n = len(keypoints_list)
    if n == 0:
        return [np.zeros(1662)] * target_length
    if n == target_length:
        return keypoints_list
    indices = np.linspace(0, n - 1, target_length).astype(int)
    return [keypoints_list[i] for i in indices]


def extract_keypoints_from_video(video_path, extractor, start_frame=1, end_frame=None):
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
        if frame_idx < start_frame:
            continue
        if frame_idx > end_frame:
            break
        try:
            _, keypoints = extractor.process_frame(frame)
            keypoints_list.append(keypoints)
        except Exception:
            keypoints_list.append(np.zeros(1662))

    cap.release()
    if len(keypoints_list) == 0:
        return None
    return keypoints_list


def process_all():
    print("=" * 60)
    print("[INFO] WLASL -> MediaPipe Keypoints Extractor")
    print(f"[INFO] NSLT: {os.path.basename(NSLT_FILE)}")
    print(f"[INFO] USE_ALL_CLASSES: {USE_ALL_CLASSES}")
    print("=" * 60)

    if not os.path.exists(NSLT_FILE):
        print(f"[ERR] Fichier NSLT introuvable: {NSLT_FILE}")
        return

    class_map = load_class_list()
    nslt = load_nslt_mapping()
    target_words = resolve_target_words(class_map, nslt)

    word_to_class = {}
    for cid, word in class_map.items():
        if word in target_words:
            word_to_class[word] = cid

    print(f"\n[INFO] {len(target_words)} mots cibles pour extraction")

    videos_by_word = {word: [] for word in target_words}
    missing_video_count = 0

    for vid_id, info in nslt.items():
        class_id = info["action"][0]
        start = info["action"][1]
        end = info["action"][2]
        word = class_map.get(class_id)
        if not word or word not in word_to_class:
            continue

        video_file = os.path.join(VIDEOS_DIR, f"{vid_id}.mp4")
        if os.path.exists(video_file):
            videos_by_word[word].append(
                {
                    "video_id": vid_id,
                    "path": video_file,
                    "start": start,
                    "end": end,
                    "subset": info.get("subset", ""),
                }
            )
        else:
            missing_video_count += 1

    if missing_video_count:
        print(f"[WARN] {missing_video_count} entrees NSLT sans fichier .mp4 local (voir missing.txt)")

    words_with_video = [w for w in target_words if videos_by_word.get(w)]
    words_without_video = [w for w in target_words if not videos_by_word.get(w)]
    if words_without_video:
        print(f"[WARN] {len(words_without_video)} mots sans aucune video locale (ex: {words_without_video[:8]}...)")

    extractor = MediaPipeExtractor(mode="holistic")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    action_list = sorted(words_with_video)
    actions_file = os.path.join(OUTPUT_DIR, "actions.json")
    with open(actions_file, "w", encoding="utf-8") as f:
        json.dump(action_list, f, ensure_ascii=False, indent=2)

    print(f"\n[SAVE] {len(action_list)} actions avec videos -> {actions_file}")

    total_extracted = 0
    for word in action_list:
        vids = videos_by_word.get(word, [])
        if MAX_VIDEOS_PER_CLASS > 0:
            vids = vids[:MAX_VIDEOS_PER_CLASS]

        word_dir = os.path.join(OUTPUT_DIR, word)
        os.makedirs(word_dir, exist_ok=True)
        print(f"[PROCESS] [{word.upper()}] - {len(vids)} video(s)")

        for seq_idx, vid_info in enumerate(vids):
            seq_dir = os.path.join(word_dir, str(seq_idx))
            os.makedirs(seq_dir, exist_ok=True)

            if os.path.exists(os.path.join(seq_dir, f"{SEQUENCE_LENGTH - 1}.npy")):
                print(f"  [SKIP] Sequence {seq_idx} deja extraite.")
                total_extracted += 1
                continue

            print(f"  [VIDEO] {vid_info['video_id']}.mp4 (frames {vid_info['start']}-{vid_info['end']})...")
            raw_keypoints = extract_keypoints_from_video(
                vid_info["path"],
                extractor,
                start_frame=vid_info["start"],
                end_frame=vid_info["end"],
            )

            if raw_keypoints is None or len(raw_keypoints) < 3:
                print("  [WARN] Pas assez de frames, skip.")
                continue

            resampled = resample_sequence(raw_keypoints, SEQUENCE_LENGTH)
            for frame_idx, kp in enumerate(resampled):
                np.save(os.path.join(seq_dir, f"{frame_idx}.npy"), kp)

            total_extracted += 1
            print(f"  [OK] {SEQUENCE_LENGTH} frames sauvegardees.")

    print(f"\n{'=' * 60}")
    print(f"[DONE] {total_extracted} sequences | mots avec donnees: {len(action_list)}/{len(target_words)}")
    print("   Prochaine etape: python model/train.py")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    process_all()
