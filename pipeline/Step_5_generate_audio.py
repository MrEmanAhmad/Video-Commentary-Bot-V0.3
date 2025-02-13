"""
Step 5: Audio generation module
Generates audio from commentary using Google Cloud TTS
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, List
from google.cloud import texttospeech
import json
import re

logger = logging.getLogger(__name__)

class AudioGenerator:
    """Handles audio generation using Google Cloud Text-to-Speech."""
    
    def __init__(self, google_credentials_path: str):
        """
        Initialize the AudioGenerator with Google Cloud credentials.
        
        Args:
            google_credentials_path: Path to Google Cloud credentials JSON file
        """
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = google_credentials_path
        self.client = texttospeech.TextToSpeechClient()
        
    def list_english_voices(self) -> List[Dict]:
        """List all available English voices."""
        voices = self.client.list_voices().voices
        english_voices = []
        for voice in voices:
            if any(language_code.startswith('en-') for language_code in voice.language_codes):
                english_voices.append({
                    'name': voice.name,
                    'language_codes': voice.language_codes,
                    'ssml_gender': texttospeech.SsmlVoiceGender(voice.ssml_gender).name,
                    'natural_sample_rate_hertz': voice.natural_sample_rate_hertz
                })
        return english_voices
        
    async def generate_audio(self, text: str, output_path: Path, target_duration: float, is_urdu: bool = False) -> Optional[Path]:
        """
        Generate audio from text using specified voice parameters.
        
        Args:
            text: Text to convert to speech
            output_path: Path where the audio file should be saved
            target_duration: Target duration in seconds
            is_urdu: Whether the text is in Urdu
            
        Returns:
            Path to the generated audio file if successful, None otherwise
        """
        try:
            # Create the parent directory if it doesn't exist
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # For Urdu text, wrap in SSML with prosody settings
            if is_urdu:
                ssml_text = f"""
                <speak>
                    <prosody rate="1.0" pitch="+0st">
                    {text}
                    </prosody>
                </speak>
                """
                synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
            else:
                synthesis_input = texttospeech.SynthesisInput(text=text)
            
            # Configure the voice
            if is_urdu:
                voice = texttospeech.VoiceSelectionParams(
                    language_code="ur-PK",
                    ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
                )
            else:
                voice = texttospeech.VoiceSelectionParams(
                    language_code='en-GB',
                    name='en-GB-Journey-O'
                )
            
            # Configure the audio output
            audio_config = texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                effects_profile_id=["headphone-class-device"] if is_urdu else None
            )
            
            # Perform the text-to-speech request
            logger.info(f"Generating audio for text: {text[:100]}...")
            response = self.client.synthesize_speech(
                input=synthesis_input,
                voice=voice,
                audio_config=audio_config
            )
            
            # Write the audio content to file
            with open(output_path, "wb") as out:
                out.write(response.audio_content)
                
            logger.info(f"Successfully generated audio file: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error generating audio: {str(e)}")
            return None

def generate_urdu_audio(text: str, output_path: str) -> bool:
    """Generate audio for Urdu text using appropriate SSML and voice settings."""
    try:
        client = texttospeech.TextToSpeechClient()
        
        # Clean the text and wrap in proper SSML
        clean_text = text.replace('<prosody rate="medium" pitch="medium">', '')
        clean_text = clean_text.replace('</prosody>', '')
        clean_text = clean_text.replace('<lang xml:lang="ur-PK">', '')
        clean_text = clean_text.replace('</lang>', '')
        
        ssml_text = f"""
        <speak>
            <prosody rate="1.2" pitch="+2st">
                {clean_text}
            </prosody>
        </speak>
        """
        
        synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
        
        voice = texttospeech.VoiceSelectionParams(
            language_code="ur-PK",
            ssml_gender=texttospeech.SsmlVoiceGender.FEMALE
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            effects_profile_id=["headphone-class-device"]
        )
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
            
        return True
        
    except Exception as e:
        logger.error(f"Error generating Urdu audio: {str(e)}")
        return False

def generate_english_audio(text: str, output_path: str) -> bool:
    """Generate audio for English text using appropriate voice settings."""
    try:
        client = texttospeech.TextToSpeechClient()
        
        # Clean text of any SSML tags
        clean_text = text.replace('<prosody rate="medium" pitch="medium">', '')
        clean_text = clean_text.replace('</prosody>', '')
        clean_text = clean_text.replace('<lang xml:lang="en-US">', '')
        clean_text = clean_text.replace('</lang>', '')
        clean_text = clean_text.replace('<break time="0.3s"/>', '')
        clean_text = clean_text.replace('<break time="1s"/>', '')
        
        synthesis_input = texttospeech.SynthesisInput(text=clean_text)
        
        voice = texttospeech.VoiceSelectionParams(
            language_code="en-US",
            name="en-US-Neural2-F"  # Using a specific neural voice for better quality
        )
        
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            speaking_rate=1.0,
            pitch=0.0,
            effects_profile_id=["headphone-class-device"]
        )
        
        response = client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
            
        return True
        
    except Exception as e:
        logger.error(f"Error generating English audio: {str(e)}")
        return False

async def execute_step(frames_info: dict, output_dir: Path, style: str = None) -> str:
    """
    Generate audio from commentary text.
    
    Args:
        frames_info: Dictionary containing frame analysis and commentary
        output_dir: Directory to save output files
        style: Commentary style (optional)
        
    Returns:
        Path to generated audio file
    """
    try:
        # Load commentary
        style = style or frames_info['metadata'].get('style', 'documentary')
        commentary_file = output_dir / f"commentary_{style}.json"
        with open(commentary_file, encoding='utf-8') as f:
            commentary = json.load(f)
        
        # Get text and language
        text = commentary['commentary']
        language = commentary.get('language', 'en')
        
        logger.info(f"Generating audio for text: {text[:100]}...")
        
        # Generate audio file path
        audio_file = output_dir / f"commentary_{style}.wav"
        
        # Generate audio based on language
        success = generate_urdu_audio(text, str(audio_file)) if language == 'ur' else generate_english_audio(text, str(audio_file))
        
        if success:
            logger.info(f"Successfully generated audio file: {audio_file}")
            return str(audio_file)
        else:
            raise Exception("Failed to generate audio")
            
    except Exception as e:
        logger.error(f"Error in audio generation: {str(e)}")
        raise 