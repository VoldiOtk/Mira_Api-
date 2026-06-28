import cv2
import numpy as np
import mediapipe as mp


class MediaPipeExtractor:
    def __init__(self, mode='holistic'):
        self.mode = mode
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles

        if self.mode == 'holistic':
            self.mp_model = mp.solutions.holistic
            self.detector = self.mp_model.Holistic(
                static_image_mode=False,
                model_complexity=1,
                smooth_landmarks=True,
                enable_segmentation=False,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.68,
            )
        elif self.mode == 'hands':
            self.mp_model = mp.solutions.hands
            self.detector = self.mp_model.Hands(
                static_image_mode=False,
                max_num_hands=2,
                model_complexity=1,
                min_detection_confidence=0.55,
                min_tracking_confidence=0.68,
            )
        else:
            raise ValueError("Le mode doit être 'hands' ou 'holistic'")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_frame(self, frame, annotate: bool = True, feature_version: str = "v1"):
        """Process a BGR frame and return (annotated_bgr, keypoints, hands_present).

        Parameters
        ----------
        frame          : BGR numpy array from OpenCV
        annotate       : Draw MediaPipe landmarks on the returned image
        feature_version: "v1" → 1662-dim (holistic, includes face)
                         "v2" → 258-dim (pose+hands only, shoulder-normalized)
        """
        image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image_rgb.flags.writeable = False
        results = self.detector.process(image_rgb)
        image_rgb.flags.writeable = True
        image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

        if annotate:
            self.draw_landmarks(image_bgr, results)

        if feature_version == "v2":
            keypoints = self.extract_keypoints_v2(results)
        else:
            keypoints = self.extract_keypoints(results)

        hands_present = self.has_hands(results)
        return image_bgr, keypoints, hands_present

    def has_hands(self, results) -> bool:
        """Return True if at least one hand is visible in the frame."""
        if self.mode == 'holistic':
            return (results.left_hand_landmarks is not None
                    or results.right_hand_landmarks is not None)
        elif self.mode == 'hands':
            return bool(results.multi_hand_landmarks)
        return False

    # ------------------------------------------------------------------
    # Feature extractors
    # ------------------------------------------------------------------

    def extract_keypoints(self, results) -> np.ndarray:
        """v1: 1662-dim flat vector (pose 132 + face 1404 + lh 63 + rh 63)."""
        if self.mode == 'holistic':
            pose = (np.array([[r.x, r.y, r.z, r.visibility]
                               for r in results.pose_landmarks.landmark]).flatten()
                    if results.pose_landmarks else np.zeros(33 * 4))
            face = (np.array([[r.x, r.y, r.z]
                               for r in results.face_landmarks.landmark]).flatten()
                    if results.face_landmarks else np.zeros(468 * 3))
            lh = (np.array([[r.x, r.y, r.z]
                              for r in results.left_hand_landmarks.landmark]).flatten()
                  if results.left_hand_landmarks else np.zeros(21 * 3))
            rh = (np.array([[r.x, r.y, r.z]
                              for r in results.right_hand_landmarks.landmark]).flatten()
                  if results.right_hand_landmarks else np.zeros(21 * 3))
            return np.concatenate([pose, face, lh, rh])

        elif self.mode == 'hands':
            pose = np.zeros(33 * 4)
            face = np.zeros(468 * 3)
            lh = np.zeros(21 * 3)
            rh = np.zeros(21 * 3)
            if results.multi_hand_landmarks:
                for idx, handedness in enumerate(results.multi_handedness):
                    label = handedness.classification[0].label
                    hand = np.array([[r.x, r.y, r.z]
                                      for r in results.multi_hand_landmarks[idx].landmark]).flatten()
                    if label == 'Left':
                        lh = hand
                    else:
                        rh = hand
            return np.concatenate([pose, face, lh, rh])

    def extract_keypoints_v2(self, results) -> np.ndarray:
        """v2: 258-dim compact vector (pose 132 + lh 63 + rh 63).

        Coordinates are normalized relative to the shoulder midpoint so the
        model learns *relative* motion instead of absolute screen position.
        This makes the model invariant to the signer's distance from the camera.
        """
        if self.mode == 'holistic':
            if results.pose_landmarks:
                pose = np.array(
                    [[r.x, r.y, r.z, r.visibility]
                     for r in results.pose_landmarks.landmark],
                    dtype=np.float32,
                )
                # Normalization reference: midpoint between shoulders (11 & 12)
                ref_xyz = (pose[11, :3] + pose[12, :3]) / 2.0
                pose_norm = pose.copy()
                pose_norm[:, :3] -= ref_xyz
                pose_flat = pose_norm.flatten()        # 132
            else:
                pose_flat = np.zeros(33 * 4, dtype=np.float32)
                ref_xyz = np.zeros(3, dtype=np.float32)

            if results.left_hand_landmarks:
                lh = np.array([[r.x, r.y, r.z]
                                for r in results.left_hand_landmarks.landmark],
                               dtype=np.float32)
                lh -= ref_xyz
                lh_flat = lh.flatten()                 # 63
            else:
                lh_flat = np.zeros(21 * 3, dtype=np.float32)

            if results.right_hand_landmarks:
                rh = np.array([[r.x, r.y, r.z]
                                for r in results.right_hand_landmarks.landmark],
                               dtype=np.float32)
                rh -= ref_xyz
                rh_flat = rh.flatten()                 # 63
            else:
                rh_flat = np.zeros(21 * 3, dtype=np.float32)

            return np.concatenate([pose_flat, lh_flat, rh_flat])  # 258

        elif self.mode == 'hands':
            # No pose available — zeros for pose, raw hand coords
            pose_flat = np.zeros(33 * 4, dtype=np.float32)
            lh_flat = np.zeros(21 * 3, dtype=np.float32)
            rh_flat = np.zeros(21 * 3, dtype=np.float32)
            if results.multi_hand_landmarks:
                for idx, handedness in enumerate(results.multi_handedness):
                    label = handedness.classification[0].label
                    hand = np.array(
                        [[r.x, r.y, r.z]
                         for r in results.multi_hand_landmarks[idx].landmark],
                        dtype=np.float32,
                    ).flatten()
                    if label == 'Left':
                        lh_flat = hand
                    else:
                        rh_flat = hand
            return np.concatenate([pose_flat, lh_flat, rh_flat])  # 258

    # ------------------------------------------------------------------
    # Drawing helpers (unchanged)
    # ------------------------------------------------------------------

    def draw_landmarks(self, image, results):
        if self.mode == 'holistic':
            if results.face_landmarks:
                self.mp_drawing.draw_landmarks(
                    image, results.face_landmarks,
                    self.mp_model.FACEMESH_TESSELATION,
                    self.mp_drawing.DrawingSpec(color=(80, 110, 10), thickness=1, circle_radius=1),
                    self.mp_drawing.DrawingSpec(color=(80, 256, 121), thickness=1, circle_radius=1),
                )
            if results.pose_landmarks:
                self.mp_drawing.draw_landmarks(
                    image, results.pose_landmarks,
                    self.mp_model.POSE_CONNECTIONS,
                    self.mp_drawing.DrawingSpec(color=(80, 22, 10), thickness=2, circle_radius=4),
                    self.mp_drawing.DrawingSpec(color=(80, 44, 121), thickness=2, circle_radius=2),
                )
            if results.left_hand_landmarks:
                self.mp_drawing.draw_landmarks(
                    image, results.left_hand_landmarks, self.mp_model.HAND_CONNECTIONS)
            if results.right_hand_landmarks:
                self.mp_drawing.draw_landmarks(
                    image, results.right_hand_landmarks, self.mp_model.HAND_CONNECTIONS)
        elif self.mode == 'hands':
            if results.multi_hand_landmarks:
                for hand_landmarks in results.multi_hand_landmarks:
                    self.mp_drawing.draw_landmarks(
                        image, hand_landmarks,
                        self.mp_model.HAND_CONNECTIONS,
                        self.mp_drawing_styles.get_default_hand_landmarks_style(),
                        self.mp_drawing_styles.get_default_hand_connections_style(),
                    )
