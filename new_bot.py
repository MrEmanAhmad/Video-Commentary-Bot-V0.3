"""
Telegram bot for video processing with AI commentary
"""

import os
import logging
import asyncio
from pathlib import Path
import json
import sys
from typing import Dict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from dotenv import load_dotenv
import psutil
import gc
from concurrent.futures import ThreadPoolExecutor
import cv2
import shutil
from datetime import datetime

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load configuration
required_vars = [
    'OPENAI_API_KEY',
    'DEEPSEEK_API_KEY',
    'GOOGLE_APPLICATION_CREDENTIALS_JSON'
]

# First try to get variables from environment (Railway)
env_vars = {var: os.getenv(var) for var in required_vars}
missing_vars = [var for var, value in env_vars.items() if not value]

# Log environment status
logger.info("Checking environment variables...")
for var in required_vars:
    if os.getenv(var):
        logger.info(f"✓ Found {var} in environment")
    else:
        logger.warning(f"✗ Missing {var} in environment")

# Try to load from railway.json if any variables are missing
if missing_vars:
    logger.info("Some variables missing, checking railway.json...")
    railway_file = Path("railway.json")
    if railway_file.exists():
        logger.info("Found railway.json, loading configuration...")
        with open(railway_file, 'r') as f:
            config = json.load(f)
        for var in missing_vars:
            if var in config:
                os.environ[var] = str(config[var])
                logger.info(f"Loaded {var} from railway.json")
    else:
        logger.warning("railway.json not found")

# Final check for required variables
still_missing = [var for var in required_vars if not os.getenv(var)]
if still_missing:
    error_msg = f"Missing required environment variables: {', '.join(still_missing)}"
    logger.error(error_msg)
    raise ValueError(error_msg)

# Set up Google credentials
if "GOOGLE_APPLICATION_CREDENTIALS_JSON" in os.environ:
    try:
        # Create credentials directory with proper permissions
        creds_dir = Path("credentials")
        creds_dir.mkdir(exist_ok=True, mode=0o777)
        
        google_creds_file = creds_dir / "google_credentials.json"
        
        # Get credentials JSON and ensure it's properly formatted
        creds_json_str = os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"]
        logger.info("Attempting to parse Google credentials...")
        
        # Try multiple parsing approaches
        try:
            # First, try direct JSON parsing
            creds_json = json.loads(creds_json_str)
        except json.JSONDecodeError as je:
            logger.warning(f"Direct JSON parsing failed: {je}")
            try:
                # Try cleaning the string and parsing again
                cleaned_str = creds_json_str.replace('\n', '\\n').replace('\r', '\\r')
                creds_json = json.loads(cleaned_str)
            except json.JSONDecodeError:
                logger.warning("Cleaned JSON parsing failed, trying literal eval")
                try:
                    # Try literal eval as last resort
                    import ast
                    creds_json = ast.literal_eval(creds_json_str)
                except (SyntaxError, ValueError) as e:
                    logger.error(f"All parsing attempts failed. Original error: {e}")
                    # Log the first and last few characters of the string for debugging
                    str_preview = f"{creds_json_str[:100]}...{creds_json_str[-100:]}" if len(creds_json_str) > 200 else creds_json_str
                    logger.error(f"Credentials string preview: {str_preview}")
                    raise ValueError("Could not parse Google credentials. Please check the format.")
        
        # Validate required fields
        required_fields = [
            "type", "project_id", "private_key_id", "private_key",
            "client_email", "client_id", "auth_uri", "token_uri",
            "auth_provider_x509_cert_url", "client_x509_cert_url"
        ]
        missing_fields = [field for field in required_fields if field not in creds_json]
        if missing_fields:
            raise ValueError(f"Missing required fields in credentials: {', '.join(missing_fields)}")
        
        # Ensure private key is properly formatted
        if 'private_key' in creds_json:
            # Normalize line endings and ensure proper PEM format
            private_key = creds_json['private_key']
            if not private_key.startswith('-----BEGIN PRIVATE KEY-----'):
                private_key = f"-----BEGIN PRIVATE KEY-----\n{private_key}"
            if not private_key.endswith('-----END PRIVATE KEY-----'):
                private_key = f"{private_key}\n-----END PRIVATE KEY-----"
            creds_json['private_key'] = private_key.replace('\\n', '\n')
        
        # Write credentials file with proper permissions
        with open(google_creds_file, 'w') as f:
            json.dump(creds_json, f, indent=2)
        
        # Set file permissions
        google_creds_file.chmod(0o600)
        
        # Set environment variable to absolute path
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(google_creds_file.absolute())
        logger.info("✓ Google credentials configured successfully")
        
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON format in credentials: {e}")
        raise ValueError("Google credentials JSON is not properly formatted")
    except ValueError as e:
        logger.error(f"Invalid credentials content: {e}")
        raise
    except Exception as e:
        logger.error(f"Error setting up Google credentials: {e}")
        raise

# Import pipeline modules
from pipeline import (
    Step_1_download_video,
    Step_2_extract_frames,
    Step_3_analyze_frames,
    Step_4_generate_commentary,
    Step_5_generate_audio,
    Step_6_video_generation
)

# Constants
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50MB
SUPPORTED_FORMATS = ['mp4', 'mov', 'avi']

class VideoBot:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # User settings storage
        self.user_settings: Dict[int, dict] = {}
        
        # Default settings
        self.default_settings = {
            'style': 'news',
            'llm': 'openai',
            'language': 'en',
            'notifications': True,
            'auto_cleanup': True
        }
        
        # Available styles
        self.styles = {
            'news': {
                'name': '📰 News',
                'description': 'Professional & objective reporting',
                'icon': '📰'
            },
            'funny': {
                'name': '😄 Funny',
                'description': 'Entertaining & humorous commentary',
                'icon': '😄'
            },
            'nature': {
                'name': '🌿 Nature',
                'description': 'Documentary-style narration',
                'icon': '🌿'
            },
            'infographic': {
                'name': '📊 Infographic',
                'description': 'Educational & informative',
                'icon': '📊'
            }
        }
        
        # Available languages with their features
        self.languages = {
            'en': {
                'name': 'English',
                'description': 'Default language for all styles',
                'icon': '🇬🇧',
                'requires_openai': False
            },
            'ur': {
                'name': 'Urdu',
                'description': 'Urdu language support for all styles',
                'icon': '🇵🇰',
                'requires_openai': True
            }
        }
        
        # Available LLM providers
        self.llm_providers = {
            'openai': {
                'name': 'OpenAI GPT-4',
                'description': 'Best quality, all features',
                'icon': '🧠'
            },
            'deepseek': {
                'name': 'Deepseek',
                'description': 'Faster, basic features',
                'icon': '🤖'
            }
        }

        # Add performance settings
        self.max_memory_percent = 75
        self.max_concurrent_processes = 2
        self.active_processes = 0
        self.process_lock = asyncio.Lock()
        self.thread_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video_worker")

    def get_user_settings(self, user_id: int) -> dict:
        """Get settings for a user, with defaults if not set."""
        if user_id not in self.user_settings:
            self.user_settings[user_id] = self.default_settings.copy()
        return self.user_settings[user_id]

    def update_user_setting(self, user_id: int, setting: str, value: any):
        """Update a specific setting for a user."""
        if user_id not in self.user_settings:
            self.user_settings[user_id] = self.default_settings.copy()
        self.user_settings[user_id][setting] = value

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show main menu."""
        query = update.callback_query
        if query:
            await query.answer()
        
        keyboard = [
            [
                InlineKeyboardButton("🎬 Create Video", callback_data="create"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings")
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="help"),
                InlineKeyboardButton("📖 Tutorial", callback_data="tutorial")
            ]
        ]
        
        welcome_text = (
            "*Welcome to Video Commentary Bot*\n\n"
            "I can add AI commentary to your videos. Here's what I can do:\n\n"
            "🎭 Multiple commentary styles\n"
            "🤖 Advanced AI processing\n"
            "🎙️ Natural voice synthesis\n"
            "🎥 Professional results\n\n"
            "Choose an option to begin:"
        )
        
        if query:
            await query.edit_message_text(
                welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                welcome_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await self.show_main_menu(update, context)

    async def settings_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show settings menu."""
        query = update.callback_query
        if query:
            await query.answer()
        
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        # Get current settings info
        current_style = self.styles[settings['style']]
        current_llm = self.llm_providers[settings['llm']]
        current_lang = self.languages[settings['language']]
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{current_style['icon']} Style",
                    callback_data="set_style"
                ),
                InlineKeyboardButton(
                    f"{current_llm['icon']} AI Model",
                    callback_data="set_llm"
                )
            ],
            [
                InlineKeyboardButton(
                    f"{current_lang['icon']} Language",
                    callback_data="set_lang"
                ),
                InlineKeyboardButton(
                    f"{'🔔' if settings['notifications'] else '🔕'} Notifications",
                    callback_data="set_notif"
                )
            ],
            [InlineKeyboardButton("« Back to Main Menu", callback_data="back_to_main")]
        ]
        
        text = (
            "*Settings*\n\n"
            f"*Current Settings:*\n"
            f"{current_style['icon']} Style: {current_style['name']}\n"
            f"{current_llm['icon']} AI Model: {current_llm['name']}\n"
            f"{current_lang['icon']} Language: {current_lang['name']}\n"
            f"{'🔔' if settings['notifications'] else '🔕'} Notifications: {'On' if settings['notifications'] else 'Off'}\n\n"
            "Select a setting to change:"
        )
        
        if query:
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

    def validate_language_settings(self, user_id: int) -> bool:
        """Validate language settings compatibility."""
        settings = self.get_user_settings(user_id)
        logger.info(f"Validating language settings for user {user_id}: {settings}")
        
        # Check if selected language requires OpenAI
        selected_lang = settings['language']
        lang_info = self.languages.get(selected_lang, {})
        requires_openai = lang_info.get('requires_openai', False)
        
        # If language requires OpenAI but not using OpenAI
        if requires_openai and settings['llm'] != 'openai':
            logger.warning(f"Language {selected_lang} requires OpenAI but user is using {settings['llm']}")
            return False
            
        logger.info(f"Language settings valid for user {user_id}")
        return True

    async def handle_style_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle style selection."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        keyboard = []
        for style_id, style_info in self.styles.items():
            # Add checkmark to current style
            is_current = settings['style'] == style_id
            button_text = f"{style_info['icon']} {style_info['name']}"
            if is_current:
                button_text = f"✓ {button_text}"
            
            keyboard.append([
                InlineKeyboardButton(button_text, callback_data=f"style_{style_id}")
            ])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="settings")])
        
        text = (
            "*Select Commentary Style*\n\n"
            f"Current: {self.styles[settings['style']]['name']}\n\n"
            "Choose your preferred style:\n\n"
            + "\n".join(f"{style['icon']} *{style['name']}*\n{style['description']}"
                       for style in self.styles.values())
        )
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def handle_llm_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle LLM provider selection."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        keyboard = []
        for llm, llm_info in self.llm_providers.items():
            keyboard.append([
                InlineKeyboardButton(
                    f"✓ {llm_info['name']}" if settings['llm'] == llm else llm_info['name'],
                    callback_data=f"llm_{llm}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="settings")])
        
        await query.edit_message_text(
            "*Select AI Model*\n\n"
            "Choose which AI model to use:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def handle_url_share(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle video URL sharing."""
        query = update.callback_query
        if query:
            await query.answer()
            
            text = (
                "*🔗 Share Video URL*\n\n"
                "Send me any video URL!\n\n"
                "Supported sources include:\n"
                "• YouTube, Vimeo, TikTok\n"
                "• Instagram, Facebook\n"
                "• Twitter/X, Reddit\n"
                "• Direct video links\n"
                "• And many more!\n\n"
                "Just paste the URL in the chat and I'll try to process it.\n\n"
                "*Note:* Maximum video length: 5 minutes"
            )
            
            keyboard = [[InlineKeyboardButton("« Back", callback_data="create")]]
            
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

    async def handle_url_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle URL text input."""
        url = update.message.text.strip()
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        # Basic URL validation
        if not url.startswith(('http://', 'https://')):
            await update.message.reply_text(
                "❌ Please provide a valid URL starting with http:// or https://"
            )
            return
        
        # Process the video from URL
        await self.process_video_from_url(update, context, url)

    async def process_video_from_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
        """Process video from URL."""
        try:
            # Send initial status
            status_message = await update.message.reply_text(
                "🎬 Starting video processing...\n\n"
                "0% ▱▱▱▱▱▱▱▱▱▱"
            )
            
            # Create temporary directory for download
            temp_dir = Path(f"temp_{update.message.message_id}")
            temp_dir.mkdir(exist_ok=True)
            
            try:
                # Update status for download
                await status_message.edit_text(
                    "📥 Downloading video...\n\n"
                    "10% ▰▱▱▱▱▱▱▱▱▱"
                )
                
                # Download video using Step_1_download_video
                logger.info(f"Downloading video from: {url}")
                success, metadata, video_title = Step_1_download_video.execute_step(url, temp_dir)
                
                if not success or not metadata:
                    raise Exception("Could not download video from this URL")
                
                # Find the downloaded video file
                video_path = next(Path(temp_dir / "video").glob("*.mp4"))
                
                if not os.path.exists(video_path):
                    raise Exception("Could not find downloaded video file")
                
                # Check video size
                if os.path.getsize(video_path) > MAX_VIDEO_SIZE:
                    await status_message.edit_text(
                        "❌ Video is too large. Maximum size is 50MB.\n"
                        "Try a shorter video or lower quality version."
                    )
                    return
                
                # Process the downloaded video with metadata
                await self.process_video_file(update, context, str(video_path), status_message, metadata)
                
            except Exception as download_error:
                logger.error(f"Download error: {download_error}")
                await status_message.edit_text(
                    "❌ Could not download video from this URL.\n\n"
                    "Possible reasons:\n"
                    "• URL is not accessible\n"
                    "• Video is private or restricted\n"
                    "• Website not supported\n"
                    "• Video requires authentication\n\n"
                    "Try another URL or upload the video directly."
                )
                return
                
            finally:
                # Cleanup temporary directory
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
                
        except Exception as e:
            logger.error(f"Error processing URL: {e}")
            error_message = str(e)
            if len(error_message) > 100:
                error_message = error_message[:100] + "..."
            await status_message.edit_text(
                f"❌ Error processing video URL:\n{error_message}\n\n"
                "Please try:\n"
                "• A different URL\n"
                "• Uploading directly\n"
                "• A shorter video"
            )

    async def process_video_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE, video_path: str, status_message, metadata=None):
        """Process a video file with status updates."""
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        try:
            # Create output directory
            output_dir = Path(f"output_{update.message.message_id}")
            output_dir.mkdir(exist_ok=True)
            
            try:
                # Save metadata if provided
                if metadata:
                    metadata_file = output_dir / "video_metadata.json"
                    with open(metadata_file, 'w', encoding='utf-8') as f:
                        json.dump(metadata, f, indent=2, ensure_ascii=False)
                
                # Step 1: Video is already downloaded
                logger.info("Starting video processing...")
                
                # Step 2: Extract frames
                logger.info("Extracting frames...")
                await status_message.edit_text(
                    "🎞️ Extracting frames...\n\n"
                    "30% ▰▰▰▱▱▱▱▱▱▱"
                )
                
                key_frames, scene_changes, motion_scores, duration, file_metadata = Step_2_extract_frames.execute_step(
                    video_file=video_path,
                    output_dir=output_dir
                )
                
                # Convert any numpy floats to Python floats
                duration = float(duration)
                motion_scores = [(path, float(score)) for path, score in motion_scores]
                
                # Combine metadata from file and provided metadata
                combined_metadata = {
                    **(file_metadata or {}),  # Metadata from video file
                    **(metadata or {}),       # Provided metadata
                    'duration': duration,
                    'scene_changes': [str(p) for p in scene_changes],
                    'motion_scores': [(str(p), score) for p, score in motion_scores],
                    'language': settings['language']  # Add language to metadata
                }
                
                # Store frame info for later steps
                frames_info = {
                    'metadata': combined_metadata
                }
                
                # Step 3: Analyze frames
                logger.info("Analyzing frames...")
                await status_message.edit_text(
                    "🔍 Analyzing video content...\n\n"
                    "50% ▰▰▰▰▰▱▱▱▱▱"
                )
                
                frames_info = await Step_3_analyze_frames.execute_step(
                    frames_dir=output_dir / "frames",
                    output_dir=output_dir,
                    metadata=frames_info['metadata'],
                    scene_changes=scene_changes,
                    motion_scores=motion_scores,
                    video_duration=duration
                )
                
                # Step 4: Generate commentary
                logger.info(f"Generating commentary in {settings['language']}...")
                await status_message.edit_text(
                    "💭 Generating commentary...\n\n"
                    "70% ▰▰▰▰▰▰▰▱▱▱"
                )
                
                audio_script = await Step_4_generate_commentary.execute_step(
                    frames_info,
                    output_dir,
                    settings['style']
                )
                
                # Step 5: Generate audio
                logger.info(f"Generating audio in {settings['language']}...")
                await status_message.edit_text(
                    "🎙️ Synthesizing voice...\n\n"
                    "80% ▰▰▰▰▰▰▰▰▱▱"
                )
                
                audio_path = await Step_5_generate_audio.execute_step(
                    audio_script,
                    output_dir,
                    settings['style']
                )
                
                # Step 6: Generate final video
                logger.info("Generating final video...")
                await status_message.edit_text(
                    "🎥 Creating final video...\n\n"
                    "85% ▰▰▰▰▰▰▰▰▰▱"
                )
                
                final_video = await Step_6_video_generation.execute_step(
                    Path(video_path),
                    Path(str(audio_path)),
                    output_dir,
                    settings['style']
                )
                
                if not final_video:
                    raise ValueError("Failed to generate final video")
                
                # Upload final video
                await status_message.edit_text(
                    "📤 Uploading enhanced video...\n\n"
                    "90% ▰▰▰▰▰▰▰▰▱▱"
                )
                
                with open(final_video, 'rb') as f:
                    await update.message.reply_video(
                        video=f,
                        caption=(
                            f"✨ Here's your video with {settings['style']} commentary!\n\n"
                            f"🎭 Style: {settings['style'].title()}\n"
                            f"🤖 AI: {settings['llm'].title()}\n"
                            f"🌐 Language: {settings['language'].upper()}"
                        )
                    )
                
                # Complete
                await status_message.edit_text(
                    "✅ Processing complete!\n\n"
                    "100% ▰▰▰▰▰▰▰▰▰▰"
                )
                
            finally:
                # Cleanup output directory
                if output_dir.exists():
                    shutil.rmtree(output_dir)
                
        except Exception as e:
            logger.error(f"Error processing video file: {e}")
            await status_message.edit_text(
                f"❌ Error processing video: {str(e)}\n"
                "Please try again or contact support."
            )

    async def handle_language_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle language selection."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        keyboard = []
        for lang_code, lang_info in self.languages.items():
            # Check if language is available with current LLM
            is_available = True
            requires_openai = lang_info.get('requires_openai', False)
            
            if requires_openai and settings['llm'] != 'openai':
                is_available = False
            
            # Create button text
            button_text = f"{lang_info['icon']} {lang_info['name']}"
            if settings['language'] == lang_code:
                button_text = f"✓ {button_text}"
            if not is_available:
                button_text += " (requires OpenAI)"
            
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"lang_{lang_code}"
                )
            ])
        
        keyboard.append([InlineKeyboardButton("« Back", callback_data="settings")])
        
        text = (
            "*Select Language*\n\n"
            f"Current: {self.languages[settings['language']]['name']}\n\n"
            "Available languages:\n"
        )
        
        # Add language descriptions
        for lang_code, lang_info in self.languages.items():
            text += f"\n{lang_info['icon']} *{lang_info['name']}*"
            if lang_info.get('requires_openai', False):
                text += " (requires OpenAI GPT-4)"
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def handle_notification_setting(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle notification settings."""
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        keyboard = [
            [
                InlineKeyboardButton("✓ On" if settings['notifications'] else "On",
                                   callback_data="notif_on"),
                InlineKeyboardButton("Off" if settings['notifications'] else "✓ Off",
                                   callback_data="notif_off")
            ],
            [InlineKeyboardButton("« Back", callback_data="settings")]
        ]
        
        await query.edit_message_text(
            "*Notification Settings*\n\n"
            f"Current: {'On' if settings['notifications'] else 'Off'}\n\n"
            "Receive updates during processing",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def show_upload_options(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show video upload options."""
        query = update.callback_query
        await query.answer()
        
        keyboard = [
            [
                InlineKeyboardButton("📤 Upload Video", callback_data="upload"),
                InlineKeyboardButton("🔗 Share URL", callback_data="url")
            ],
            [InlineKeyboardButton("« Back", callback_data="back_to_main")]
        ]
        
        await query.edit_message_text(
            "*Upload Your Video*\n\n"
            "• Maximum size: 50MB\n"
            "• Supported formats: MP4, MOV, AVI\n"
            "• Maximum duration: 5 minutes\n\n"
            "Choose how to share your video:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help menu."""
        query = update.callback_query
        await query.answer()
        
        text = (
            "*Help & Support*\n\n"
            "*Commands:*\n"
            "/start - Start the bot\n"
            "/settings - Change settings\n"
            "/help - Show this help\n\n"
            
            "*Features:*\n"
            "• AI video commentary\n"
            "• Multiple styles\n"
            "• Natural voice synthesis\n"
            "• Support for multiple languages\n\n"
            
            "*Limitations:*\n"
            "• Max video size: 50MB\n"
            "• Max duration: 5 minutes\n"
            "• Supported formats: MP4, MOV, AVI"
        )
        
        keyboard = [[InlineKeyboardButton("« Back", callback_data="back_to_main")]]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def show_tutorial(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show tutorial."""
        query = update.callback_query
        await query.answer()
        
        text = (
            "*Quick Tutorial*\n\n"
            "*1. Choose Your Style*\n"
            "• Documentary - Professional & informative\n"
            "• Energetic - Dynamic & enthusiastic\n"
            "• Analytical - Technical & detailed\n"
            "• Storyteller - Narrative & emotional\n\n"
            
            "*2. Select AI Model*\n"
            "• OpenAI GPT-4 - Best quality\n"
            "• Deepseek - Faster processing\n\n"
            
            "*3. Upload Video*\n"
            "• Send video file or URL\n"
            "• Wait for processing\n"
            "• Get enhanced video\n\n"
            
            "*Tips:*\n"
            "• Use high-quality videos\n"
            "• Keep videos under 3 minutes\n"
            "• Choose style matching content"
        )
        
        keyboard = [[InlineKeyboardButton("« Back", callback_data="back_to_main")]]
        
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    def check_system_resources(self) -> bool:
        """Check if system has enough resources."""
        try:
            # Check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > self.max_memory_percent:
                return False
                
            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:  # CPU usage above 90%
                return False
                
            return True
        except Exception as e:
            logger.error(f"Error checking resources: {e}")
            return True  # Default to True if check fails

    async def cleanup_resources(self):
        """Clean up system resources."""
        try:
            # Force garbage collection
            gc.collect()
            
            # Clear any temporary files
            temp_pattern = "temp_*"
            output_pattern = "output_*"
            for pattern in [temp_pattern, output_pattern]:
                for path in Path().glob(pattern):
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

    async def process_video(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process uploaded video."""
        user_id = update.effective_user.id
        settings = self.get_user_settings(user_id)
        
        # Check active processes
        async with self.process_lock:
            if self.active_processes >= self.max_concurrent_processes:
                await update.message.reply_text(
                    "⏳ Bot is currently busy. Please try again in a few minutes."
                )
                return
            
            # Check system resources
            if not self.check_system_resources():
                await update.message.reply_text(
                    "⚠️ System is currently under heavy load. Please try again later."
                )
                return
            
            self.active_processes += 1
        
        try:
            # Validate language settings
            if not self.validate_language_settings(user_id):
                await update.message.reply_text(
                    "❌ Urdu commentary requires OpenAI GPT-4.\n"
                    "Please change your AI model or language in settings."
                )
                return
            
            # Check video size
            video = update.message.video
            if video.file_size > MAX_VIDEO_SIZE:
                await update.message.reply_text(
                    "❌ Video is too large. Maximum size is 50MB."
                )
                return
            
            # Send initial status message
            status_message = await update.message.reply_text(
                "🎬 Starting video processing...\n\n"
                "0% ▱▱▱▱▱▱▱▱▱▱"
            )
            
            try:
                # Download video (10%)
                await status_message.edit_text(
                    "📥 Downloading video...\n\n"
                    "10% ▰▱▱▱▱▱▱▱▱▱"
                )
                
                video_file = await context.bot.get_file(video.file_id)
                video_path = f"temp_{video.file_unique_id}.mp4"
                await video_file.download_to_drive(video_path)
                
                # Create basic metadata for uploaded video
                metadata = {
                    'title': video.file_name if video.file_name else f"video_{video.file_unique_id}",
                    'duration': video.duration,
                    'description': 'Uploaded via Telegram',
                    'uploader': f"User_{update.effective_user.id}",
                    'upload_date': datetime.now().strftime("%Y%m%d"),
                    'file_size': video.file_size,
                    'mime_type': video.mime_type,
                    'width': video.width,
                    'height': video.height
                }
                
                # Create output directory
                output_dir = Path(f"output_{video.file_unique_id}")
                output_dir.mkdir(exist_ok=True)
                
                try:
                    # Process through pipeline
                    final_video = await self.run_pipeline_sync(
                        video_path,
                        output_dir,
                        settings,
                        status_message,
                        metadata
                    )
                    
                    # Upload final video
                    await status_message.edit_text(
                        "📤 Uploading enhanced video...\n\n"
                        "90% ▰▰▰▰▰▰▰▰▱▱"
                    )
                    
                    with open(final_video, 'rb') as f:
                        await update.message.reply_video(
                            video=f,
                            caption=(
                                f"✨ Here's your video with {settings['style']} commentary!\n\n"
                                f"🎭 Style: {settings['style'].title()}\n"
                                f"🤖 AI: {settings['llm'].title()}\n"
                                f"🌐 Language: {settings['language'].upper()}"
                            )
                        )
                    
                    # Complete
                    await status_message.edit_text(
                        "✅ Processing complete!\n\n"
                        "100% ▰▰▰▰▰▰▰▰▰▰"
                    )
                    
                finally:
                    # Cleanup
                    if os.path.exists(video_path):
                        os.remove(video_path)
                    if output_dir.exists():
                        shutil.rmtree(output_dir)
                    
            except Exception as e:
                logger.error(f"Error processing video: {e}")
                await status_message.edit_text(
                    f"❌ Error processing video: {str(e)}\n"
                    "Please try again or contact support."
                )
                
        finally:
            # Decrease active processes count
            async with self.process_lock:
                self.active_processes -= 1
            
            # Cleanup resources
            await self.cleanup_resources()

    def optimize_video_for_processing(self, video_path: str) -> str:
        """Optimize video before processing to reduce memory usage."""
        try:
            # Read video
            cap = cv2.VideoCapture(video_path)
            
            # Get video properties
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = int(cap.get(cv2.CAP_PROP_FPS))
            
            # Calculate new dimensions (max 720p)
            if height > 720:
                ratio = 720.0 / height
                width = int(width * ratio)
                height = 720
            
            # Create optimized video path
            optimized_path = f"opt_{os.path.basename(video_path)}"
            
            # Create video writer
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(optimized_path, fourcc, fps, (width, height))
            
            # Process frames
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                    
                # Resize frame
                if height != 720:
                    frame = cv2.resize(frame, (width, height))
                
                out.write(frame)
            
            # Release everything
            cap.release()
            out.release()
            
            return optimized_path
            
        except Exception as e:
            logger.error(f"Error optimizing video: {e}")
            return video_path  # Return original if optimization fails

    async def run_pipeline_sync(self, video_path: str, output_dir: Path, settings: dict, status_message, metadata=None) -> str:
        """Synchronous version of pipeline for thread pool."""
        try:
            # Save metadata if provided
            if metadata:
                metadata_file = output_dir / "video_metadata.json"
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            # Extract frames
            logger.info("Extracting frames...")
            key_frames, scene_changes, motion_scores, duration, file_metadata = Step_2_extract_frames.execute_step(
                video_file=video_path,
                output_dir=output_dir
            )
            
            # Convert any numpy floats to Python floats
            duration = float(duration)
            motion_scores = [(path, float(score)) for path, score in motion_scores]
            
            # Combine metadata from file and provided metadata
            combined_metadata = {
                **(file_metadata or {}),  # Metadata from video file
                **(metadata or {}),       # Provided metadata
                'duration': duration,
                'scene_changes': [str(p) for p in scene_changes],
                'motion_scores': [(str(p), score) for p, score in motion_scores],
                'language': settings['language']  # Add language to metadata
            }
            
            # Store frame info for later steps
            frames_info = {
                'metadata': combined_metadata
            }
            
            # Update status
            await status_message.edit_text(
                "🔍 Analyzing video content...\n\n"
                "50% ▰▰▰▰▰▱▱▱▱▱"
            )
            
            # Analyze frames
            logger.info("Analyzing frames...")
            frames_info = await Step_3_analyze_frames.execute_step(
                frames_dir=output_dir / "frames",
                output_dir=output_dir,
                metadata=frames_info['metadata'],
                scene_changes=scene_changes,
                motion_scores=motion_scores,
                video_duration=duration
            )
            
            # Update status
            await status_message.edit_text(
                "💭 Generating commentary...\n\n"
                "70% ▰▰▰▰▰▰▰▱▱▱"
            )
            
            # Generate commentary
            logger.info(f"Generating commentary in {settings['language']}...")
            audio_script = await Step_4_generate_commentary.execute_step(
                frames_info,
                output_dir,
                settings['style']
            )
            
            # Update status
            await status_message.edit_text(
                "🎙️ Synthesizing voice...\n\n"
                "80% ▰▰▰▰▰▰▰▰▱▱"
            )
            
            # Generate audio
            logger.info(f"Generating audio in {settings['language']}...")
            audio_path = await Step_5_generate_audio.execute_step(
                audio_script,
                output_dir,
                settings['style']
            )
            
            # Update status
            await status_message.edit_text(
                "🎥 Creating final video...\n\n"
                "85% ▰▰▰▰▰▰▰▰▰▱"
            )
            
            # Generate final video
            logger.info("Generating final video...")
            final_video = await Step_6_video_generation.execute_step(
                Path(video_path),
                Path(str(audio_path)),
                output_dir,
                settings['style']
            )
            
            if final_video:
                logger.info(f"Processing complete! Final video: {final_video}")
                return str(final_video)
            else:
                raise ValueError("Failed to generate final video")
            
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            raise

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle all callback queries."""
        query = update.callback_query
        data = query.data
        
        try:
            if data == "start" or data == "back_to_main":
                await self.show_main_menu(update, context)
            elif data == "settings":
                await self.settings_menu(update, context)
            elif data == "set_style":
                await self.handle_style_selection(update, context)
            elif data == "set_llm":
                await self.handle_llm_selection(update, context)
            elif data == "set_lang":
                await self.handle_language_selection(update, context)
            elif data == "set_notif":
                await self.handle_notification_setting(update, context)
            elif data == "url":
                await self.handle_url_share(update, context)
            elif data.startswith("style_"):
                style = data.replace("style_", "")
                if style in self.styles:
                    self.update_user_setting(update.effective_user.id, 'style', style)
                    await query.answer(f"Style set to: {self.styles[style]['name']}")
                    await self.settings_menu(update, context)
            elif data.startswith("llm_"):
                llm = data.replace("llm_", "")
                if llm in self.llm_providers:
                    self.update_user_setting(update.effective_user.id, 'llm', llm)
                    # If switching from OpenAI and using Urdu, reset language to English
                    if llm != 'openai':
                        settings = self.get_user_settings(update.effective_user.id)
                        if settings['language'] == 'ur':
                            self.update_user_setting(update.effective_user.id, 'language', 'en')
                            await query.answer("Language reset to English as Urdu requires OpenAI", show_alert=True)
                    else:
                        await query.answer(f"AI Model set to: {self.llm_providers[llm]['name']}")
                    await self.settings_menu(update, context)
            elif data.startswith("lang_"):
                lang = data.replace("lang_", "")
                if lang in self.languages:
                    settings = self.get_user_settings(update.effective_user.id)
                    if self.languages[lang].get('requires_openai', False) and settings['llm'] != 'openai':
                        await query.answer("This language requires OpenAI GPT-4. Please change AI model first.", show_alert=True)
                    else:
                        logger.info(f"Setting language to: {lang} for user {update.effective_user.id}")
                        self.update_user_setting(update.effective_user.id, 'language', lang)
                        await query.answer(f"Language set to: {self.languages[lang]['name']}", show_alert=True)
                        # Log current settings after update
                        current_settings = self.get_user_settings(update.effective_user.id)
                        logger.info(f"Current settings for user {update.effective_user.id}: {current_settings}")
                        await self.settings_menu(update, context)
            elif data.startswith("notif_"):
                value = data.replace("notif_", "") == "on"
                self.update_user_setting(update.effective_user.id, 'notifications', value)
                await query.answer(f"Notifications turned {'on' if value else 'off'}")
                await self.settings_menu(update, context)
            elif data == "create":
                await self.show_upload_options(update, context)
            elif data == "help":
                await self.show_help(update, context)
            elif data == "tutorial":
                await self.show_tutorial(update, context)
            else:
                await query.answer("Option not available yet")
                
        except Exception as e:
            logger.error(f"Callback error: {e}")
            await query.answer("An error occurred. Please try again.")

    def run(self):
        """Start the bot with minimal resource configuration."""
        # Create application with optimized settings
        application = (
            Application.builder()
            .token(os.getenv("TELEGRAM_BOT_TOKEN"))
            # Limit concurrent updates to match pipeline capacity
            .concurrent_updates(self.max_concurrent_processes)
            # Set conservative timeouts
            .connect_timeout(60)
            .read_timeout(60)
            .write_timeout(60)
            # Disable persistence to save memory
            .persistence(None)
            # Use HTTP/1.1 for better compatibility and less overhead
            .http_version("1.1")
            .get_updates_http_version("1.1")
            .build()
        )
        
        # Add only necessary handlers
        application.add_handler(CommandHandler(
            "start", 
            self.start,
            block=False  # Non-blocking to allow concurrent processing
        ))
        application.add_handler(CommandHandler(
            "settings", 
            self.settings_menu,
            block=False
        ))
        application.add_handler(CallbackQueryHandler(
            self.handle_callback,
            block=False
        ))
        
        # Combine video handlers to reduce overhead
        video_filter = (
            filters.VIDEO |
            filters.Document.VIDEO |
            filters.Document.MimeType("video/mp4") |
            filters.Document.MimeType("video/quicktime")
        )
        application.add_handler(MessageHandler(
            video_filter,
            self.process_video,
            block=False
        ))
        
        # URL handler with specific pattern matching
        application.add_handler(MessageHandler(
            filters.TEXT & filters.Regex(r'https?://[^\s/$.?#].[^\s]*'),
            self.handle_url_input,
            block=False
        ))
        
        # Start bot with minimal polling settings
        application.run_polling(
            # Only get essential update types
            allowed_updates=['message', 'callback_query'],
            # Drop updates that occurred while bot was offline
            drop_pending_updates=True,
            # Conservative timeout values
            pool_timeout=60,
            read_timeout=60,
            write_timeout=60,
            connect_timeout=60,
            # Limit polling frequency
            poll_interval=1.0
        )

if __name__ == '__main__':
    bot = VideoBot()
    bot.run() 