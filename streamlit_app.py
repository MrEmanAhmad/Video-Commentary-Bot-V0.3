import os
import sys
import logging
from pathlib import Path
import json
import asyncio
import tempfile
from datetime import datetime
import shutil
import gc
import psutil
import tracemalloc
import streamlit as st
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import pickle

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('streamlit_app.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Set stdout and stderr encoding to UTF-8
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

# Add the current directory to Python path
sys.path.append(str(Path(__file__).parent))

try:
    # Set page config first
    st.set_page_config(
        page_title="AI Video Commentary Bot",
        page_icon="🎬",
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            'Get Help': None,
            'Report a bug': None,
            'About': None
        }
    )
    
    # Initialize session state for authentication
    if 'google_auth' not in st.session_state:
        st.session_state.google_auth = None
    if 'user_info' not in st.session_state:
        st.session_state.user_info = None

    def get_google_auth_flow():
        """Create and return Google OAuth flow"""
        try:
            # Load client secrets from railway.json
            with open('railway.json', 'r') as f:
                config = json.load(f)
                client_secrets = json.loads(config['YOUTUBE_CLIENT_SECRETS'])
            
            # Create temporary secrets file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                json.dump(client_secrets, f)
                temp_secrets_path = f.name
            
            # Create flow with required scopes
            flow = InstalledAppFlow.from_client_secrets_file(
                temp_secrets_path,
                scopes=[
                    'https://www.googleapis.com/auth/youtube',
                    'https://www.googleapis.com/auth/youtube.upload',
                    'https://www.googleapis.com/auth/userinfo.email',
                    'https://www.googleapis.com/auth/userinfo.profile',
                    'openid'
                ]
            )
            
            # Clean up temporary file
            os.unlink(temp_secrets_path)
            return flow
        except Exception as e:
            logger.error(f"Error setting up Google auth flow: {e}")
            return None

    def get_user_info(credentials):
        """Get user info from Google"""
        try:
            import google.auth.transport.requests
            import google.oauth2.id_token
            
            request = google.auth.transport.requests.Request()
            id_info = google.oauth2.id_token.verify_oauth2_token(
                credentials.id_token, request
            )
            return {
                'email': id_info.get('email'),
                'name': id_info.get('name'),
                'picture': id_info.get('picture')
            }
        except Exception as e:
            logger.error(f"Error getting user info: {e}")
            return None

    # Show login interface if not authenticated
    if not st.session_state.google_auth:
        st.title("🎬 AI Video Commentary Bot")
        st.markdown("### Welcome! Please sign in with Google to continue")
        
        if st.button("🔑 Sign in with Google"):
            try:
                flow = get_google_auth_flow()
                if flow:
                    # Run the local server flow
                    credentials = flow.run_local_server(port=0)
                    
                    # Get user info first
                    user_info = get_user_info(credentials)
                    if not user_info:
                        st.error("❌ Failed to get user information")
                        st.stop()
                    
                    # Save credentials with user-specific filename
                    tokens_dir = Path.home() / '.video_bot' / 'tokens'
                    tokens_dir.mkdir(parents=True, exist_ok=True)
                    safe_email = user_info['email'].replace('@', '_at_').replace('.', '_dot_')
                    token_path = tokens_dir / f'{safe_email}_token.pickle'
                    
                    with open(token_path, 'wb') as token:
                        pickle.dump(credentials, token)
                    
                    # Store in session state
                    st.session_state.google_auth = credentials
                    st.session_state.user_info = user_info
                    st.success(f"✅ Successfully signed in as {user_info['email']}")
                    st.rerun()
                else:
                    st.error("❌ Failed to initialize Google authentication")
            except Exception as e:
                st.error(f"❌ Authentication failed: {str(e)}")
        
        # Stop here if not authenticated
        st.stop()

    # Show user info in sidebar if authenticated
    if st.session_state.user_info:
        with st.sidebar:
            st.markdown("---")
            col1, col2 = st.columns([1, 3])
            with col1:
                st.image(st.session_state.user_info['picture'], width=50)
            with col2:
                st.markdown(f"**{st.session_state.user_info['name']}**")
                st.markdown(f"_{st.session_state.user_info['email']}_")
            if st.button("Sign Out"):
                if st.session_state.user_info:
                    # Remove user-specific token file
                    safe_email = st.session_state.user_info['email'].replace('@', '_at_').replace('.', '_dot_')
                    token_path = Path.home() / '.video_bot' / 'tokens' / f'{safe_email}_token.pickle'
                    if token_path.exists():
                        token_path.unlink()
                
                st.session_state.google_auth = None
                st.session_state.user_info = None
                st.rerun()
            st.markdown("---")
    
    # Show loading message
    loading_placeholder = st.empty()
    loading_placeholder.info("🔄 Initializing application...")
    
    # Load configuration
    try:
        # Define required variables
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
            st.error(f"⚠️ Configuration Error: {error_msg}")
            st.error("Please ensure all required environment variables are set in Railway or railway.json")
            st.stop()
        
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
                st.error("⚠️ Error: Google credentials JSON is not properly formatted. Please check the credential format.")
                st.stop()
            except ValueError as e:
                logger.error(f"Invalid credentials content: {e}")
                st.error(f"⚠️ Error: {str(e)}")
                st.stop()
            except Exception as e:
                logger.error(f"Error setting up Google credentials: {e}")
                st.error("⚠️ Error setting up Google credentials. Please check the logs for details.")
                st.stop()

        # Continue with the rest of the imports and initialization
        logger.info("✓ Configuration loaded successfully")
        loading_placeholder.success("✓ Configuration loaded successfully")
        
        # Import required modules
        import tempfile
        import asyncio
        import json
        from datetime import datetime
        import shutil
        from telegram.ext import ContextTypes
        from telegram import Bot
        import gc
        import tracemalloc
        import psutil
        
        from new_bot import VideoBot
        from pipeline import Step_1_download_video, Step_7_cleanup
        from pipeline.youtube_uploader import YouTubeUploader
        
        # Initialize VideoBot with proper caching
        @st.cache_resource(show_spinner=False)
        def init_bot():
            """Initialize the VideoBot instance with caching"""
            try:
                return VideoBot()
            except Exception as e:
                logger.error(f"Bot initialization error: {e}")
                raise
        
        # Initialize bot instance
        bot = init_bot()
        
        # Initialize session state
        if 'initialized' not in st.session_state:
            st.session_state.initialized = False
            st.session_state.settings = bot.default_settings.copy()
            st.session_state.is_processing = False
            st.session_state.progress = 0
            st.session_state.status = ""
            st.session_state.initialized = True
        
        # Add YouTube uploader to session state
        if 'youtube_uploader' not in st.session_state:
            st.session_state.youtube_uploader = None
        
        # Clear loading message
        loading_placeholder.empty()
        
        # Safe cleanup function
        def cleanup_memory(force=False):
            """Force garbage collection and clear memory"""
            try:
                if force or not st.session_state.get('is_processing', False):
                    gc.collect()
                    
                # Clear temp directories that are older than 1 hour
                current_time = datetime.now().timestamp()
                for pattern in ['temp_*', 'output_*']:
                    for path in Path().glob(pattern):
                        try:
                            if path.is_dir():
                                # Check if directory is older than 1 hour
                                if current_time - path.stat().st_mtime > 3600:
                                    shutil.rmtree(path, ignore_errors=True)
                        except Exception as e:
                            logger.warning(f"Failed to remove directory {path}: {e}")
                
                logger.info("Cleanup completed successfully")
            except Exception as e:
                logger.error(f"Error during cleanup: {e}")
        
        # Custom CSS with mobile responsiveness and centered content
        st.markdown("""
            <style>
            /* Global responsive container */
            .main {
                max-width: 1200px;
                margin: 0 auto;
                padding: 1rem;
            }

            /* Responsive text sizing */
            @media (max-width: 768px) {
                h1 { font-size: 1.5rem !important; }
                h2 { font-size: 1.3rem !important; }
                p, div { font-size: 0.9rem !important; }
            }

            /* Center all content */
            .stApp {
                max-width: 100%;
                margin: 0 auto;
            }

            /* Make tabs more mobile-friendly */
            .stTabs [data-baseweb="tab-list"] {
                gap: 8px;
                flex-wrap: wrap;
            }

            .stTabs [data-baseweb="tab"] {
                height: auto !important;
                padding: 10px !important;
                white-space: normal !important;
                min-width: 120px;
            }

            /* Responsive video grid */
            .sample-video-grid {
                display: grid;
                gap: 1rem;
                width: 100%;
                padding: 1rem;
            }

            /* Responsive grid breakpoints */
            @media (min-width: 1200px) {
                .sample-video-grid { grid-template-columns: repeat(3, 1fr); }
            }
            @media (min-width: 768px) and (max-width: 1199px) {
                .sample-video-grid { grid-template-columns: repeat(2, 1fr); }
            }
            @media (max-width: 767px) {
                .sample-video-grid { grid-template-columns: 1fr; }
            }

            /* Make all videos responsive and reel-sized */
            .stVideo {
                width: 100% !important;
                height: auto !important;
                max-width: 400px !important;
                margin: 0 auto !important;
            }

            video {
                width: 100% !important;
                height: auto !important;
                max-height: 80vh;
                aspect-ratio: 9/16 !important;
                object-fit: cover !important;
                border-radius: 10px;
                background: #000;
            }

            /* URL input and button styling */
            .url-input-container {
                width: 100%;
                max-width: 600px;
                margin: 0 auto;
                padding: 1rem;
            }

            /* Style text inputs */
            .stTextInput input {
                width: 100%;
                max-width: 600px;
                margin: 0 auto;
                padding: 0.5rem;
                border-radius: 5px;
            }

            /* Style buttons */
            .stButton button {
                width: auto !important;
                min-width: 150px;
                max-width: 300px;
                margin: 1rem auto !important;
                padding: 0.5rem 1rem !important;
                display: block !important;
                border-radius: 5px;
            }

            /* Responsive sidebar */
            @media (max-width: 768px) {
                .css-1d391kg {
                    width: 100% !important;
                }
            }

            /* Loading and status messages */
            .stAlert {
                max-width: 600px;
                margin: 1rem auto !important;
            }

            /* Center download button and style it */
            .download-button-container {
                display: flex;
                justify-content: center;
                align-items: center;
                width: 100%;
                margin: 1rem auto;
                padding: 0.5rem;
            }

            .stDownloadButton {
                display: flex !important;
                justify-content: center !important;
                margin: 1rem auto !important;
            }

            .stDownloadButton > button {
                background-color: #FF4B4B !important;
                color: white !important;
                padding: 0.5rem 2rem !important;
                border-radius: 25px !important;
                font-weight: 600 !important;
                transition: all 0.3s ease !important;
                border: none !important;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1) !important;
            }

            .stDownloadButton > button:hover {
                background-color: #FF3333 !important;
                transform: translateY(-2px) !important;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.2) !important;
            }

            /* Video card styling */
            .sample-video-card {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 10px;
                padding: 1rem;
                width: 100%;
                max-width: 400px;
                margin: 0 auto;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                transition: transform 0.2s;
            }

            /* Generated video container */
            .generated-video-container {
                width: 100%;
                max-width: 400px;
                margin: 2rem auto;
                padding: 1rem;
            }

            /* Center all content and animations */
            .stApp {
                max-width: 100%;
                margin: 0 auto;
                text-align: center;
            }

            /* Center status messages and emojis */
            .stMarkdown {
                text-align: center;
            }
            
            /* Make status messages stand out */
            .status-message {
                background-color: rgba(255, 255, 255, 0.1);
                padding: 1rem;
                border-radius: 10px;
                margin: 1rem auto;
                max-width: 600px;
                text-align: center;
            }

            /* Video duration warning */
            .duration-warning {
                color: #ff4b4b;
                background-color: rgba(255, 75, 75, 0.1);
                padding: 0.5rem;
                border-radius: 5px;
                margin: 0.5rem auto;
                max-width: 600px;
                font-weight: bold;
                text-align: center;
            }

            /* Center emojis and make them larger */
            .emoji-large {
                font-size: 2rem;
                text-align: center;
                display: block;
                margin: 1rem auto;
            }
            </style>
        """, unsafe_allow_html=True)
        
        # Title and description
        st.title("🎬 AI Video Commentary Bot")
        st.markdown("<div class='emoji-large'>✨</div>", unsafe_allow_html=True)
        st.markdown("""
            Transform your videos with AI-powered commentary in multiple styles and languages.
            Upload a video or provide a URL to get started!
        """)
        
        # Add duration warning
        st.markdown("<div class='duration-warning'>⚠️ Videos must be 2 minutes or shorter</div>", unsafe_allow_html=True)
        
        # Update status messages to use centered styling
        if st.session_state.get('status'):
            st.markdown(f"<div class='status-message'>{st.session_state.status}</div>", unsafe_allow_html=True)
        
        # Sidebar for settings
        with st.sidebar:
            st.header("⚙️ Settings")
            
            # AI Model selection first
            st.subheader("AI Model")
            llm = st.selectbox(
                "Choose AI model",
                options=["openai", "deepseek"],
                format_func=lambda x: "🧠 OpenAI GPT-4" if x == "openai" else "🤖 Deepseek",
                key="llm"
            )
            
            # Language selection with model compatibility check
            st.subheader("Language")
            available_languages = ["en", "ur"] if llm == "openai" else ["en"]
            language = st.selectbox(
                "Choose language",
                options=available_languages,
                format_func=lambda x: {
                    "en": "🇬🇧 English - Default language",
                    "ur": "🇵🇰 Urdu - اردو"
                }[x],
                key="language"
            )
            
            # Add warning if trying to use Urdu with Deepseek
            if llm == "deepseek" and language == "ur":
                st.warning("⚠️ Urdu language requires OpenAI GPT-4")
            
            # Style selection
            st.subheader("Commentary Style")
            style = st.selectbox(
                "Choose your style",
                options=["news", "funny", "nature", "infographic"],
                format_func=lambda x: {
                    "news": "📰 News - Professional reporting",
                    "funny": "😄 Funny - Humorous commentary",
                    "nature": "🌿 Nature - Documentary style",
                    "infographic": "📊 Infographic - Educational"
                }[x],
                key="style"
            )
            
            # Add style description
            style_descriptions = {
                "news": "Clear, objective reporting with professional tone",
                "funny": "Light-hearted, entertaining commentary with humor",
                "nature": "Descriptive narration with scientific insights",
                "infographic": "Educational content with clear explanations"
            }
            st.caption(style_descriptions[style])
            
            # Update settings in session state and bot's user settings
            user_id = 0  # Default user ID for Streamlit interface
            init_bot().update_user_setting(user_id, 'style', style)
            init_bot().update_user_setting(user_id, 'llm', llm)
            init_bot().update_user_setting(user_id, 'language', language)
            st.session_state.settings = init_bot().get_user_settings(user_id)
        
        # Add these classes and process_video function before the tab sections
        class StreamlitMessage:
            """Mock Telegram message for status updates"""
            def __init__(self):
                self.message_id = 0
                self.text = ""
                self.video = None
                self.file_id = None
                self.file_name = None
                self.mime_type = None
                self.file_size = None
                self.download_placeholder = st.empty()
                self.video_placeholder = st.empty()
                self.status_placeholder = st.empty()
                self.output_filename = None
                
            async def reply_text(self, text, **kwargs):
                logger.info(f"Status update: {text}")
                self.text = text
                st.session_state.status = text
                self.status_placeholder.markdown(f"🔄 {text}")
                return self
                
            async def edit_text(self, text, **kwargs):
                return await self.reply_text(text)
                
            async def reply_video(self, video, caption=None, **kwargs):
                logger.info("Handling video reply")
                try:
                    if hasattr(video, 'read'):
                        video_data = video.read()
                        self.output_filename = getattr(video, 'name', None)
                    elif isinstance(video, str) and os.path.exists(video):
                        self.output_filename = video
                        with open(video, 'rb') as f:
                            video_data = f.read()
                    else:
                        logger.error("Invalid video format")
                        st.error("Invalid video format")
                        return self
                    
                    # Store video data in session state
                    st.session_state.processed_video = video_data
                    
                    # Display video with download button
                    self.video_placeholder.markdown("<div class='generated-video-container'>", unsafe_allow_html=True)
                    if caption:
                        self.video_placeholder.markdown(f"### {caption}")
                    self.video_placeholder.video(video_data)
                    
                    # Add download button with unique key
                    self.video_placeholder.download_button(
                        label="⬇️ Download Enhanced Video",
                        data=video_data,
                        file_name="enhanced_video.mp4",
                        mime="video/mp4",
                        help="Click to download the enhanced video with AI commentary",
                        key="download_button_reply"
                    )
                    
                    self.video_placeholder.markdown("</div>", unsafe_allow_html=True)
                    return self
                    
                except Exception as e:
                    logger.error(f"Error in reply_video: {str(e)}")
                    st.error(f"Error displaying video: {str(e)}")
                    return self

        class StreamlitUpdate:
            """Mock Telegram Update for bot compatibility"""
            def __init__(self):
                logger.info("Initializing StreamlitUpdate")
                self.effective_user = type('User', (), {'id': 0})
                self.message = StreamlitMessage()
                self.effective_message = self.message

        class StreamlitContext:
            """Mock Telegram context"""
            def __init__(self):
                logger.info("Initializing StreamlitContext")
                self.bot = type('MockBot', (), {
                    'get_file': lambda *args, **kwargs: None,
                    'send_message': lambda *args, **kwargs: None,
                    'edit_message_text': lambda *args, **kwargs: None,
                    'send_video': lambda *args, **kwargs: None,
                    'send_document': lambda *args, **kwargs: None
                })()
                self.args = []
                self.matches = None
                self.user_data = {}
                self.chat_data = {}
                self.bot_data = {}

        async def process_video():
            # Check if already processing and reset if stuck
            if st.session_state.is_processing:
                # If stuck for more than 5 minutes, reset
                if hasattr(st.session_state, 'processing_start_time'):
                    if (datetime.now() - st.session_state.processing_start_time).total_seconds() > 300:
                        st.session_state.is_processing = False
                        logger.warning("Reset stuck processing state")
                    else:
                        st.warning("⚠️ Already processing a video. Please wait.")
                        return
                else:
                    st.session_state.is_processing = False
            
            try:
                # Set processing start time
                st.session_state.processing_start_time = datetime.now()
                st.session_state.is_processing = True
                
                update = StreamlitUpdate()
                context = StreamlitContext()
                
                # Create placeholders for status and video
                status_placeholder = st.empty()
                video_container = st.empty()
                
                # Show processing status
                status_placeholder.info("🎬 Starting video processing...")
                
                if video_url:
                    logger.info(f"Processing video URL: {video_url}")
                    await bot.process_video_from_url(update, context, video_url)
                elif uploaded_file:
                    logger.info(f"Processing uploaded file: {uploaded_file.name}")
                    status_placeholder.info("📥 Processing uploaded video...")
                    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                        tmp.write(uploaded_file.getbuffer())
                        await bot.process_video_file(update, context, tmp.name, update.message)
                
                # Check if video was processed successfully
                if st.session_state.get('processed_video'):
                    status_placeholder.success("✅ Processing complete!")
                else:
                    logger.error("No video data found after processing")
                    status_placeholder.error("❌ Failed to generate video")
                
            except Exception as e:
                logger.error(f"Error processing video: {str(e)}")
                status_placeholder.error(f"❌ Error processing video: {str(e)}")
            finally:
                # Clear processing state
                st.session_state.is_processing = False
                if hasattr(st.session_state, 'processing_start_time'):
                    delattr(st.session_state, 'processing_start_time')
                cleanup_memory(force=True)

        # Main content area with responsive containers
        tab1, tab2 = st.tabs(["🔗 Video URL", "🎥 Sample Videos"])
        
        # Video URL Tab
        with tab1:
            st.markdown("<div class='url-input-container'>", unsafe_allow_html=True)
            video_url = st.text_input(
                "Enter video URL",
                placeholder="https://example.com/video.mp4",
                help="Support for YouTube, Vimeo, TikTok, and more",
                label_visibility="collapsed"
            )
            
            if video_url:
                if st.button("Process URL", key="process_url"):
                    if not video_url.startswith(('http://', 'https://')):
                        st.error("❌ Please provide a valid URL starting with http:// or https://")
                    else:
                        try:
                            if not st.session_state.is_processing:
                                st.session_state.progress = 0
                                st.session_state.status = "Starting video processing..."
                                
                                # Convert x.com to twitter.com if needed
                                if 'x.com' in video_url:
                                    video_url = video_url.replace('x.com', 'twitter.com')
                                    st.info("🔄 Converting X.com URL to Twitter format...")
                                
                                asyncio.run(process_video())
                            else:
                                st.warning("⚠️ Already processing a video. Please wait.")
                        except ValueError as ve:
                            # Handle specific error messages from download step
                            error_msg = str(ve).lower()
                            logger.error(f"Validation error: {error_msg}")
                            
                            # Show appropriate error message with guidance
                            if "authentication" in error_msg or "nsfw" in error_msg:
                                st.error(
                                    "❌ Authentication Required\n\n"
                                    "This content requires authentication because:\n"
                                    "• It may be age-restricted (NSFW)\n"
                                    "• It's from a private account\n"
                                    "• The tweet is protected\n\n"
                                    "Try:\n"
                                    "• Using a different video\n"
                                    "• Logging into Twitter to view the content first\n"
                                    "• Checking if you have permission to view this content"
                                )
                            else:
                                st.error(f"❌ {str(ve)}")
                            st.session_state.is_processing = False
                            
                        except Exception as e:
                            logger.error(f"Error in process_url: {str(e)}")
                            # Check for common error patterns
                            error_msg = str(e).lower()
                            
                            if "tweet" in error_msg or "twitter" in error_msg:
                                if "unavailable" in error_msg or "404" in error_msg:
                                    st.error(
                                        "❌ Tweet Not Found\n\n"
                                        "This tweet is not available because:\n"
                                        "• The tweet was deleted\n"
                                        "• The account was suspended\n"
                                        "• The URL is incorrect\n\n"
                                        "Try:\n"
                                        "• Checking if the tweet still exists\n"
                                        "• Copying the URL again\n"
                                        "• Using a different video"
                                    )
                                elif "private" in error_msg or "protected" in error_msg:
                                    st.error(
                                        "❌ Private Content\n\n"
                                        "Cannot access this tweet because:\n"
                                        "• The account is private\n"
                                        "• The tweets are protected\n"
                                        "• You need to be following the account\n\n"
                                        "Try:\n"
                                        "• Following the account first\n"
                                        "• Using a public video instead\n"
                                        "• Asking permission from the content owner"
                                    )
                                else:
                                    st.error(
                                        "❌ Twitter Error\n\n"
                                        "Failed to download the tweet because:\n"
                                        "• The content may be restricted\n"
                                        "• The tweet might be unavailable\n"
                                        "• There could be a temporary issue\n\n"
                                        "Try:\n"
                                        "• Checking if the tweet is still accessible\n"
                                        "• Waiting a few minutes and trying again\n"
                                        "• Using a different video"
                                    )
                            elif "youtube" in error_msg:
                                if "private" in error_msg:
                                    st.error(
                                        "❌ Private YouTube Video\n\n"
                                        "This video is not accessible because:\n"
                                        "• It's set to private\n"
                                        "• It's unlisted and requires a direct link\n"
                                        "• You need specific permissions\n\n"
                                        "Try:\n"
                                        "• Checking if you have the correct link\n"
                                        "• Using a public video instead\n"
                                        "• Asking the video owner for permission"
                                    )
                                elif "age" in error_msg:
                                    st.error(
                                        "❌ Age-Restricted Content\n\n"
                                        "Cannot access this video because:\n"
                                        "• It's age-restricted content\n"
                                        "• You need to be logged in\n"
                                        "• Age verification is required\n\n"
                                        "Try:\n"
                                        "• Using a different video\n"
                                        "• Choosing non-age-restricted content\n"
                                        "• Verifying your age on YouTube first"
                                    )
                                else:
                                    st.error(
                                        "❌ YouTube Error\n\n"
                                        "Failed to download the video because:\n"
                                        "• The video might be unavailable\n"
                                        "• It could be region-restricted\n"
                                        "• There might be a temporary issue\n\n"
                                        "Try:\n"
                                        "• Checking if the video is still available\n"
                                        "• Using a VPN if it's region-restricted\n"
                                        "• Choosing a different video"
                                    )
                            else:
                                st.error(
                                    "❌ Download Error\n\n"
                                    "Failed to process the video because:\n"
                                    "• The URL might be invalid\n"
                                    "• The content is not accessible\n"
                                    "• The video might be too long\n\n"
                                    "Try:\n"
                                    "• Checking if the URL is correct\n"
                                    "• Ensuring the video is public\n"
                                    "• Using a video under 2 minutes"
                                )
                            st.session_state.is_processing = False
            st.markdown("</div>", unsafe_allow_html=True)
            
        # Sample Videos Tab
        with tab2:
            st.markdown("<div class='sample-video-grid'>", unsafe_allow_html=True)
            
            # Get list of sample videos
            sample_videos_dir = Path("sample_generated_videos")
            if sample_videos_dir.exists():
                sample_videos = list(sample_videos_dir.glob("*.mp4"))
                
                # Display each sample video in a card
                for video_path in sample_videos:
                    st.markdown("<div class='sample-video-card'>", unsafe_allow_html=True)
                    st.video(str(video_path))
                    st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.info("No sample videos available")
            
            st.markdown("</div>", unsafe_allow_html=True)
        
        # Add memory monitoring
        if st.sidebar.checkbox("Show Memory Usage"):
            process = psutil.Process()
            memory_info = process.memory_info()
            st.sidebar.write(f"Memory Usage: {memory_info.rss / 1024 / 1024:.2f} MB")
            if st.sidebar.button("Force Cleanup"):
                cleanup_memory()
                st.sidebar.success("Memory cleaned up!")
        
        # Add this section after the tabs to ensure video persists
        if st.session_state.get('processed_video'):
            st.markdown("<div class='generated-video-container'>", unsafe_allow_html=True)
            st.video(st.session_state.processed_video)
            
            # Add YouTube upload section
            with st.expander("📤 Upload to YouTube"):
                if not st.session_state.google_auth:
                    st.warning("⚠️ Please sign in with Google to upload videos to YouTube")
                else:
                    st.info("Your video title and description will be automatically generated using AI")
                    
                    # Video upload form
                    with st.form("youtube_upload_form"):
                        # Privacy setting only
                        privacy = st.selectbox(
                            "Privacy Setting",
                            options=['private', 'unlisted', 'public'],
                            index=0,
                            help="Choose who can view your video"
                        )
                        
                        submit = st.form_submit_button("Upload to YouTube")
                        
                        if submit:
                            try:
                                # Initialize YouTube uploader with user's credentials
                                uploader = YouTubeUploader(credentials=st.session_state.google_auth)
                                auth_success = uploader.authenticate()
                                
                                if not auth_success:
                                    st.error("❌ Failed to authenticate with YouTube. Please try signing in again.")
                                    logger.error("YouTube authentication failed")
                                    st.stop()
                                
                                # Store the authenticated uploader in session state
                                st.session_state.youtube_uploader = uploader
                                
                                # Save video to temporary file
                                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
                                    tmp.write(st.session_state.processed_video)
                                    video_path = tmp.name
                                
                                # Show upload progress
                                progress_bar = st.progress(0)
                                status_text = st.empty()
                                status_text.text("Starting upload...")
                                
                                # Get video metadata from session state
                                video_metadata = {
                                    'description': st.session_state.get('video_description', ''),
                                    'duration': st.session_state.get('video_duration', 0),
                                    'source_url': st.session_state.get('video_url', '')
                                }
                                
                                try:
                                    # Upload to YouTube with auto-generated content
                                    result = uploader.upload_video(
                                        video_path=video_path,
                                        video_metadata=video_metadata,
                                        privacy=privacy
                                    )
                                    
                                    if result['success']:
                                        st.success(
                                            f"✅ Video uploaded successfully!\n\n"
                                            f"📝 Title: {result['title']}\n"
                                            f"🔗 Video URL: {result['url']}\n"
                                            f"🔒 Privacy: {result['privacy']}\n\n"
                                            f"Description Preview:\n{result['description'][:200]}..."
                                        )
                                        # Add direct link button
                                        st.markdown(f"[▶️ Watch on YouTube]({result['url']})")
                                    else:
                                        if result.get('reason') == 'channelRequired':
                                            # Show channel creation prompt
                                            st.error("❌ YouTube Channel Required")
                                            st.warning(
                                                "Before uploading videos, you need to create a YouTube channel. "
                                                "This only needs to be done once."
                                            )
                                            channel_url = result.get('create_channel_url', 'https://www.youtube.com/create_channel')
                                            st.markdown(
                                                f"""
                                                1. [Click here to create your YouTube channel]({channel_url})
                                                2. Follow the steps to set up your channel
                                                3. Come back here and try uploading again
                                                """
                                            )
                                            # Add help text
                                            with st.expander("Need help?"):
                                                st.markdown("""
                                                    ### Creating a YouTube Channel
                                                    1. Click the link above to go to YouTube
                                                    2. Sign in with your Google account if needed
                                                    3. Click 'Create Channel'
                                                    4. Follow the setup steps
                                                    5. Return here when finished
                                                    
                                                    Your channel only needs to be created once, and then you can upload as many videos as you want!
                                                """)
                                        else:
                                            st.error(
                                                f"❌ Upload failed: {result.get('error', 'Unknown error')}\n"
                                                f"Reason: {result.get('reason', 'Unknown')}"
                                            )
                                finally:
                                    # Cleanup temporary file
                                    if os.path.exists(video_path):
                                        os.unlink(video_path)
                                
                            except Exception as e:
                                st.error(f"❌ Error during upload: {str(e)}")
                                logger.error(f"YouTube upload error: {str(e)}", exc_info=True)
            
            # Add download button after YouTube section
            st.markdown("<div class='download-button-container'>", unsafe_allow_html=True)
            st.download_button(
                label="⬇️ Download Enhanced Video",
                data=st.session_state.processed_video,
                file_name="enhanced_video.mp4",
                mime="video/mp4",
                help="Click to download the enhanced video with AI commentary",
                key="download_button_persist"
            )
            st.markdown("</div></div>", unsafe_allow_html=True)
        
        # Help section
        with st.expander("ℹ️ Help & Information"):
            st.markdown("""
                ### How to Use
                1. Choose your preferred settings in the sidebar
                2. Upload a video file or provide a video URL
                3. Click the process button and wait for the magic!
                
                ### Features
                - Multiple commentary styles
                - Support for different languages
                - Choice of AI models
                - Professional voice synthesis
                
                ### Limitations
                - Maximum video size: 50MB
                - Maximum duration: 5 minutes
                - Supported formats: MP4, MOV, AVI
                
                ### Need Help?
                If you encounter any issues, try:
                - Using a shorter video
                - Converting your video to MP4 format
                - Checking your internet connection
                - Refreshing the page
            """)
        
    except Exception as e:
        logger.error(f"Initialization error: {e}", exc_info=True)
        st.error(f"⚠️ Failed to initialize application: {str(e)}")
        st.stop()
        
except Exception as e:
    logger.error(f"Critical error: {e}", exc_info=True)
    # If streamlit itself fails to import or initialize
    print(f"Critical error: {e}")
    sys.exit(1) 