"""
Step 3: Frame analysis module
Analyzes extracted frames using Google Vision and OpenAI Vision APIs
"""

import base64
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from google.cloud import vision
from openai import OpenAI

logger = logging.getLogger(__name__)

def convert_numpy_floats(obj):
    """Convert any numpy float types to Python floats for JSON serialization."""
    if isinstance(obj, dict):
        return {str(k): convert_numpy_floats(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_floats(item) for item in obj]
    elif isinstance(obj, Path):
        return str(obj)
    elif hasattr(obj, 'dtype'):  # Check if it's a numpy type
        return float(obj)
    return obj

class VisionAnalyzer:
    """Handles image analysis using multiple vision APIs with optimized usage."""
    
    def __init__(self, frames_dir: Path, output_dir: Path, metadata: Optional[dict] = None):
        """
        Initialize vision analyzer.
        
        Args:
            frames_dir: Directory containing frames to analyze
            output_dir: Directory to save analysis results
            metadata: Video metadata dictionary
        """
        self.frames_dir = Path(frames_dir)
        self.output_dir = Path(output_dir)
        self.metadata = convert_numpy_floats(metadata or {})
        
        # Initialize API clients
        self.vision_client = vision.ImageAnnotatorClient()
        self.openai_client = OpenAI()  # Initialize without explicit API key
        
        # Analysis storage
        self.google_vision_results = {}
        self.openai_results = {}
    
    def select_key_frames(self, scene_changes: List[Union[Path, str]], motion_scores: List[Tuple[Union[Path, str], float]], max_frames: int = 12) -> List[Path]:
        """
        Select key frames for detailed analysis.
        Prioritizes scene changes and high motion frames.
        """
        # Convert all paths to Path objects
        scene_changes = [Path(p) if isinstance(p, str) else p for p in scene_changes]
        motion_scores = [(Path(p) if isinstance(p, str) else p, float(s)) for p, s in motion_scores]
        
        selected_frames = []
        
        # Include all scene changes up to half of max_frames
        scene_limit = max_frames // 2
        if scene_changes:
            selected_frames.extend(scene_changes[:scene_limit])
        
        # Sort motion scores by magnitude
        sorted_motion = sorted(motion_scores, key=lambda x: x[1], reverse=True)
        
        # Add highest motion frames that aren't too close to already selected frames
        for frame_path, _ in sorted_motion:
            if len(selected_frames) >= max_frames:
                break
                
            # Check if frame is sufficiently different in time from selected frames
            frame_time = float(frame_path.name.split('_')[1].replace('s.jpg', ''))
            is_unique = all(
                abs(float(f.name.split('_')[1].replace('s.jpg', '')) - frame_time) > 2.0
                for f in selected_frames
            )
            
            if is_unique and frame_path not in selected_frames:
                selected_frames.append(frame_path)
        
        return selected_frames
    
    async def analyze_frame_google_vision(self, frame_path: Path) -> Tuple[Optional[dict], bool]:
        """
        Analyze a frame using Google Vision API.
        Optimized to use only essential features.
        """
        try:
            with open(frame_path, "rb") as image_file:
                content = image_file.read()
            
            image = vision.Image(content=content)
            features = [
                vision.Feature(type_=vision.Feature.Type.LABEL_DETECTION, max_results=20),
                vision.Feature(type_=vision.Feature.Type.OBJECT_LOCALIZATION, max_results=20),
                vision.Feature(type_=vision.Feature.Type.IMAGE_PROPERTIES)
            ]
            request = vision.AnnotateImageRequest(image=image, features=features)
            response = self.vision_client.annotate_image(request)
            
            # Enhanced object validation
            validated_objects = []
            for obj in response.localized_object_annotations:
                # Higher confidence threshold for better accuracy
                if obj.score >= 0.7:  
                    validated_objects.append({
                        'name': str(obj.name),  # Ensure name is string
                        'confidence': float(obj.score),
                        'area': float(obj.bounding_poly.normalized_vertices[2].x * obj.bounding_poly.normalized_vertices[2].y)
                    })
            
            # Sort objects by area and confidence
            validated_objects.sort(key=lambda x: (x['area'], x['confidence']), reverse=True)
            
            # Convert all values to basic Python types
            result = {
                "labels": [{'description': str(label.description), 'confidence': float(label.score)} 
                          for label in response.label_annotations if label.score >= 0.7],
                "objects": validated_objects,
                "confidence": float(response.label_annotations[0].score) if response.label_annotations else 0.0
            }
            
            return convert_numpy_floats(result), True
        except Exception as e:
            logger.error(f"Google Vision API error: {str(e)}")
            return None, False
    
    async def analyze_frame_openai(self, frame_path: Path, google_analysis: Optional[dict] = None) -> Tuple[Optional[dict], bool]:
        """
        Analyze a frame using OpenAI Vision API.
        Provides detailed scene understanding.
        """
        try:
            with open(frame_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            
            # Convert google_analysis to ensure it's JSON serializable
            if google_analysis:
                google_analysis = convert_numpy_floats(google_analysis)
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self._build_openai_prompt(google_analysis)},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=300,
            )
            
            return {"detailed_description": response.choices[0].message.content}, True
        except Exception as e:
            logger.error(f"OpenAI Vision API error: {str(e)}")
            return None, False
    
    def _build_openai_prompt(self, google_analysis: Optional[dict] = None) -> str:
        """Build prompt for OpenAI Vision API analysis."""
        prompt = f"""Analyze this frame in detail, considering both the visual content and the following context:

Video Title: {self.metadata.get('title', 'Unknown')}
Description: {self.metadata.get('description', 'No description available')}

Previous computer vision analysis detected:"""
        
        if google_analysis:
            if google_analysis.get("labels"):
                prompt += "\nKey elements detected (with confidence):"
                for label in google_analysis["labels"]:
                    prompt += f"\n- {label['description']} ({label['confidence']:.2f})"
            
            if google_analysis.get("objects"):
                prompt += "\n\nObjects detected (with confidence and relative size):"
                for obj in google_analysis["objects"]:
                    prompt += f"\n- {obj['name']} (confidence: {obj['confidence']:.2f}, area: {obj['area']:.2f})"
        
        prompt += """

Please provide a comprehensive analysis that:
1. Describes the main focus or subject of this frame in relation to the video's context
2. Explains any actions, movements, or interactions visible in the frame
3. Notes significant details that align with or add to the video's narrative
4. Analyzes how this moment connects to the overall story being told in the description
5. Corrects any potential misidentifications from computer vision (e.g., if an object was incorrectly labeled)
6. Pay special attention to distinguishing between similar animals (e.g., deer vs dog, horse vs deer)

Keep the analysis natural and focused on how this frame relates to the video's context."""
        
        return prompt
    
    async def analyze_video(self, scene_changes: List[Path], motion_scores: List[Tuple[Path, float]], video_duration: float) -> dict:
        """
        Main analysis workflow with optimized API usage.
        """
        try:
            # Convert all inputs to ensure consistent types
            scene_changes = [Path(p) if isinstance(p, str) else p for p in scene_changes]
            motion_scores = [(Path(p) if isinstance(p, str) else p, float(s)) for p, s in motion_scores]
            video_duration = float(video_duration)
            
            final_results = {
                "metadata": self.metadata,
                "frames": []
            }
            
            # Select key frames for analysis
            key_frames = self.select_key_frames(scene_changes, motion_scores, max_frames=12)
            logger.info(f"Selected {len(key_frames)} key frames for analysis")
            
            # Analyze all selected frames with Google Vision
            google_vision_results = []
            for frame_path in key_frames:
                frame_result = {
                    "frame": frame_path.name,
                    "timestamp": float(frame_path.name.split('_')[1].replace('s.jpg', '')),
                    "path": str(frame_path)
                }
                
                # Google Vision Analysis for all frames
                google_analysis, success = await self.analyze_frame_google_vision(frame_path)
                if success:
                    frame_result["google_vision"] = google_analysis
                    google_vision_results.append(frame_result)
                    final_results["frames"].append(frame_result)
            
            # Aggregate all Google Vision results using string keys
            unique_labels = {}
            unique_objects = {}
            
            for result in google_vision_results:
                if "google_vision" in result:
                    # Process labels
                    for label in result["google_vision"].get("labels", []):
                        desc = str(label['description'])
                        if desc not in unique_labels or label['confidence'] > unique_labels[desc]['confidence']:
                            unique_labels[desc] = label
                    
                    # Process objects
                    for obj in result["google_vision"].get("objects", []):
                        name = str(obj['name'])
                        if name not in unique_objects or obj['confidence'] > unique_objects[name]['confidence']:
                            unique_objects[name] = obj
            
            # Convert back to lists and sort
            all_labels = sorted(unique_labels.values(), key=lambda x: x['confidence'], reverse=True)
            all_objects = sorted(unique_objects.values(), key=lambda x: x['confidence'], reverse=True)
            
            # Select frames for OpenAI analysis
            openai_frames = sorted(google_vision_results, 
                                 key=lambda x: x["google_vision"].get("confidence", 0),
                                 reverse=True)[:3]
            
            # OpenAI Vision Analysis for selected frames
            for frame_data in openai_frames:
                frame_path = self.frames_dir / frame_data["frame"]
                
                # Pass aggregated Google Vision results to OpenAI
                openai_analysis, success = await self.analyze_frame_openai(
                    frame_path,
                    {
                        "labels": all_labels,
                        "objects": all_objects,
                        "current_frame_objects": frame_data["google_vision"].get("objects", []),
                        "current_frame_labels": frame_data["google_vision"].get("labels", [])
                    }
                )
                
                if success:
                    # Add OpenAI analysis to the frame
                    for frame in final_results["frames"]:
                        if frame["frame"] == frame_data["frame"]:
                            frame["openai_vision"] = openai_analysis
                            break
            
            # Save results
            analysis_file = self.output_dir / "final_analysis.json"
            with open(analysis_file, 'w', encoding='utf-8') as f:
                json.dump(convert_numpy_floats(final_results), f, indent=2, ensure_ascii=False)
            
            logger.info(f"Analysis complete. Results saved to {analysis_file}")
            return convert_numpy_floats(final_results)
            
        except Exception as e:
            logger.error(f"Error in analyze_video: {str(e)}")
            raise

async def execute_step(
    frames_dir: Path,
    output_dir: Path,
    metadata: dict,
    scene_changes: List[Path],
    motion_scores: List[Tuple[Path, float]],
    video_duration: float
) -> dict:
    """
    Execute frame analysis step.
    
    Args:
        frames_dir: Directory containing extracted frames
        output_dir: Directory to save analysis results
        metadata: Video metadata dictionary
        scene_changes: List of frames where scene changes were detected
        motion_scores: List of tuples containing (frame path, motion score)
        video_duration: Duration of the video in seconds
        
    Returns:
        Dictionary containing analysis results
    """
    logger.debug("Step 3: Analyzing frames...")
    
    # Convert all inputs to ensure consistent types
    frames_dir = Path(frames_dir)
    output_dir = Path(output_dir)
    metadata = convert_numpy_floats(metadata)
    scene_changes = [Path(p) if isinstance(p, str) else p for p in scene_changes]
    motion_scores = [(Path(p) if isinstance(p, str) else p, float(s)) for p, s in motion_scores]
    video_duration = float(video_duration)
    
    # Initialize analyzer with metadata
    analyzer = VisionAnalyzer(frames_dir, output_dir, metadata)
    
    # Analyze video with provided parameters
    results = await analyzer.analyze_video(scene_changes, motion_scores, video_duration)
    
    logger.debug(f"Analyzed {len(results['frames'])} frames")
    return results 