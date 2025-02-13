"""
Step 6: Video generation module
Combines video and audio using Cloudinary for professional video processing
"""

import os
import logging
import re
from pathlib import Path
from typing import Optional, Dict
import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary import CloudinaryVideo
import requests
import aiohttp

logger = logging.getLogger(__name__)

class VideoGenerator:
    """Handles video generation and audio overlay using Cloudinary."""
    
    def __init__(self, cloud_name: str, api_key: str, api_secret: str):
        """
        Initialize the VideoGenerator with Cloudinary credentials.
        
        Args:
            cloud_name: Cloudinary cloud name
            api_key: Cloudinary API key
            api_secret: Cloudinary API secret
        """
        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret
        )
        self.uploaded_resources = []
        self.uploaded_logos = {}  # Cache for logo public_ids
        self._setup_cloudinary_config()
        
    def _setup_cloudinary_config(self):
        """Configure Cloudinary for optimal performance."""
        cloudinary.config(
            secure=True,
            chunk_size=6000000,  # 6MB chunks for faster uploads
            use_cache=True,
            cache_duration=3600  # 1 hour cache
        )
        
    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for Cloudinary public ID.
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename suitable for Cloudinary
        """
        # Remove file extension
        filename = os.path.splitext(filename)[0]
        # Remove emojis and special characters
        filename = re.sub(r'[^\w\s-]', '', filename)
        # Replace spaces with underscores
        filename = re.sub(r'[-\s]+', '_', filename)
        # Ensure it's not empty
        if not filename:
            filename = 'video'
        return filename.strip('_')
        
    async def upload_media(self, file_path: str, resource_type: str) -> Optional[Dict]:
        """
        Upload media file to Cloudinary with optimized settings.
        
        Args:
            file_path: Path to the media file
            resource_type: Type of resource ('video' or 'raw' for audio)
            
        Returns:
            Upload response if successful, None otherwise
        """
        try:
            # Sanitize the filename for the public_id
            public_id = self._sanitize_filename(os.path.basename(file_path))
            logger.info(f"Uploading {resource_type}: {file_path}")
            
            # Optimize upload settings
            response = cloudinary.uploader.upload(
                file_path,
                resource_type=resource_type,
                public_id=public_id,
                overwrite=True,
                chunk_size=6000000,  # 6MB chunks
                eager_async=True,  # Async transformations
                eager=[  # Pre-generate common transformations
                    {"quality": "auto:good"},
                    {"fetch_format": "auto"}
                ],
                use_filename=True,
                unique_filename=False,
                invalidate=True
            )
            
            logger.info(f"Upload successful. Public ID: {response['public_id']}")
            self.uploaded_resources.append(response['public_id'])
            return response
        except Exception as e:
            logger.error(f"Error uploading media: {str(e)}")
            return None
            
    async def upload_logo(self, logo_path: Path, style_name: str) -> Optional[str]:
        """Upload logo and cache its public_id."""
        try:
            # Check if we already have this logo uploaded
            style_key = style_name.lower()
            if style_key in self.uploaded_logos:
                logger.info(f"Using cached logo for style {style_name}")
                return self.uploaded_logos[style_key]

            logger.info(f"Uploading new logo for style {style_name}: {logo_path}")
            
            # Upload logo with specific settings
            logo_response = cloudinary.uploader.upload(
                str(logo_path),
                resource_type="image",
                public_id=f"logo_{style_key}",
                overwrite=True,
                unique_filename=False,
                use_filename=True,
                format="png",
                transformation=[
                    {"fetch_format": "auto"},
                    {"quality": "auto:best"}
                ]
            )
            
            if logo_response and 'public_id' in logo_response:
                # Cache the logo public_id
                self.uploaded_logos[style_key] = logo_response['public_id']
                logger.info(f"Logo uploaded successfully for {style_name}: {logo_response['public_id']}")
                return logo_response['public_id']
            else:
                logger.error(f"Logo upload failed: {logo_response}")
                return None
                
        except Exception as e:
            logger.error(f"Error uploading logo: {str(e)}")
            return None
            
    async def cleanup_resources(self):
        """Clean up temporary resources but preserve logos."""
        for resource_id in self.uploaded_resources:
            try:
                # Don't cleanup logo resources
                if not any(resource_id == logo_id for logo_id in self.uploaded_logos.values()):
                    cloudinary.uploader.destroy(resource_id)
                    logger.info(f"Cleaned up resource: {resource_id}")
            except Exception as e:
                logger.warning(f"Error cleaning up resource {resource_id}: {str(e)}")
        self.uploaded_resources = []
            
    async def generate_video(self, video_id: str, audio_id: str, output_path: Path, style_name: str = None) -> Optional[Path]:
        """
        Generate final video with optimized processing.
        
        Args:
            video_id: Public ID of uploaded video
            audio_id: Public ID of uploaded audio
            output_path: Path to save the final video
            style_name: Name of the commentary style used
            
        Returns:
            Path to generated video if successful, None otherwise
        """
        try:
            video = CloudinaryVideo(video_id)
            
            # Get video details
            details = cloudinary.api.resource(video_id, resource_type='video')
            width = details.get('width', 0)
            height = details.get('height', 0)
            
            logger.info(f"Processing video with style: {style_name}")
            logger.info(f"Video dimensions: {width}x{height}")
            
            # Calculate aspect ratio
            aspect_ratio = width / height if height else 0
            target_ratio = 9/16
            
            # Optimize transformations
            transformation = [
                {'quality': 'auto:good'},
                {'fetch_format': 'auto'}
            ]
            
            # Add padding only if needed
            if abs(aspect_ratio - target_ratio) > 0.01:
                logger.info(f"Adding vertical padding (ratio: {aspect_ratio:.2f}, target: {target_ratio:.2f})")
                target_height = int(width * (16/9))
                
                transformation.extend([
                    {
                        'width': width,
                        'height': target_height,
                        'crop': "pad",
                        'background': "white",
                        'y_padding': "auto",
                        'gravity': "center"
                    }
                ])
            
            # Add audio with optimized settings
            transformation.extend([
                {
                    'overlay': f"video:{audio_id}",
                    'resource_type': "video"
                },
                {
                    'flags': 'layer_apply',
                    'audio_codec': 'aac',
                    'bit_rate': '192k'
                }
            ])
            
            # Add style-specific logo if available
            if style_name:
                try:
                    # Look for logo in style-specific directory
                    logo_dir = Path(__file__).parent.parent / 'framesAndLogo' / style_name.capitalize()
                    logger.info(f"Looking for logo in directory: {logo_dir}")
                    
                    if not logo_dir.exists():
                        logger.warning(f"Logo directory does not exist: {logo_dir}")
                        raise FileNotFoundError(f"Logo directory not found: {logo_dir}")
                    
                    # Search for logo files with multiple patterns
                    logo_patterns = [
                        f"{style_name.lower()}logo.*",  # e.g., naturelogo.png
                        "logo.*",                       # e.g., logo.png
                        "*.png"                         # any png file
                    ]
                    
                    logo_path = None
                    for pattern in logo_patterns:
                        matches = list(logo_dir.glob(pattern))
                        if matches:
                            logo_path = matches[0]
                            logger.info(f"Found logo using pattern '{pattern}': {logo_path}")
                            break
                    
                    if logo_path and logo_path.exists():
                        # Upload or get cached logo
                        logo_public_id = await self.upload_logo(logo_path, style_name)
                        
                        if logo_public_id:
                            # Configure logo settings based on style
                            logo_settings = {
                                'nature': {
                                    'width': 120,
                                    'opacity': 85,
                                    'gravity': 'south_east',
                                    'x': 20,
                                    'y': 20,
                                    'effect': 'brightness:20'  # Slightly brighten logo
                                },
                                'news': {
                                    'width': 100,
                                    'opacity': 90,
                                    'gravity': 'north_east',
                                    'x': 15,
                                    'y': 15
                                },
                                'funny': {
                                    'width': 110,
                                    'opacity': 80,
                                    'gravity': 'south_west',
                                    'x': 20,
                                    'y': 20
                                },
                                'infographic': {
                                    'width': 130,
                                    'opacity': 95,
                                    'gravity': 'north_west',
                                    'x': 15,
                                    'y': 15
                                }
                            }
                            
                            # Get style-specific settings or use defaults
                            settings = logo_settings.get(style_name.lower(), {
                                'width': 100,
                                'opacity': 80,
                                'gravity': 'south_east',
                                'x': 20,
                                'y': 20
                            })
                            
                            # Add logo overlay transformation
                            logo_transform = {
                                'overlay': logo_public_id,  # Use cached logo public_id
                                'width': settings['width'],
                                'opacity': settings['opacity'],
                                'gravity': settings['gravity'],
                                'x': settings['x'],
                                'y': settings['y']
                            }
                            
                            # Add optional effect if present
                            if 'effect' in settings:
                                logo_transform['effect'] = settings['effect']
                            
                            transformation.extend([
                                logo_transform,
                                {'flags': 'layer_apply'}
                            ])
                            
                            logger.info(f"Added {style_name} logo transformation: {logo_transform}")
                        else:
                            logger.error("Failed to get logo public_id")
                    else:
                        logger.warning(f"No logo files found in {logo_dir} using patterns: {logo_patterns}")
                except Exception as e:
                    logger.error(f"Error adding {style_name} logo: {str(e)}", exc_info=True)
            
            # Log final transformation chain
            logger.info(f"Final transformation chain: {transformation}")
            
            # Generate optimized video URL
            video_url = video.build_url(
                transformation=transformation,
                resource_type='video',
                format='mp4',
                secure=True
            )
            
            logger.info(f"Generated video URL: {video_url}")
            
            # Download with streaming and chunking
            async with aiohttp.ClientSession() as session:
                async with session.get(video_url) as response:
                    if response.status == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(output_path, 'wb') as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)
                        logger.info(f"Video generated successfully: {output_path}")
                        return output_path
                    else:
                        logger.error(f"Error downloading video. Status: {response.status}, URL: {video_url}")
                        return None
                
        except Exception as e:
            logger.error(f"Error generating video: {str(e)}", exc_info=True)
            return None
        finally:
            await self.cleanup_resources()

async def execute_step(
    video_file: Path,
    audio_file: Path,
    output_dir: Path,
    style_name: str
) -> Optional[Path]:
    """
    Execute video generation step.
    
    Args:
        video_file: Path to the input video file
        audio_file: Path to the generated audio file
        output_dir: Directory to save generated video
        style_name: Name of the commentary style used
        
    Returns:
        Path to the generated video if successful, None otherwise
    """
    logger.debug("Step 6: Generating final video...")
    
    # Initialize video generator with Cloudinary credentials
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    
    if not all([cloud_name, api_key, api_secret]):
        logger.error("Missing Cloudinary credentials")
        return None
    
    generator = VideoGenerator(cloud_name, api_key, api_secret)
    
    try:
        # Upload video and audio
        video_response = await generator.upload_media(str(video_file), 'video')
        audio_response = await generator.upload_media(str(audio_file), 'video')  # Use video type for audio to support overlay
        
        if not video_response or not audio_response:
            return None
        
        # Generate final video
        output_file = output_dir / f"final_video_{style_name}.mp4"
        result = await generator.generate_video(
            video_response['public_id'],
            audio_response['public_id'],
            output_file,
            style_name
        )
        
        return result
    except Exception as e:
        logger.error(f"Error executing step: {str(e)}")
        return None 