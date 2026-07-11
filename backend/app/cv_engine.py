import cv2
import numpy as np
import base64
import time

import os

try:
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision
    MEDIAPIPE_AVAILABLE = True
except ImportError:
    MEDIAPIPE_AVAILABLE = False

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

def decode_base64_image(base64_string):
    """
    Decodes a base64 encoded image string (optionally containing the data URL prefix)
    into an OpenCV BGR image.
    """
    if "," in base64_string:
        base64_string = base64_string.split(",")[1]
    image_bytes = base64.b64decode(base64_string)
    np_arr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    return image

def calculate_angle(a, b, c):
    """
    Calculates the angle at point B formed by points A, B, and C.
    Points are passed as dicts {'x': val, 'y': val, 'z': val}
    """
    pt_a = np.array([a['x'], a['y'], a['z']])
    pt_b = np.array([b['x'], b['y'], b['z']])
    pt_c = np.array([c['x'], c['y'], c['z']])
    
    # Calculate vectors
    ba = pt_a - pt_b
    bc = pt_c - pt_b
    
    # Calculate cosine of the angle
    cosine_angle = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-6)
    cosine_angle = np.clip(cosine_angle, -1.0, 1.0)
    
    # Arc-cosine to get angle in radians, then convert to degrees
    angle = np.arccos(cosine_angle)
    return float(np.degrees(angle))

class WorkoutFSM:
    """
    Finite State Machine (FSM) to count repetitions and measure performance metrics
    while filtering out noise and sensor shaking.
    Supported exercises: squat, bicep_curl, bench_press, lateral_raise, pull_up
    """
    def __init__(self, exercise):
        self.exercise = exercise.lower()
        self.rep_count = 0
        self.rep_start_time = None
        
        # All exercises use a 4-state cycle:
        #   UP -> DOWNGOING -> DOWN -> UPGOING -> UP (rep counted)
        # OR
        #   DOWN -> UPGOING -> UP -> DOWNGOING -> DOWN (rep counted)
        # The "flex" threshold = angle below which counts as the contracted end
        # The "extend" threshold = angle above which counts as the extended end
        
        if self.exercise == "squat":
            self.state = "UP"
            self.direction = "down_first"   # starts UP, goes down first
            self.flex_threshold = 115.0     # knee angle at depth
            self.extend_threshold = 150.0   # standing straight
        elif self.exercise == "bicep_curl":
            self.state = "DOWN"
            self.direction = "up_first"     # starts DOWN (arms extended), curls up
            self.flex_threshold = 95.0      # elbow angle at squeeze
            self.extend_threshold = 135.0   # full arm extension
        elif self.exercise == "bench_press":
            self.state = "UP"
            self.direction = "down_first"   # starts UP (arms extended), lowers bar
            self.flex_threshold = 100.0     # elbow angle at chest
            self.extend_threshold = 145.0   # arms locked out
        elif self.exercise == "lateral_raise":
            self.state = "DOWN"
            self.direction = "up_first"     # starts DOWN (arms at sides), raises
            self.flex_threshold = 60.0      # shoulder angle when arms raised (angle gets smaller as arms go up)
            self.extend_threshold = 140.0   # arms at sides
        elif self.exercise == "pull_up":
            self.state = "DOWN"
            self.direction = "up_first"     # starts DOWN (hanging), pulls up
            self.flex_threshold = 90.0      # elbow angle at top
            self.extend_threshold = 145.0   # arms extended at hang
        else:
            # Default to bicep curl behavior
            self.state = "DOWN"
            self.direction = "up_first"
            self.flex_threshold = 95.0
            self.extend_threshold = 135.0
            
        self.min_angle_in_rep = 180.0
        self.max_angle_in_rep = 0.0

    def update(self, current_angle, time_now=None):
        """
        Updates the state machine based on the current joint angle.
        Returns a tuple: (rep_completed, rep_info)
        - rep_completed: bool (True if a full rep was just completed)
        - rep_info: dict or None (details about the completed rep)
        """
        if time_now is None:
            time_now = time.time()
            
        rep_completed = False
        rep_info = None
        
        # Track min/max angles during the current movement
        self.min_angle_in_rep = min(self.min_angle_in_rep, current_angle)
        self.max_angle_in_rep = max(self.max_angle_in_rep, current_angle)
        
        if self.direction == "down_first":
            # Exercises that start UP and go DOWN first (squat, bench_press)
            # Cycle: UP -> DOWNGOING -> DOWN -> UPGOING -> UP (rep complete)
            if self.state == "UP":
                if current_angle < self.extend_threshold - 10:
                    self.state = "DOWNGOING"
                    self.rep_start_time = time_now
                    self.min_angle_in_rep = current_angle
                    self.max_angle_in_rep = current_angle
            elif self.state == "DOWNGOING":
                if current_angle <= self.flex_threshold:
                    self.state = "DOWN"
                elif current_angle >= self.extend_threshold:
                    # Cancelled rep (went back up without hitting depth)
                    self.state = "UP"
            elif self.state == "DOWN":
                if current_angle > self.flex_threshold + 10:
                    self.state = "UPGOING"
            elif self.state == "UPGOING":
                if current_angle >= self.extend_threshold:
                    self.state = "UP"
                    self.rep_count += 1
                    rep_completed = True
                    duration = time_now - self.rep_start_time if self.rep_start_time else 2.0
                    rep_info = {
                        "rep_number": self.rep_count,
                        "duration": duration,
                        "min_angle": self.min_angle_in_rep,
                        "max_angle": self.max_angle_in_rep,
                        "form_score": 100.0
                    }
                    self.rep_start_time = None
                    
        else:
            # Exercises that start DOWN and go UP first (bicep_curl, lateral_raise, pull_up)
            # Cycle: DOWN -> UPGOING -> UP -> DOWNGOING -> DOWN (rep complete)
            if self.state == "DOWN":
                if current_angle < self.extend_threshold - 10:
                    self.state = "UPGOING"
                    self.rep_start_time = time_now
                    self.min_angle_in_rep = current_angle
                    self.max_angle_in_rep = current_angle
            elif self.state == "UPGOING":
                if current_angle <= self.flex_threshold:
                    self.state = "UP"
                elif current_angle >= self.extend_threshold:
                    # Cancelled rep
                    self.state = "DOWN"
            elif self.state == "UP":
                if current_angle > self.flex_threshold + 15:
                    self.state = "DOWNGOING"
            elif self.state == "DOWNGOING":
                if current_angle >= self.extend_threshold:
                    self.state = "DOWN"
                    self.rep_count += 1
                    rep_completed = True
                    duration = time_now - self.rep_start_time if self.rep_start_time else 2.0
                    rep_info = {
                        "rep_number": self.rep_count,
                        "duration": duration,
                        "min_angle": self.min_angle_in_rep,
                        "max_angle": self.max_angle_in_rep,
                        "form_score": 100.0
                    }
                    self.rep_start_time = None
                    
        return rep_completed, rep_info


class PoseTracker:
    """
    Pose Tracker: Uses YOLOv8-Pose as primary and MediaPipe Tasks PoseLandmarker as fallback
    to extract body landmarks from OpenCV frames.
    """
    def __init__(self):
        self.yolo_model = None
        self.landmarker = None
        
        # 1. Initialize YOLOv8-Pose (Primary Tracker)
        if YOLO_AVAILABLE:
            try:
                # Load YOLOv8-pose model (nano for speed)
                self.yolo_model = YOLO('yolov8n-pose.pt')
                print("YOLOv8-Pose initialized successfully as primary tracker in backend!")
            except Exception as e:
                print(f"Error initializing YOLOv8-Pose: {e}. Falling back to MediaPipe.")
                self.yolo_model = None

        # 2. Initialize MediaPipe (Fallback Tracker)
        if MEDIAPIPE_AVAILABLE:
            try:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                model_path = os.path.join(base_dir, "pose_landmarker_full.task")
                
                if os.path.exists(model_path):
                    base_options = python.BaseOptions(model_asset_path=model_path)
                    options = vision.PoseLandmarkerOptions(
                        base_options=base_options,
                        output_segmentation_masks=False,
                        running_mode=vision.RunningMode.IMAGE
                    )
                    self.landmarker = vision.PoseLandmarker.create_from_options(options)
                    print("MediaPipe Tasks PoseLandmarker initialized successfully in backend!")
                else:
                    print(f"MediaPipe model file not found at {model_path}.")
            except Exception as e:
                print(f"Error initializing MediaPipe Tasks PoseLandmarker: {e}.")
                self.landmarker = None

        if self.yolo_model is None and self.landmarker is None:
            print("Both trackers unavailable. Running in simulated pose mode.")

    def process_frame(self, image):
        """
        Processes an OpenCV BGR image.
        Returns a list of 33 dictionaries representing the landmarks:
        [{'x': val, 'y': val, 'z': val, 'visibility': val}, ...]
        or None if detection fails.
        """
        # --- PRIMARY: YOLOv8-Pose ---
        if self.yolo_model is not None:
            try:
                results = self.yolo_model(image, verbose=False)
                if results and len(results) > 0:
                    result = results[0]
                    if result.keypoints is not None and len(result.keypoints.xy) > 0:
                        xyn = result.keypoints.xyn[0].cpu().numpy()  # normalized coordinates
                        conf = result.keypoints.conf[0].cpu().numpy()  # keypoint confidence scores
                        
                        if np.any(xyn):
                            # Initialize 33 MediaPipe-compliant landmarks
                            landmarks = [{'x': 0.5, 'y': 0.5, 'z': 0.0, 'visibility': 0.0} for _ in range(33)]
                            
                            # YOLO COCO -> MediaPipe index mapping
                            yolo_to_mp = {
                                0: 0,   # Nose
                                1: 2,   # L Eye
                                2: 5,   # R Eye
                                3: 7,   # L Ear
                                4: 8,   # R Ear
                                5: 11,  # L Shoulder
                                6: 12,  # R Shoulder
                                7: 13,  # L Elbow
                                8: 14,  # R Elbow
                                9: 15,  # L Wrist
                                10: 16, # R Wrist
                                11: 23, # L Hip
                                12: 24, # R Hip
                                13: 25, # L Knee
                                14: 26, # R Knee
                                15: 27, # L Ankle
                                16: 28, # R Ankle
                            }
                            
                            for yolo_idx, mp_idx in yolo_to_mp.items():
                                landmarks[mp_idx] = {
                                    'x': float(xyn[yolo_idx][0]),
                                    'y': float(xyn[yolo_idx][1]),
                                    'z': 0.0,
                                    'visibility': float(conf[yolo_idx])
                                }
                            
                            # Hand padding (copy Wrist coords)
                            for mp_idx in [17, 19, 21]:
                                landmarks[mp_idx] = landmarks[15]
                            for mp_idx in [18, 20, 22]:
                                landmarks[mp_idx] = landmarks[16]
                                
                            # Foot padding (copy Ankle coords)
                            for mp_idx in [29, 31]:
                                landmarks[mp_idx] = landmarks[27]
                            for mp_idx in [30, 32]:
                                landmarks[mp_idx] = landmarks[28]
                                
                            return landmarks
            except Exception as e:
                print(f"YOLOv8-Pose processing error: {e}. Falling back to MediaPipe.")

        # --- FALLBACK: MediaPipe ---
        if self.landmarker is not None:
            try:
                rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_image)
                results = self.landmarker.detect(mp_image)
                
                if results.pose_landmarks and len(results.pose_landmarks) > 0:
                    raw_landmarks = results.pose_landmarks[0]
                    landmarks = []
                    for lm in raw_landmarks:
                        landmarks.append({
                            'x': lm.x,
                            'y': lm.y,
                            'z': lm.z,
                            'visibility': lm.visibility
                        })
                    return landmarks
            except Exception as e:
                print(f"MediaPipe Tasks processing error: {e}")

        return None
    def generate_mock_landmarks(self, exercise, frame_index):
        """
        Generates realistic simulated coordinates for testing when MediaPipe is not running,
        creating standard squatting and curling movements.
        """
        landmarks = [{'x': 0.5, 'y': 0.5, 'z': 0.0, 'visibility': 0.9} for _ in range(33)]
        
        # Calculate simulated angles based on frame count (30 frames per cycle)
        cycle_frames = 60
        progress = (frame_index % cycle_frames) / cycle_frames
        
        # Sine wave mapping to simulate natural joint movements
        if exercise.lower() == "squat":
            # Knee flexion cycles between 170° and 85°
            factor = (1.0 - np.cos(2 * np.pi * progress)) / 2.0  # ranges 0 to 1
            simulated_knee_angle = 175.0 - (factor * 95.0)
            
            # Left Hip (23), Left Knee (25), Left Ankle (27)
            # Hip: (0.5, 0.4)
            # Ankle: (0.5, 0.9)
            # Knee moves horizontally/vertically to adjust angle
            landmarks[23] = {'x': 0.5, 'y': 0.4, 'z': 0.0, 'visibility': 0.95}
            landmarks[24] = {'x': 0.6, 'y': 0.4, 'z': 0.0, 'visibility': 0.95}
            
            # Simulated knee movement
            knee_y = 0.65 + (factor * 0.1) # Knee drops lower
            knee_x = 0.45 - (factor * 0.05) # Knee pushes out slightly
            
            landmarks[25] = {'x': knee_x, 'y': knee_y, 'z': -0.1, 'visibility': 0.95}
            landmarks[26] = {'x': 1.1 - knee_x, 'y': knee_y, 'z': -0.1, 'visibility': 0.95}
            
            landmarks[27] = {'x': 0.48, 'y': 0.85, 'z': 0.0, 'visibility': 0.95}
            landmarks[28] = {'x': 0.62, 'y': 0.85, 'z': 0.0, 'visibility': 0.95}
            
            landmarks[11] = {'x': 0.49, 'y': 0.2, 'z': 0.0, 'visibility': 0.95}
            landmarks[12] = {'x': 0.61, 'y': 0.2, 'z': 0.0, 'visibility': 0.95}
            
            return landmarks, simulated_knee_angle
        else:
            # Bicep curl elbow cycles between 170° and 50°
            factor = (1.0 - np.cos(2 * np.pi * progress)) / 2.0  # ranges 0 to 1
            simulated_elbow_angle = 165.0 - (factor * 115.0)
            
            # Shoulder (11), Elbow (13), Wrist (15)
            landmarks[11] = {'x': 0.45, 'y': 0.25, 'z': 0.0, 'visibility': 0.95}
            landmarks[12] = {'x': 0.55, 'y': 0.25, 'z': 0.0, 'visibility': 0.95}
            
            landmarks[13] = {'x': 0.44, 'y': 0.45, 'z': 0.0, 'visibility': 0.95}
            landmarks[14] = {'x': 0.56, 'y': 0.45, 'z': 0.0, 'visibility': 0.95}
            
            # Wrist moves upwards to flex the elbow
            wrist_y = 0.65 - (factor * 0.3)
            wrist_x = 0.45 - (factor * 0.05)
            
            landmarks[15] = {'x': wrist_x, 'y': wrist_y, 'z': -0.2, 'visibility': 0.95}
            landmarks[16] = {'x': 1.0 - wrist_x, 'y': wrist_y, 'z': -0.2, 'visibility': 0.95}
            
            return landmarks, simulated_elbow_angle
