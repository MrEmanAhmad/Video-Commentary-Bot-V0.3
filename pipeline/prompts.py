"""
Module for managing prompts and LLM model selection.
"""

from enum import Enum
from typing import Dict, Optional, Any
import os
from openai import OpenAI, OpenAIError
import requests
import logging

logger = logging.getLogger(__name__)

class LLMProvider(Enum):
    """Available LLM providers."""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"

class PromptTemplate:
    """Class to manage prompt templates."""
    def __init__(self, template: str, provider_specific_params: Optional[Dict[str, Any]] = None):
        self.template = template
        self.provider_specific_params = provider_specific_params or {}

class PromptManager:
    """Manager for handling prompts and LLM interactions."""
    
    def __init__(self, provider: LLMProvider = LLMProvider.OPENAI):
        """Initialize the prompt manager with a specific provider."""
        self.provider = provider
        self.client = None
        self._setup_client()
        
    def _setup_client(self):
        """Setup the appropriate client based on provider."""
        try:
            if self.provider == LLMProvider.OPENAI:
                self.client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
            elif self.provider == LLMProvider.DEEPSEEK:
                self.client = OpenAI(
                    api_key=os.getenv('DEEPSEEK_API_KEY'),
                    base_url="https://api.deepseek.com/v1"
                )
        except Exception as e:
            logger.error(f"Error setting up {self.provider.value} client: {str(e)}")
            raise

    def generate_response(self, messages: list, model: str = "gpt-4o-mini", **kwargs) -> str:
        """Generate response using the selected provider."""
        try:
            if not self.client:
                raise ValueError(f"{self.provider.value} client not initialized")

            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            raise

# Commentary style templates
COMMENTARY_STYLES = {
    "news": {
        "system_prompt": """You are a professional news commentator. Create clear, objective commentary that:
- Uses formal journalistic language
- Presents information objectively
- Follows news reporting structure
- Maintains credibility and authority
- Emphasizes key facts and developments""",
        "example": "Breaking news: In a remarkable development..."
    },
    "funny": {
        "system_prompt": """You are an entertaining commentator. Create humorous commentary that:
- Uses witty observations and jokes
- Maintains light and playful tone
- Includes appropriate humor
- Emphasizes amusing moments
- Keeps engagement through humor""",
        "example": "Oh my goodness, you won't believe what happens next..."
    },
    "nature": {
        "system_prompt": """You are a nature documentary narrator. Create descriptive commentary that:
- Uses vivid, descriptive language
- Conveys wonder and appreciation
- Includes scientific observations
- Maintains a sense of discovery
- Balances education with entertainment""",
        "example": "Watch as this magnificent creature..."
    },
    "infographic": {
        "system_prompt": """You are an educational content expert. Create informative commentary that:
- Explains complex information simply
- Highlights key data points
- Uses clear, precise language
- Maintains educational focus
- Guides through visual information""",
        "example": "Let's break down these important numbers..."
    },
    "urdu": {
        "system_prompt": """You are a culturally-aware Urdu commentator. Create commentary that:
- Uses natural, flowing Urdu expressions
- Adapts tone to content formality
- Incorporates poetic elements when suitable
- Maintains cultural sensitivity
- Balances formal and casual language""",
        "example": "دیکھیے کیسے یہ خوبصورت منظر..."
    }
}

# Speech patterns for different styles
SPEECH_PATTERNS = {
    "news": {
        "fillers": ["Breaking news...", "In this development...", "We're reporting...", "Sources confirm..."],
        "transitions": ["Furthermore...", "In addition...", "Moving to our next point..."],
        "emphasis": ["critically", "significantly", "notably", "exclusively"],
        "pause_frequency": 0.3
    },
    "funny": {
        "fillers": ["Get this...", "You'll love this...", "Here's the funny part...", "Wait for it..."],
        "transitions": ["But that's not all...", "It gets better...", "Here's the best part..."],
        "emphasis": ["hilarious", "absolutely", "totally", "literally"],
        "pause_frequency": 0.2
    },
    "nature": {
        "fillers": ["Observe...", "Remarkably...", "Fascinatingly...", "In nature..."],
        "transitions": ["Meanwhile...", "As we watch...", "In this habitat..."],
        "emphasis": ["extraordinary", "magnificent", "remarkable", "fascinating"],
        "pause_frequency": 0.4
    },
    "infographic": {
        "fillers": ["Let's analyze...", "Notice here...", "This data shows...", "Looking at these numbers..."],
        "transitions": ["Next we see...", "This leads to...", "The data indicates..."],
        "emphasis": ["significantly", "precisely", "clearly", "effectively"],
        "pause_frequency": 0.5
    },
    "urdu": {
        "fillers": ["دیکھیں...", "ارے واہ...", "سنیں تو...", "کیا بات ہے..."],
        "transitions": ["اور پھر...", "اس کے بعد...", "سب سے اچھی بات..."],
        "emphasis": ["بالکل", "یقیناً", "واقعی", "بےحد"],
        "pause_frequency": 0.3
    }
}

# Define prompt templates
COMMENTARY_PROMPTS = {
    "documentary": PromptTemplate(
        template="""You are creating engaging commentary for a video. Here is all the information:

1. USER'S ORIGINAL CONTEXT:
{analysis}

2. COMPUTER VISION ANALYSIS (objects, labels, text detected):
{vision_analysis}

Your task is to create natural, engaging commentary that:
1. Uses the user's original context as the primary story foundation
2. Incorporates specific details from the vision analysis to make it vivid
3. Sounds like a genuine human reaction video
4. Stays under {duration} seconds (about {word_limit} words)

Key Guidelines:
1. Start with the user's story/context as your base
2. Use vision analysis details to enhance your reactions
3. React naturally like you're watching with friends
4. Use casual, conversational language
5. Show genuine enthusiasm and emotion
6. Make specific references to what excites you

Example format:
"Oh my gosh, this is exactly what they meant! Look at how [mention specific detail]... I love that [connect to broader meaning]..."

Remember: You're reacting naturally to the video while telling the user's story!""",
        provider_specific_params={
            "openai": {"model": "gpt-4o-mini", "temperature": 0.7},
            "deepseek": {"model": "deepseek-chat", "temperature": 0.7}
        }
    ),
    
    "energetic": PromptTemplate(
        template="""You're creating high-energy commentary for this video:

1. USER'S ORIGINAL CONTEXT:
{analysis}

2. COMPUTER VISION ANALYSIS (objects, labels, text detected):
{vision_analysis}

Create dynamic, enthusiastic commentary that:
1. Uses the user's context as your foundation
2. Highlights exciting details from the vision analysis
3. Sounds like an energetic reaction video
4. Stays under {duration} seconds (about {word_limit} words)

Key Guidelines:
1. Keep energy levels high
2. React with genuine excitement
3. Use dynamic language
4. Point out amazing moments
5. Share authentic enthusiasm
6. Make it fun and engaging

Example format:
"WOW! This is INCREDIBLE! Did you see how [specific detail]?! I can't believe [connect to context]..."

Remember: High energy, genuine reactions, and real enthusiasm!""",
        provider_specific_params={
            "openai": {"model": "gpt-4o-mini", "temperature": 0.8},
            "deepseek": {"model": "deepseek-chat", "temperature": 0.8}
        }
    ),
    
    "analytical": PromptTemplate(
        template="""You're providing detailed analytical commentary for this video:

1. USER'S ORIGINAL CONTEXT:
{analysis}

2. COMPUTER VISION ANALYSIS (objects, labels, text detected):
{vision_analysis}

Create insightful, technical commentary that:
1. Uses the user's context as your analytical base
2. Incorporates specific technical details
3. Sounds like expert analysis
4. Stays under {duration} seconds (about {word_limit} words)

Key Guidelines:
1. Focus on technical aspects
2. Explain interesting details
3. Connect observations to context
4. Use precise language
5. Share expert insights
6. Point out noteworthy elements

Example format:
"What's particularly interesting here is [technical detail]... This demonstrates [analytical insight]... Notice how [connect to context]..."

Remember: Be thorough but engaging in your analysis!""",
        provider_specific_params={
            "openai": {"model": "gpt-4o-mini", "temperature": 0.6},
            "deepseek": {"model": "deepseek-chat", "temperature": 0.6}
        }
    ),
    
    "storyteller": PromptTemplate(
        template="""You're sharing an incredible story through this video:

1. USER'S ORIGINAL CONTEXT:
{analysis}

2. COMPUTER VISION ANALYSIS (objects, labels, text detected):
{vision_analysis}

Create emotional, story-driven commentary that:
1. Uses the user's context as the heart of the story
2. Weaves in specific visual details to enhance emotion
3. Sounds like sharing a meaningful moment
4. Stays under {duration} seconds (about {word_limit} words)

Key Guidelines:
1. Start with the user's emotional core
2. Build narrative with specific details
3. Connect moments to feelings
4. Keep it personal and genuine
5. Share authentic reactions
6. Make viewers feel something

Example format:
"This story touches my heart... When you see [specific detail], you realize [emotional connection]... What makes this so special is [tie to user's context]..."

Remember: Tell their story with heart and authentic emotion!""",
        provider_specific_params={
            "openai": {"model": "gpt-4o-mini", "temperature": 0.75},
            "deepseek": {"model": "deepseek-chat", "temperature": 0.75}
        }
    ),
    
    "urdu": PromptTemplate(
        template="""آپ ایک ویڈیو پر جذباتی تبصرہ کر رہے ہیں:

1. صارف کا تناظر:
{analysis}

2. کمپیوٹر ویژن تجزیہ:
{vision_analysis}

اردو میں ایک دلچسپ اور جذباتی تبصرہ بنائیں جو:
1. صارف کے تناظر کو بنیاد بناتا ہے
2. خاص بصری تفصیلات کو شامل کرتا ہے
3. حقیقی جذباتی ردعمل کی طرح لگتا ہے
4. {duration} سیکنڈز سے کم ہے (تقریباً {word_limit} الفاظ)

اہم ہدایات:
1. قدرتی اور روزمرہ کی اردو استعمال کریں
2. جذباتی اور دلچسپ انداز اپنائیں
3. خاص لمحات پر ردعمل دیں
4. عام اردو محاورے استعمال کریں
5. حقیقی جذبات کا اظہار کریں

مثال کا انداز:
"ارے واہ! یہ تو بالکل وہی ہے جو [خاص تفصیل]... دل خوش ہو گیا [جذباتی رابطہ]... کیا بات ہے [صارف کے تناظر سے جوڑیں]..."

یاد رکھیں: آپ کو اردو میں حقیقی جذباتی ردعمل دینا ہے!""",
        provider_specific_params={
            "openai": {"model": "gpt-4o-mini", "temperature": 0.7},
            "deepseek": {"model": "deepseek-chat", "temperature": 0.7}
        }
    )
}

# Example usage:
# prompt_manager = PromptManager(provider=LLMProvider.OPENAI)
# commentary = prompt_manager.generate_response(
#     COMMENTARY_PROMPTS["documentary"],
#     analysis="Video analysis text here"
# ) 