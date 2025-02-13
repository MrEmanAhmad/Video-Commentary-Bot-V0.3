"""
Step 7: Cleanup module
Performs thorough cleanup of all temporary files, directories and cloud resources
"""

import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional, Union
import cloudinary
import cloudinary.uploader
import cloudinary.api

logger = logging.getLogger(__name__)

def cleanup_workspace(output_dir: Union[str, Path], keep_files: Optional[List[str]] = None) -> None:
    """Clean up workspace completely, keeping no files by default."""
    output_dir = Path(output_dir)
    
    try:
        # Delete all files in the directory and subdirectories
        for item in output_dir.glob("**/*"):
            if item.is_file():
                if keep_files and item.name in keep_files:
                    continue
                try:
                    item.unlink()
                    logger.info(f"Deleted file: {item}")
                except Exception as e:
                    logger.warning(f"Could not delete {item}: {e}")
    
        # Remove all empty directories
        for item in sorted(output_dir.glob("**/*"), reverse=True):
            if item.is_dir():
                try:
                    item.rmdir()
                    logger.info(f"Removed directory: {item}")
                except Exception as e:
                    logger.warning(f"Could not remove directory {item}: {e}")
                    
        # Finally remove the output directory itself if empty
        try:
            if not any(output_dir.iterdir()):
                output_dir.rmdir()
                logger.info(f"Removed empty output directory: {output_dir}")
        except Exception as e:
            logger.warning(f"Could not remove output directory {output_dir}: {e}")
            
    except Exception as e:
        logger.error(f"Error during workspace cleanup: {e}")

def cleanup_cloudinary_resources(prefix: str) -> None:
    """Clean up all Cloudinary resources with the given prefix."""
    try:
        # Get all resources with the prefix
        result = cloudinary.api.resources(type="upload", prefix=prefix)
        for resource in result.get("resources", []):
            try:
                cloudinary.uploader.destroy(resource["public_id"])
                logger.info(f"Deleted Cloudinary resource: {resource['public_id']}")
            except Exception as e:
                logger.warning(f"Could not delete Cloudinary resource {resource['public_id']}: {e}")
    except Exception as e:
        logger.error(f"Error cleaning up Cloudinary resources: {e}")

def execute_step(output_dir: Path, style_name: str, keep_files: Optional[List[str]] = None) -> None:
    """
    Execute cleanup step.
    
    Args:
        output_dir: Directory to clean up
        style_name: Name of the commentary style used
        keep_files: List of filenames to keep (optional)
    """
    logger.info("Step 7: Starting thorough cleanup...")
    
    try:
        # Clean up Cloudinary resources first
        cleanup_cloudinary_resources(str(output_dir.name))
        
        # Clean up local workspace
        cleanup_workspace(output_dir, keep_files)
        
        logger.info("Cleanup completed successfully")
        
    except Exception as e:
        logger.error(f"Error during cleanup step: {e}")
        raise 