"""
ASL Alphabet Images → MediaPipe Keypoints Extractor
===================================================
Lit les images statiques ASL (A-Z, del, nothing, space), 
extrait les keypoints via MediaPipe Hands, et sauvegarde 
les données sous forme de tableaux compressés (.npy) par classe.
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
IMAGE_DATASET_DIR = os.path.join(BASE_DIR, 'data', 'knowledge', 'asl_images', 'asl_alphabet_train')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data', 'knowledge', 'asl_data_hands')


def process_images():
    if not os.path.exists(IMAGE_DATASET_DIR):
        print(f"[ERR] Le dossier {IMAGE_DATASET_DIR} n'existe pas !")
        return

    print("=" * 60)
    print("[INFO] ASL Alphabet → MediaPipe Hands Extractor")
    print("=" * 60)

    # Créer le répertoire de sortie
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # Identifier les classes (sous-dossiers A, B, C...)
    classes = sorted([d for d in os.listdir(IMAGE_DATASET_DIR) if os.path.isdir(os.path.join(IMAGE_DATASET_DIR, d))])
    
    if not classes:
        print("[ERR] Aucun sous-dossier trouvé dans le dataset d'images.")
        return

    # Sauvegarder la liste des actions
    actions_file = os.path.join(OUTPUT_DIR, 'actions_hands.json')
    with open(actions_file, 'w', encoding='utf-8') as f:
        json.dump(classes, f, ensure_ascii=False, indent=2)
    print(f"[SAVE] Classes sauvegardées ({len(classes)} classes) : {actions_file}")

    # Initialiser l'extracteur en mode "Hands" (seulement les mains)
    extractor = MediaPipeExtractor(mode='hands')

    total_extracted = 0

    for cls in classes:
        class_dir = os.path.join(IMAGE_DATASET_DIR, cls)
        images = [f for f in os.listdir(class_dir) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
        
        # Vérifier si on a déjà extrait cette classe
        out_npy = os.path.join(OUTPUT_DIR, f"{cls}.npy")
        if os.path.exists(out_npy):
            print(f"[SKIP] Classe '{cls}' déjà extraite, passage au suivant.")
            # On pourrait le charger pour compter, mais on avance
            continue
            
        print(f"[PROCESS] Classe '{cls}' : {len(images)} images détectées. Extraction en cours...")
        
        valid_keypoints = []
        for img_idx, img_name in enumerate(images):
            img_path = os.path.join(class_dir, img_name)
            
            # Afficher la progression tous les 500 images
            if img_idx > 0 and img_idx % 500 == 0:
                print(f"   -> {img_idx}/{len(images)} images traitées...")
                
            frame = cv2.imread(img_path)
            if frame is None:
                continue
                
            # Extraire les points (MediaPipe)
            try:
                _, keypoints = extractor.process_frame(frame)
                
                # Vérifier si des mains ont été détectées (les 126 dernières valeurs ne doivent pas être toutes zéros)
                if np.sum(keypoints[-126:]) != 0:
                    valid_keypoints.append(keypoints)
            except Exception as e:
                pass
                
        # Sauvegarder toutes les images valides pour cette classe dans un seul fichier .npy
        if valid_keypoints:
            X_class = np.array(valid_keypoints)
            np.save(out_npy, X_class)
            total_extracted += len(valid_keypoints)
            print(f"  [OK] Classe '{cls}' terminée : {len(valid_keypoints)} images valides sauvegardées.")
        else:
            print(f"  [WARN] Aucun point valide extrait pour la classe '{cls}'.")

    print(f"\n{'=' * 60}")
    print(f"[DONE] Extraction images statiques terminée !")
    print(f"   Total d'images converties en points: {total_extracted}")
    print(f"   Données sauvegardées dans: {OUTPUT_DIR}")
    print(f"   Prochaine étape: python model/train_alphabet.py")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    process_images()
