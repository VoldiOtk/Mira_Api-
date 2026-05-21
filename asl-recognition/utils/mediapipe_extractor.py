import cv2
import numpy as np
import mediapipe as mp

class MediaPipeExtractor:
    def __init__(self, mode='holistic'):
        """
        Initialise l'extracteur.
        :param mode: 'hands' (mains uniquement) ou 'holistic' (corps entier, visage, mains)
        """
        self.mode = mode
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        
        if self.mode == 'holistic':
            self.mp_model = mp.solutions.holistic
            self.detector = self.mp_model.Holistic(
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
        elif self.mode == 'hands':
            self.mp_model = mp.solutions.hands
            self.detector = self.mp_model.Hands(
                max_num_hands=2,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
        else:
            raise ValueError("Le mode doit être 'hands' ou 'holistic'")

    def process_frame(self, frame):
        """Prend une image BGR (OpenCV) et retourne l'image avec les points dessinés et les landmarks"""
        image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image_rgb.flags.writeable = False
        results = self.detector.process(image_rgb)
        image_rgb.flags.writeable = True
        image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

        self.draw_landmarks(image_bgr, results)
        keypoints = self.extract_keypoints(results)
        
        return image_bgr, keypoints

    def draw_landmarks(self, image, results):
        if self.mode == 'holistic':
            # Dessiner Visage
            if results.face_landmarks:
                self.mp_drawing.draw_landmarks(
                    image, results.face_landmarks, self.mp_model.FACEMESH_TESSELATION, 
                    self.mp_drawing.DrawingSpec(color=(80,110,10), thickness=1, circle_radius=1),
                    self.mp_drawing.DrawingSpec(color=(80,256,121), thickness=1, circle_radius=1)
                )
            # Dessiner Pose
            if results.pose_landmarks:
                self.mp_drawing.draw_landmarks(
                    image, results.pose_landmarks, self.mp_model.POSE_CONNECTIONS,
                    self.mp_drawing.DrawingSpec(color=(80,22,10), thickness=2, circle_radius=4),
                    self.mp_drawing.DrawingSpec(color=(80,44,121), thickness=2, circle_radius=2)
                )
            # Dessiner Mains (Gauche et Droite)
            if results.left_hand_landmarks:
                self.mp_drawing.draw_landmarks(image, results.left_hand_landmarks, self.mp_model.HAND_CONNECTIONS)
            if results.right_hand_landmarks:
                self.mp_drawing.draw_landmarks(image, results.right_hand_landmarks, self.mp_model.HAND_CONNECTIONS)
        
        elif self.mode == 'hands':
            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    self.mp_drawing.draw_landmarks(
                        image,
                        hand_landmarks,
                        self.mp_model.HAND_CONNECTIONS,
                        self.mp_drawing_styles.get_default_hand_landmarks_style(),
                        self.mp_drawing_styles.get_default_hand_connections_style()
                    )

    def extract_keypoints(self, results):
        """Convertit les repères de MediaPipe en un vecteur numpy 1D aplati de taille 1662 constante"""
        if self.mode == 'holistic':
            pose = np.array([[res.x, res.y, res.z, res.visibility] for res in results.pose_landmarks.landmark]).flatten() if results.pose_landmarks else np.zeros(33*4)
            face = np.array([[res.x, res.y, res.z] for res in results.face_landmarks.landmark]).flatten() if results.face_landmarks else np.zeros(468*3)
            lh = np.array([[res.x, res.y, res.z] for res in results.left_hand_landmarks.landmark]).flatten() if results.left_hand_landmarks else np.zeros(21*3)
            rh = np.array([[res.x, res.y, res.z] for res in results.right_hand_landmarks.landmark]).flatten() if results.right_hand_landmarks else np.zeros(21*3)
            return np.concatenate([pose, face, lh, rh])
        
        elif self.mode == 'hands':
            # Padding pour que la taille soit toujours 1662 comme dans le mode holistic
            pose = np.zeros(33*4)
            face = np.zeros(468*3)
            lh = np.zeros(21*3)
            rh = np.zeros(21*3)
            
            if results.multi_hand_landmarks:
                for idx, hand_handedness in enumerate(results.multi_handedness):
                    hand_label = hand_handedness.classification[0].label
                    hand_landmarks = np.array([[res.x, res.y, res.z] for res in results.multi_hand_landmarks[idx].landmark]).flatten()
                    if hand_label == 'Left':
                        lh = hand_landmarks
                    else:
                        rh = hand_landmarks
                        
            return np.concatenate([pose, face, lh, rh])
