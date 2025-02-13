"""
Step 4: Commentary generation module
Generates styled commentary based on frame analysis and content type
"""
import json
import logging
import os
import re
import random
from enum import Enum
from pathlib import Path
from typing import Dict, Optional, Tuple, List

from openai import OpenAI
from .prompts import PromptManager, LLMProvider, COMMENTARY_STYLES, SPEECH_PATTERNS

logger = logging.getLogger(__name__)

class ContentType(Enum):
    """Available content types for commentary."""
    NEWS = "news"
    FUNNY = "funny"
    NATURE = "nature"
    INFOGRAPHIC = "infographic"

class CommentaryGenerator:
    """Generates video commentary using OpenAI."""
    
    def __init__(self, content_type: ContentType):
        """
        Initialize commentary generator.
        
        Args:
            content_type: Type of content for commentary generation
        """
        self.content_type = content_type
        self.prompt_manager = PromptManager()
        
    def _build_system_prompt(self) -> str:
        """Build system prompt based on content type."""
        style = COMMENTARY_STYLES[self.content_type.value]
        return style["system_prompt"]

    def _build_prompt(self, analysis: Dict) -> str:
        """Build the prompt for commentary generation."""
        # Get video metadata
        video_text = analysis['metadata'].get('text', '')
        video_title = analysis['metadata'].get('title', '')
        video_description = analysis['metadata'].get('description', '')
        
        # Get vision analysis with enhanced validation
        vision_insights = {
            'objects': [],
            'labels': [],
            'descriptions': []
        }
        
        if 'frames' in analysis:
            # Track confidence scores for better object validation
            object_confidence = {}
            label_confidence = {}
            
            for frame in analysis['frames']:
                if 'google_vision' in frame:
                    # Aggregate objects with confidence tracking
                    for obj in frame['google_vision'].get('objects', []):
                        name = obj['name']
                        conf = obj['confidence']
                        area = obj.get('area', 0)
                        
                        if name not in object_confidence or conf > object_confidence[name]['confidence']:
                            object_confidence[name] = {
                                'confidence': conf,
                                'area': area,
                                'count': object_confidence.get(name, {}).get('count', 0) + 1
                            }
                    
                    # Aggregate labels with confidence tracking
                    for label in frame['google_vision'].get('labels', []):
                        desc = label['description']
                        conf = label['confidence']
                        
                        if desc not in label_confidence or conf > label_confidence[desc]:
                            label_confidence[desc] = conf
                
                if 'openai_vision' in frame:
                    desc = frame['openai_vision'].get('detailed_description', '')
                    if desc:
                        vision_insights['descriptions'].append(desc)
            
            # Filter and sort objects by confidence and frequency
            vision_insights['objects'] = [
                {
                    'name': name,
                    'confidence': data['confidence'],
                    'area': data['area'],
                    'frequency': data['count']
                }
                for name, data in object_confidence.items()
                if data['confidence'] >= 0.7 and data['count'] >= 2  # Require multiple detections
            ]
            vision_insights['objects'].sort(key=lambda x: (x['frequency'], x['confidence'], x['area']), reverse=True)
            
            # Filter and sort labels by confidence
            vision_insights['labels'] = [
                {'description': desc, 'confidence': conf}
                for desc, conf in label_confidence.items()
                if conf >= 0.7
            ]
            vision_insights['labels'].sort(key=lambda x: x['confidence'], reverse=True)
        
        # Build content text with enhanced analysis
        content_text = "VIDEO CONTENT:\n"
        if video_title:
            content_text += f"Title: {video_title}\n"
        if video_description:
            content_text += f"Description: {video_description}\n"
        if video_text:
            content_text += f"Text: {video_text}\n"
            
        content_text += "\nVISUAL ANALYSIS:\n"
        
        if vision_insights['objects']:
            content_text += "\nMain subjects detected (with confidence and frequency):\n"
            for obj in vision_insights['objects'][:5]:  # Focus on top 5 most confident/frequent objects
                content_text += f"- {obj['name']} (confidence: {obj['confidence']:.2f}, seen {obj['frequency']} times)\n"
        
        if vision_insights['labels']:
            content_text += "\nKey visual elements (with confidence):\n"
            for label in vision_insights['labels'][:8]:  # Include more relevant labels
                content_text += f"- {label['description']} ({label['confidence']:.2f})\n"
        
        if vision_insights['descriptions']:
            content_text += "\nDetailed scene descriptions:\n"
            for desc in vision_insights['descriptions'][:2]:  # Include top 2 most detailed descriptions
                content_text += f"- {desc}\n"
        
        selected_language = analysis['metadata'].get('language', 'en')
        
        base_prompt = f"""Generate a VERY SHORT {selected_language.upper()} commentary (1-2 lines maximum) for this video in {self.content_type.value} style.

{content_text}

STRICT REQUIREMENTS:
1. MUST be 1-2 lines only - no exceptions
2. Focus on combining the video description with what is actually shown in the video
3. If there is text in the video, incorporate it naturally
4. Match the {self.content_type.value} style while staying extremely brief
5. Make it engaging but concise
6. Format for {selected_language}
7. Ensure commentary reflects both visual content and video description
8. Correct any obvious errors in object detection (e.g., if a deer was labeled as a dog)"""

        if selected_language == 'ur':
            base_prompt += """
9. Use proper Urdu script and punctuation (۔، ؟)"""

        return base_prompt

    def _process_response(self, text: str, language: str) -> str:
        """Process and clean the generated commentary."""
        # Remove stars, markdown formatting and other special characters
        text = re.sub(r'[*_#`]', '', text)  # Remove markdown formatting
        text = re.sub(r'^\s*[*-]\s*', '', text, flags=re.MULTILINE)  # Remove list markers
        text = ''.join(char for char in text if char.isprintable() or char.isspace())
        
        # Add appropriate pauses and formatting based on language
        if language == 'ur':
            text = text.replace('۔', '۔<break time="1s"/>')
            text = text.replace('،', '،<break time="0.5s"/>')
        else:
            text = text.replace('. ', '... ')
            text = text.replace('! ', '... ')
            text = text.replace('? ', '... ')
        
        return text.strip()

    async def generate_commentary(self, analysis_file: Path, output_file: Path) -> Optional[Dict]:
        """Generate commentary from analysis results."""
        try:
            # Load analysis
            with open(analysis_file, encoding='utf-8') as f:
                analysis = json.load(f)

            # Log the video text from metadata
            video_text = analysis['metadata'].get('text', '')
            logger.info("\n=== VIDEO TEXT FROM METADATA ===")
            logger.info(video_text if video_text else "No text found in metadata")
            
            # Build messages for the API call
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_prompt(analysis)
            
            # Log prompts
            logger.info("\n=== SYSTEM PROMPT ===")
            logger.info(system_prompt)
            logger.info("\n=== USER PROMPT ===")
            logger.info(user_prompt)
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            try:
                # Generate commentary using the prompt manager
                logger.info("\n=== GENERATING COMMENTARY ===")
                commentary_text = self.prompt_manager.generate_response(
                    messages=messages,
                    model="gpt-4o-mini",
                    temperature=0.7,
                    max_tokens=500
                )
                
                logger.info("\n=== RAW GENERATED COMMENTARY ===")
                logger.info(commentary_text)
                
                if not commentary_text:
                    logger.error("Empty response from API")
                    return None

                # Process the generated text
                language = analysis['metadata'].get('language', 'en')
                processed_text = self._process_response(commentary_text, language)
                
                logger.info("\n=== PROCESSED COMMENTARY ===")
                logger.info(processed_text)

                # Create commentary object
                commentary = {
                    "style": self.content_type.value,
                    "commentary": processed_text,
                    "metadata": analysis['metadata'],
                    "language": language
                }

                # Log final output
                logger.info("\n=== FINAL COMMENTARY OBJECT ===")
                logger.info(json.dumps(commentary, indent=2, ensure_ascii=False))

                # Save commentary
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(commentary, f, indent=2, ensure_ascii=False)

                return commentary

            except Exception as api_error:
                logger.error(f"API error: {str(api_error)}")
                return None

        except Exception as e:
            logger.error(f"Error generating commentary: {str(e)}")
            return None

    def _analyze_scene_sequence(self, frames: List[Dict]) -> Dict:
        """
        Analyze the sequence of scenes to identify narrative patterns.
        
        Args:
            frames: List of frame analysis dictionaries
            
        Returns:
            Dictionary containing scene sequence analysis
        """
        sequence = {
            "timeline": [],
            "key_objects": [],
            "recurring_elements": [],
            "scene_transitions": []
        }

        # Track unique objects and elements using dictionaries
        unique_objects = {}
        recurring_objects = {}

        for frame in frames:
            timestamp = float(frame['timestamp'])
            
            # Track objects and elements
            if 'google_vision' in frame:
                frame_objects = []
                for obj in frame['google_vision'].get('objects', []):
                    name = obj['name']
                    frame_objects.append(name)
                    if name not in unique_objects:
                        unique_objects[name] = obj
                    elif name in unique_objects and name not in recurring_objects:
                        recurring_objects[name] = obj
            
            # Track scene transitions
            if len(sequence['timeline']) > 0:
                prev_time = sequence['timeline'][-1]['timestamp']
                if timestamp - prev_time > 2.0:  # Significant time gap
                    sequence['scene_transitions'].append(timestamp)
            
            sequence['timeline'].append({
                'timestamp': timestamp,
                'objects': frame_objects if 'google_vision' in frame else [],
                'description': frame.get('openai_vision', {}).get('detailed_description', '')
            })
        
        # Convert tracked objects to lists
        sequence['key_objects'] = list(unique_objects.keys())
        sequence['recurring_elements'] = list(recurring_objects.keys())
        
        return sequence

    def _estimate_speech_duration(self, text: str, language: str = 'en') -> float:
        """
        Estimate the duration of speech in seconds.
        Different languages have different speaking rates.
        
        Args:
            text: Text to estimate duration for
            language: Language of the text
            
        Returns:
            Estimated duration in seconds
        """
        # Words per minute rates for different languages
        WPM_RATES = {
            'en': 150,  # English: ~150 words per minute
            'ur': 120   # Urdu: ~120 words per minute (slower due to formal speech)
        }
        
        words = len(text.split())
        rate = WPM_RATES.get(language, 150)
        return (words / rate) * 60  # Convert from minutes to seconds

    def _build_narration_prompt(self, analysis: Dict, sequence: Dict) -> str:
        """Build a prompt specifically for generating narration-friendly commentary."""
        video_duration = float(analysis['metadata'].get('duration', 0))
        video_title = analysis['metadata'].get('title', '')
        video_description = analysis['metadata'].get('description', '')
        selected_language = analysis['metadata'].get('language', 'en')
        
        # Target shorter duration to ensure final audio fits
        target_duration = max(video_duration * 0.8, video_duration - 2)
        
        # Calculate target words based on language-specific speaking rate
        words_per_minute = 120 if selected_language == 'ur' else 150
        target_words = int((target_duration / 60) * words_per_minute)
        
        prompt = f"""Create engaging commentary for this specific video content:

CONTENT TO NARRATE:
Title: {video_title}
Description: {video_description}

STRICT DURATION CONSTRAINTS:
- Video Duration: {video_duration:.1f} seconds
- Target Duration: {target_duration:.1f} seconds
- Maximum Words: {target_words} words
- DO NOT EXCEED these limits!

KEY REQUIREMENTS:
1. Keep commentary SHORTER than video duration
2. Use the video's own text/description as PRIMARY source
3. Match commentary style to content theme
4. Reference specific details from video
5. Create natural transitions between topics
6. Vary tone based on content
7. Maintain authenticity and engagement

CONTENT-SPECIFIC GUIDELINES:
- Focus on the unique aspects of this video
- Use terminology from the video's text
- Create emotional connections where appropriate
- Balance information with engagement
- Adapt pacing to content intensity"""

        # Add style-specific voice instructions
        if self.content_type == ContentType.NEWS:
            prompt += """

NEWS APPROACH:
- Present information objectively
- Follow news reporting structure
- Use formal journalistic language
- Maintain credibility and authority
- Emphasize key facts and developments"""

        elif self.content_type == ContentType.FUNNY:
            prompt += """

FUNNY APPROACH:
- Use witty observations and jokes
- Maintain light and playful tone
- Include appropriate humor
- Emphasize amusing moments
- Keep engagement through humor"""

        elif self.content_type == ContentType.NATURE:
            prompt += """

NATURE APPROACH:
- Use descriptive, vivid language
- Convey wonder and appreciation
- Include scientific observations
- Maintain a sense of discovery
- Balance education with entertainment"""

        elif self.content_type == ContentType.INFOGRAPHIC:
            prompt += """

INFOGRAPHIC APPROACH:
- Explain complex information simply
- Highlight key data points
- Use clear, precise language
- Maintain educational focus
- Guide through visual information"""

        elif self.content_type == ContentType.URDU:
            prompt += f"""

URDU NARRATION REQUIREMENTS:
1. Maximum Duration: {target_duration:.1f} seconds
2. Maximum Words: {target_words} words
3. Use authentic Urdu expressions and idioms
4. Adapt formality based on content:
   - Use formal Urdu for serious topics
   - Use conversational Urdu for casual content
   - Balance between poetic and plain language
5. Cultural Considerations:
   - Incorporate culturally relevant metaphors
   - Use appropriate honorifics
   - Maintain cultural sensitivity
6. Language Structure:
   - Use proper Urdu sentence structure
   - Include natural pauses and emphasis
   - Incorporate poetic elements when suitable
7. Expression Guidelines:
   - Start with engaging phrases like "دیکھیے", "ملاحظہ کیجیے"
   - Use emotional expressions like "واہ واہ", "سبحان اللہ"
   - Include rhetorical questions for engagement
   - End with impactful conclusions
8. Tone Variations:
   - Serious: "قابل غور بات یہ ہے کہ..."
   - Excited: "کیا خوبصورت منظر ہے..."
   - Analytical: "غور کیجیے کہ..."
   - Narrative: "کہانی یوں ہے کہ..."
9. Example Structures:
   - Opening: "دیکھیے کیسے..."
   - Transition: "اس کے بعد..."
   - Emphasis: "خاص طور پر..."
   - Conclusion: "یوں یہ منظر..."
"""

        return prompt
    
    def _validate_urdu_text(self, text: str) -> bool:
        """
        Validate Urdu text to ensure it's properly formatted.
        
        Args:
            text: Text to validate
            
        Returns:
            bool: True if text is valid Urdu, False otherwise
        """
        # Check for Urdu Unicode range (0600-06FF)
        urdu_chars = len([c for c in text if '\u0600' <= c <= '\u06FF'])
        total_chars = len(''.join(text.split()))  # Exclude whitespace
        
        # Text should be predominantly Urdu (>80%)
        if urdu_chars / total_chars < 0.8:
            logger.warning(f"Text may not be proper Urdu. Urdu character ratio: {urdu_chars/total_chars:.2f}")
            return False
        
        # Check for common Urdu punctuation marks
        urdu_punctuation = ['۔', '،', '؟', '!']
        has_urdu_punctuation = any(mark in text for mark in urdu_punctuation)
        
        if not has_urdu_punctuation:
            logger.warning("Text lacks Urdu punctuation marks")
            return False
            
        return True

    def _validate_english_text(self, text: str) -> bool:
        """
        Validate English text to ensure it's properly formatted.
        
        Args:
            text: Text to validate
            
        Returns:
            bool: True if text is valid English, False otherwise
        """
        # Check for English characters (basic Latin alphabet)
        english_chars = len([c for c in text if c.isascii() and (c.isalpha() or c.isspace() or c in '.,!?\'"-')])
        total_chars = len(text)
        
        # Text should be predominantly English (>80%)
        if english_chars / total_chars < 0.8:
            logger.warning(f"Text may not be proper English. English character ratio: {english_chars/total_chars:.2f}")
            return False
        
        # Check for proper sentence structure
        sentences = [s.strip() for s in text.split('.') if s.strip()]
        if not sentences:
            logger.warning("Text lacks proper sentence structure")
            return False
        
        # Check for basic punctuation
        has_punctuation = any(mark in text for mark in ['.', ',', '!', '?'])
        if not has_punctuation:
            logger.warning("Text lacks proper punctuation")
            return False
        
        return True

    def _add_narration_tags(self, text: str, language: str) -> str:
        """
        Add appropriate narration tags based on language.
        
        Args:
            text: Text to enhance
            language: Language of the text
            
        Returns:
            str: Enhanced text with appropriate tags
        """
        if language == 'ur':
            # For Urdu, we'll use specific SSML tags that work well with the Urdu voice
            text = text.replace('۔', '۔<break time="1s"/>')
            text = text.replace('،', '،<break time="0.5s"/>')
            text = text.replace('!', '!<break time="0.8s"/>')
            text = text.replace('؟', '؟<break time="0.8s"/>')
            
            # Add prosody for better Urdu pacing
            text = f'<prosody rate="1.2" pitch="+2st">{text}</prosody>'
            
            # Add language tag
            text = f'<lang xml:lang="ur-PK">{text}</lang>'
            
        else:
            # For English, we'll keep it simple since the voice doesn't support complex SSML
            # Just add basic punctuation pauses
            text = text.replace('. ', '... ')
            text = text.replace('! ', '... ')
            text = text.replace('? ', '... ')
            text = text.replace(', ', ', ')
            
            # Clean any emojis or special characters
            text = ''.join(char for char in text if char.isprintable() or char.isspace())
            
        return text

    def _analyze_text_for_narration(self, text: str, language: str) -> Tuple[bool, str]:
        """
        Analyze text for audio narration compatibility.
        """
        try:
            logger.info("=== Original Text ===")
            logger.info(language)
            logger.info(text)
            
            # Remove any control characters
            cleaned_text = ''.join(char for char in text if char.isprintable() or char.isspace())
            
            logger.info("\n=== After Control Character Removal ===")
            logger.info(cleaned_text)
            
            # Basic validation
            if not cleaned_text.strip():
                return False, "Empty text after cleaning"
            
            # Language-specific checks
            if language == 'ur':
                # Validate Urdu text
                if not self._validate_urdu_text(cleaned_text):
                    return False, "Invalid Urdu text format"
                
                # Add appropriate breaks and formatting for Urdu
                cleaned_text = self._add_narration_tags(cleaned_text, 'ur')
                
                logger.info("\n=== After Urdu Formatting ===")
                logger.info(cleaned_text)
                
            else:  # English
                # Validate English text
                if not self._validate_english_text(cleaned_text):
                    return False, "Invalid English text format"
                
                # Add appropriate formatting for English
                cleaned_text = self._add_narration_tags(cleaned_text, 'en')
                
                logger.info("\n=== After English Formatting ===")
                logger.info(cleaned_text)
            
            logger.info("\n=== Final Text for Audio Generation ===")
            logger.info(cleaned_text)
            logger.info("=== End of Text Processing ===\n")
            
            return True, cleaned_text
            
        except Exception as e:
            logger.error(f"Error analyzing text for narration: {e}")
            return False, str(e)

    def _format_vision_insights(self, insights: List[Dict]) -> str:
        """Format vision insights for the prompt."""
        formatted = []
        for insight in insights:
            timestamp = insight['timestamp']
            if 'objects' in insight and insight['objects']:
                formatted.append(f"Time {timestamp}s - Objects: {', '.join(insight['objects'])}")
            if 'text' in insight and insight['text']:
                formatted.append(f"Time {timestamp}s - Text: {insight['text']}")
            if 'description' in insight and insight['description']:
                formatted.append(f"Time {timestamp}s - Scene: {insight['description']}")
        return "\n".join(formatted)

    def format_for_audio(self, commentary: Dict) -> str:
        """
        Format commentary for text-to-speech with content-type-specific patterns.
        
        Args:
            commentary: Generated commentary dictionary
            
        Returns:
            Formatted text suitable for audio generation
        """
        text = commentary['commentary']
        
        # Remove emojis and special characters
        text = re.sub(r'[^\w\s,.!?;:()\-\'\"]+', '', text)  # Keep only basic punctuation
        text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
        
        # Get content-specific speech patterns
        content_config = SPEECH_PATTERNS[self.content_type.value]
        
        # Add natural speech patterns and pauses
        sentences = text.split('.')
        enhanced_sentences = []
        
        for i, sentence in enumerate(sentences):
            if not sentence.strip():
                continue
                
            sentence = sentence.strip()
            
            # Add style-specific fillers at the start of some sentences
            if i > 0 and random.random() < 0.3:
                sentence = random.choice(content_config['fillers']) + ' ' + sentence
            
            # Add transitions between ideas
            if i > 1 and random.random() < 0.25:
                sentence = random.choice(content_config['transitions']) + ' ' + sentence
            
            # Add emphasis words
            if random.random() < 0.2:
                emphasis = random.choice(content_config['emphasis'])
                words = sentence.split()
                if len(words) > 4:
                    insert_pos = random.randint(2, len(words) - 2)
                    words.insert(insert_pos, emphasis)
                    sentence = ' '.join(words)
            
            # Add thoughtful pauses based on style
            if len(sentence.split()) > 6 and random.random() < content_config['pause_frequency']:
                words = sentence.split()
                mid = len(words) // 2
                words.insert(mid, '<break time="0.2s"/>')
                sentence = ' '.join(words)
            
            enhanced_sentences.append(sentence)
        
        # Join sentences with appropriate pauses
        text = '. '.join(enhanced_sentences)
        
        # Add final formatting and pauses
        text = re.sub(r'([,;])\s', r'\1 <break time="0.2s"/> ', text)  # Short pauses
        text = re.sub(r'([.!?])\s', r'\1 <break time="0.4s"/> ', text)  # Medium pauses
        text = re.sub(r'\.\.\.\s', '... <break time="0.3s"/> ', text)  # Thoughtful pauses
        
        # Add natural variations in pace
        text = re.sub(r'(!)\s', r'\1 <break time="0.2s"/> ', text)  # Quick pauses after excitement
        text = re.sub(r'(\?)\s', r'\1 <break time="0.3s"/> ', text)  # Questioning pauses
        
        # Add occasional emphasis for important words
        for emphasis in content_config['emphasis']:
            text = re.sub(f'\\b{emphasis}\\b', f'<emphasis level="strong">{emphasis}</emphasis>', text)
        
        # Clean up any duplicate breaks or spaces
        text = re.sub(r'\s*<break[^>]+>\s*<break[^>]+>\s*', ' <break time="0.4s"/> ', text)
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()

def process_for_audio(commentary: str, language: str = 'en') -> str:
    """
    Process commentary text for audio narration.
    
    Args:
        commentary: Text to process
        language: Language of the text ('en' or 'ur')
    """
    try:
        # Remove any non-printable characters first
        script = ''.join(char for char in commentary if char.isprintable() or char.isspace())
        
        if language == 'ur':
            # For Urdu text, keep Urdu characters and basic punctuation
            # Keep Urdu Unicode ranges and Urdu punctuation
            allowed_chars = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF\s۔،؟!]')
            script = ''.join(c for c in script if allowed_chars.match(c))
            
            # Add SSML pauses for Urdu punctuation
            script = script.replace('۔', '۔<break time="1s"/>')
            script = script.replace('،', '،<break time="0.5s"/>')
            script = script.replace('؟', '؟<break time="0.8s"/>')
            
        else:  # English
            # For English text, keep only ASCII characters and basic punctuation
            script = re.sub(r'[*_#`~]', '', script)  # Remove markdown symbols
            script = re.sub(r'[^\x00-\x7F]+', '', script)  # Remove non-ASCII
            script = re.sub(r'[^\w\s.,!?;:()\-\'\"]+', ' ', script)  # Keep basic punctuation
            
            # Add pauses for English punctuation
            script = script.replace('. ', '... ').replace('! ', '... ').replace('? ', '... ')
        
        # Normalize whitespace for both languages
        script = re.sub(r'\s+', ' ', script)
        
        return script.strip()
        
    except Exception as e:
        logger.error(f"Error processing text for audio: {str(e)}")
        return commentary.strip()

async def execute_step(frames_info: dict, output_dir: Path, content_type: str) -> str:
    """Generate commentary based on video analysis and content type."""
    analysis_file = output_dir / "final_analysis.json"
    commentary_file = output_dir / f"commentary_{content_type}.json"
    
    try:
        logger.info("\n=== STARTING COMMENTARY GENERATION ===")
        logger.info(f"Content Type: {content_type}")
        logger.info(f"Analysis File: {analysis_file}")
        
        # Save analysis
        with open(analysis_file, 'w', encoding='utf-8') as f:
            json.dump(frames_info, f, indent=2)
        
        # Generate commentary
        content = ContentType[content_type.upper()]
        generator = CommentaryGenerator(content)
        commentary = await generator.generate_commentary(analysis_file, commentary_file)
        
        if not commentary:
            raise ValueError("Failed to generate commentary")
        
        # Process for audio with correct language
        language = frames_info['metadata'].get('language', 'en')
        logger.info("\n=== PROCESSING FOR AUDIO ===")
        logger.info(f"Language: {language}")
        
        audio_script = process_for_audio(commentary['commentary'], language)
        logger.info("\n=== FINAL AUDIO SCRIPT ===")
        logger.info(audio_script)
        
        # Save result
        with open(commentary_file, 'w', encoding='utf-8') as f:
            json.dump(commentary, f, indent=2)
        
        return audio_script
    except Exception as e:
        logger.error(f"Error generating commentary: {str(e)}")
        raise
