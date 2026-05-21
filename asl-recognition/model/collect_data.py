import cv2
import numpy as np
import os
import sys

# Ajouter le parent au sys.path pour les imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.mediapipe_extractor import MediaPipeExtractor

# Configuration de la collecte
DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'knowledge', 'asl_data')
ACTIONS = np.array(['HELLO', 'EAT', 'THANK YOU', 'I LOVE YOU', 'YES'])
SEQUENCE_LENGTH = 30  # Nombre de frames par séquence
NO_SEQUENCES = 15     # Nombre de vidéos par action (pour le test, on met bas pour aller vite)

def capture_data(mode='holistic'):
    extractor = MediaPipeExtractor(mode=mode)
    cap = cv2.VideoCapture(0)

    # Création des dossiers si nécessaire
    for action in ACTIONS:
        dir_path = os.path.join(DATA_PATH, action)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

    for action in ACTIONS:
        for sequence in range(NO_SEQUENCES):
            # Créer le répertoire de la séquence
            seq_path = os.path.join(DATA_PATH, action, str(sequence))
            if not os.path.exists(seq_path):
                os.makedirs(seq_path)

            for frame_num in range(SEQUENCE_LENGTH):
                ret, frame = cap.read()
                if not ret:
                    break

                image, keypoints = extractor.process_frame(frame)

                # Affichage des instructions
                if frame_num == 0:
                    cv2.putText(image, 'PREPARATION...', (120, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 4, cv2.LINE_AA)
                    cv2.putText(image, f'Collecting frames for {action} Video Number {sequence}', (15, 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
                    cv2.imshow('OpenCV Feed', image)
                    cv2.waitKey(2000)
                else:
                    cv2.putText(image, f'Collecting frames for {action} Video Number {sequence}', (15, 12),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
                    cv2.imshow('OpenCV Feed', image)

                # Sauvegarde du keypoint
                npy_path = os.path.join(seq_path, str(frame_num))
                np.save(npy_path, keypoints)

                if cv2.waitKey(10) & 0xFF == ord('q'):
                    cap.release()
                    cv2.destroyAllWindows()
                    sys.exit()

    cap.release()
    cv2.destroyAllWindows()
    print("Collecte de données terminée !")

if __name__ == "__main__":
    print("Lancement de la collecte en mode holistic afin d'avoir toutes les features enregistrées.")
    capture_data(mode='holistic')
