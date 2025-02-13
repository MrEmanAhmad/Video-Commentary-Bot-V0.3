"""
Step 2: Frame extraction module
Extracts key frames from video using scene detection and motion analysis
"""

import logging
from pathlib import Path
from typing import List, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)

class FrameExtractor:
    """Handles video frame extraction with intelligent frame selection."""
    
    def __init__(self, video_path: Path, output_dir: Path):
        """
        Initialize frame extractor.
        
        Args:
            video_path: Path to video file
            output_dir: Directory to save extracted frames
        """
        self.video_path = video_path
        self.frames_dir = output_dir / "frames"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.scene_changes = []
        self.motion_scores = []
        
        # Load object detection models only if needed
        self.face_cascade = None
        self.body_cascade = None
    
    def _load_detection_models(self):
        """Lazy load detection models only when needed."""
        if self.face_cascade is None:
            self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
            self.body_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_fullbody.xml')
    
    def _compute_frame_difference(self, frame1: np.ndarray, frame2: np.ndarray) -> float:
        """
        Compute the difference between two frames.
        Uses grayscale conversion and absolute difference.
        """
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        
        # Calculate absolute difference and normalize
        diff = cv2.absdiff(gray1, gray2)
        norm_diff = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
        
        return np.mean(norm_diff)
    
    def _detect_motion(self, frame: np.ndarray, prev_frame: np.ndarray) -> float:
        """
        Detect motion between frames using optical flow.
        Returns average magnitude of motion vectors.
        """
        if prev_frame is None:
            return 0.0
            
        # Convert to grayscale
        gray1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Calculate optical flow using Farneback method
        flow = cv2.calcOpticalFlowFarneback(
            gray1, gray2, None,
            pyr_scale=0.5,  # Pyramid scale
            levels=3,       # Number of pyramid levels
            winsize=15,     # Window size
            iterations=3,   # Number of iterations
            poly_n=5,      # Polynomial degree
            poly_sigma=1.2, # Gaussian sigma
            flags=0
        )
        
        # Calculate magnitude of flow vectors
        magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
        return np.mean(magnitude)
    
    def _detect_objects(self, frame: np.ndarray) -> int:
        """
        Detect objects in frame using pre-trained models.
        Currently detects faces and bodies.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Detect faces
        faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)
        
        # Detect bodies
        bodies = self.body_cascade.detectMultiScale(gray, 1.1, 3)
        
        return len(faces) + len(bodies)
    
    def _is_frame_interesting(self, 
                            frame: np.ndarray, 
                            prev_frame: np.ndarray,
                            frame_diff: float,
                            motion_score: float,
                            object_count: int,
                            min_scene_change: float,
                            min_motion_threshold: float) -> bool:
        """
        Determine if a frame is interesting based on multiple criteria.
        """
        # Check for scene changes
        is_scene_change = frame_diff > min_scene_change
        
        # Check for significant motion
        has_motion = motion_score > min_motion_threshold
        
        # Check for objects
        has_objects = object_count > 0
        
        return is_scene_change or has_motion or has_objects
    
    def extract_frames(
        self,
        min_scene_change: float = 30.0,
        min_motion_threshold: float = 2.0,
        max_frames: int = 4,
        frame_interval: int = 5
    ) -> List[Path]:
        """Extract key frames with optimized processing."""
        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {self.video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        saved_frames = []
        prev_frame = None
        last_saved_time = -2
        frame_buffer = []
        
        logger.info("Analyzing video for key frames...")
        
        for frame_number in range(0, frame_count, frame_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            if not ret:
                break
            
            timestamp = frame_number / fps
            
            # Skip if too close to last saved frame
            if timestamp - last_saved_time < 2:
                continue
            
            # Buffer frames for batch processing
            frame_buffer.append((frame, timestamp))
            if len(frame_buffer) >= 10:  # Process in batches of 10
                self._process_frame_batch(frame_buffer, saved_frames, min_scene_change, min_motion_threshold)
                frame_buffer = []
            
            if len(saved_frames) >= max_frames:
                break
            
            if frame_number % 100 == 0:
                logger.info(f"Progress: {(frame_number / frame_count) * 100:.1f}%")
        
        # Process remaining frames
        if frame_buffer:
            self._process_frame_batch(frame_buffer, saved_frames, min_scene_change, min_motion_threshold)
        
        cap.release()
        logger.info(f"Extracted {len(saved_frames)} key frames")
        return saved_frames

    def _process_frame_batch(
        self,
        frame_buffer: List[Tuple[np.ndarray, float]],
        saved_frames: List[Path],
        min_scene_change: float,
        min_motion_threshold: float
    ):
        """Process a batch of frames efficiently."""
        for i, (frame, timestamp) in enumerate(frame_buffer):
            if i > 0:
                prev_frame = frame_buffer[i-1][0]
                frame_diff = self._compute_frame_difference(frame, prev_frame)
                motion_score = self._detect_motion(frame, prev_frame)
                
                if frame_diff > min_scene_change or motion_score > min_motion_threshold:
                    frame_path = self.frames_dir / f"frame_{timestamp:.2f}s.jpg"
                    cv2.imwrite(str(frame_path), frame)
                    saved_frames.append(frame_path)
                    
                    if frame_diff > min_scene_change:
                        self.scene_changes.append(frame_path)
                    self.motion_scores.append((frame_path, motion_score))
                    
                    logger.info(f"Saved frame at {timestamp:.2f}s (scene_change={frame_diff > min_scene_change}, "
                              f"motion={motion_score:.2f}")
    
    def get_scene_changes(self) -> List[Path]:
        """Get list of frames where scene changes were detected."""
        return self.scene_changes
    
    def get_motion_scores(self) -> List[Tuple[Path, float]]:
        """Get motion scores for saved frames."""
        return self.motion_scores

def execute_step(
    video_file: Path,
    output_dir: Path,
    min_scene_change: float = 30.0,
    min_motion_threshold: float = 2.0,
    max_frames: int = 12  # Increased from 4 to 12
) -> Tuple[List[Path], List[Path], List[Tuple[Path, float]], float, dict]:
    """
    Execute frame extraction step.
    
    Args:
        video_file: Path to video file
        output_dir: Directory to save frames
        min_scene_change: Minimum difference for scene change detection
        min_motion_threshold: Minimum score for motion detection
        max_frames: Maximum number of frames to extract
        
    Returns:
        Tuple containing:
        - List of extracted frame paths
        - List of scene change frame paths
        - List of tuples containing (frame path, motion score)
        - Video duration in seconds
        - Video metadata dictionary
    """
    logger.debug("Step 2: Extracting frames...")
    
    # Load video metadata
    metadata = {}
    metadata_file = output_dir / "video_metadata.json"
    if metadata_file.exists():
        try:
            with open(metadata_file, 'r', encoding='utf-8') as f:
                import json
                metadata = json.load(f)
            logger.debug("Loaded video metadata")
        except Exception as e:
            logger.warning(f"Error loading metadata: {str(e)}")
    
    # Get video duration
    cap = cv2.VideoCapture(str(video_file))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_file}")
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0
    cap.release()
    
    frame_extractor = FrameExtractor(video_file, output_dir)
    key_frames = frame_extractor.extract_frames(
        min_scene_change=min_scene_change,
        min_motion_threshold=min_motion_threshold,
        max_frames=max_frames,
        frame_interval=3  # Reduced from 5 to 3 to sample more frequently
    )
    
    scene_changes = frame_extractor.get_scene_changes()
    motion_scores = frame_extractor.get_motion_scores()
    
    logger.debug(f"Extracted {len(key_frames)} key frames")
    logger.debug(f"Detected {len(scene_changes)} scene changes")
    logger.debug(f"Final video duration: {duration:.2f} seconds")
    
    return key_frames, scene_changes, motion_scores, duration, metadata 