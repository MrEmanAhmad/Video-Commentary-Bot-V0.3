"""
YouTube upload module for handling video uploads to YouTube
"""

import os
import pickle
import logging
import json
import tempfile
from pathlib import Path
from typing import Optional, Dict
from openai import OpenAI
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
import cv2
import re

logger = logging.getLogger(__name__)

class YouTubeUploader:
    """Handles YouTube video uploads."""
    
    def __init__(self, credentials=None):
        """
        Initialize the YouTube uploader.
        
        Args:
            credentials: Optional Google OAuth2 credentials
        """
        self.youtube = None
        self.credentials = credentials
        self.user_email = None
        
        # Initialize DeepSeek client
        try:
            with open('railway.json', 'r') as f:
                config = json.load(f)
                self.deepseek_client = OpenAI(
                    api_key=config['DEEPSEEK_API_KEY'],
                    base_url="https://api.deepseek.com"
                )
        except Exception as e:
            logger.error(f"Failed to initialize DeepSeek client: {e}")
            self.deepseek_client = None
        
        # If modifying these scopes, delete the token.pickle file
        self.SCOPES = [
            'https://www.googleapis.com/auth/youtube',
            'https://www.googleapis.com/auth/youtube.upload',
            'https://www.googleapis.com/auth/userinfo.email',
            'https://www.googleapis.com/auth/userinfo.profile',
            'openid'
        ]
        
        # Store credentials in user's home directory
        self.tokens_dir = Path.home() / '.video_bot' / 'tokens'
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        
        # Try to load client secrets from environment/railway.json
        self.client_secrets = None
        try:
            logger.info("Attempting to load YouTube client secrets...")
            # First try environment variable
            if os.getenv('YOUTUBE_CLIENT_SECRETS'):
                logger.info("Found YOUTUBE_CLIENT_SECRETS in environment variables")
                secrets_str = os.getenv('YOUTUBE_CLIENT_SECRETS')
                # Handle both string and object formats
                if isinstance(secrets_str, str):
                    try:
                        logger.info("Parsing YOUTUBE_CLIENT_SECRETS string...")
                        self.client_secrets = json.loads(secrets_str)
                        logger.info("Successfully parsed YOUTUBE_CLIENT_SECRETS")
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse YOUTUBE_CLIENT_SECRETS environment variable: {e}")
                else:
                    logger.info("Using YOUTUBE_CLIENT_SECRETS as object directly")
                    self.client_secrets = secrets_str
            else:
                # Try railway.json
                railway_path = Path("railway.json")
                if railway_path.exists():
                    logger.info("Loading credentials from railway.json")
                    with open(railway_path, 'r') as f:
                        config = json.load(f)
                        if 'YOUTUBE_CLIENT_SECRETS' in config:
                            secrets_data = config['YOUTUBE_CLIENT_SECRETS']
                            logger.info(f"Found YOUTUBE_CLIENT_SECRETS in railway.json, type: {type(secrets_data)}")
                            # Handle both string and object formats
                            if isinstance(secrets_data, str):
                                try:
                                    logger.info("Parsing YOUTUBE_CLIENT_SECRETS string from railway.json...")
                                    self.client_secrets = json.loads(secrets_data)
                                    logger.info("Successfully parsed YOUTUBE_CLIENT_SECRETS from railway.json")
                                except json.JSONDecodeError as e:
                                    logger.error(f"Failed to parse YOUTUBE_CLIENT_SECRETS from railway.json: {e}")
                            else:
                                logger.info("Using YOUTUBE_CLIENT_SECRETS from railway.json as object directly")
                                self.client_secrets = secrets_data
                        else:
                            logger.warning("YOUTUBE_CLIENT_SECRETS not found in railway.json")
                else:
                    logger.warning("railway.json not found")
                    
            # Validate client secrets format
            if self.client_secrets:
                logger.info(f"Client secrets keys: {list(self.client_secrets.keys())}")
                if 'installed' not in self.client_secrets and 'web' not in self.client_secrets:
                    logger.error("Invalid client secrets format: missing both 'installed' and 'web' keys")
                    logger.error(f"Available keys: {list(self.client_secrets.keys())}")
                    self.client_secrets = None
                else:
                    logger.info("Client secrets format validation passed")
                    # Log the type of credentials
                    if 'installed' in self.client_secrets:
                        logger.info("Using 'installed' type credentials")
                    elif 'web' in self.client_secrets:
                        logger.info("Using 'web' type credentials")
                    
                    # Validate required fields
                    required_fields = ['client_id', 'project_id', 'auth_uri', 'token_uri', 'client_secret']
                    creds_section = self.client_secrets.get('installed') or self.client_secrets.get('web', {})
                    missing_fields = [field for field in required_fields if field not in creds_section]
                    if missing_fields:
                        logger.error(f"Missing required fields in credentials: {missing_fields}")
                    else:
                        logger.info("All required credential fields are present")
                
        except Exception as e:
            logger.error(f"Error loading client secrets: {str(e)}", exc_info=True)
    
    def _get_token_path(self) -> Path:
        """Get the token path for the current user."""
        if not self.user_email:
            # Extract email from credentials if available
            try:
                import google.auth.transport.requests
                import google.oauth2.id_token
                request = google.auth.transport.requests.Request()
                id_info = google.oauth2.id_token.verify_oauth2_token(
                    self.credentials.id_token, request
                )
                self.user_email = id_info.get('email')
            except Exception as e:
                logger.warning(f"Could not get user email: {e}")
                return self.tokens_dir / 'default_token.pickle'
        
        # Use email as filename (sanitized)
        safe_email = self.user_email.replace('@', '_at_').replace('.', '_dot_')
        return self.tokens_dir / f'{safe_email}_token.pickle'

    def authenticate(self, client_secrets_file: Optional[str] = None) -> bool:
        """
        Authenticate with YouTube using OAuth 2.0.
        
        Args:
            client_secrets_file: Optional path to client secrets JSON file
            
        Returns:
            bool: True if authentication successful
        """
        try:
            logger.info("Starting YouTube authentication process...")
            
            # Use provided credentials if available
            if self.credentials:
                logger.info("Using provided credentials")
                if not self.credentials.valid:
                    if self.credentials.expired and self.credentials.refresh_token:
                        logger.info("Refreshing expired credentials")
                        self.credentials.refresh(Request())
                    else:
                        logger.error("Invalid credentials and cannot refresh")
                        return False
            else:
                # Get token path for current user
                token_path = self._get_token_path()
                logger.info(f"Using token path: {token_path}")
                
                # Load existing credentials if available
                if token_path.exists():
                    logger.info(f"Found existing token at {token_path}")
                    with open(token_path, 'rb') as token:
                        self.credentials = pickle.load(token)
                    logger.info(f"Loaded credentials valid: {self.credentials.valid if self.credentials else False}")
                
                # If no valid credentials available, authenticate
                if not self.credentials or not self.credentials.valid:
                    logger.info("No valid credentials, starting OAuth flow...")
                    if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                        logger.info("Refreshing expired credentials")
                        self.credentials.refresh(Request())
                    else:
                        # Use provided file or embedded credentials
                        if client_secrets_file:
                            logger.info(f"Using provided client secrets file: {client_secrets_file}")
                            if not os.path.exists(client_secrets_file):
                                raise FileNotFoundError(f"Client secrets file not found: {client_secrets_file}")
                            flow = InstalledAppFlow.from_client_secrets_file(
                                client_secrets_file, self.SCOPES)
                        elif self.client_secrets:
                            logger.info("Using embedded client secrets")
                            # Create temporary secrets file with proper format
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                                # Ensure proper format for client secrets
                                if 'installed' in self.client_secrets:
                                    secrets_content = {'installed': self.client_secrets['installed']}
                                elif 'web' in self.client_secrets:
                                    secrets_content = {'web': self.client_secrets['web']}
                                else:
                                    raise ValueError("Invalid client secrets format")
                                
                                json.dump(secrets_content, f)
                                temp_secrets_path = f.name
                                logger.info(f"Created temporary secrets file: {temp_secrets_path}")
                            
                            try:
                                flow = InstalledAppFlow.from_client_secrets_file(
                                    temp_secrets_path, self.SCOPES)
                                logger.info("Successfully created OAuth flow")
                            except Exception as e:
                                logger.error(f"Error creating OAuth flow: {str(e)}", exc_info=True)
                                raise
                            finally:
                                if os.path.exists(temp_secrets_path):
                                    os.unlink(temp_secrets_path)
                                    logger.info("Cleaned up temporary secrets file")
                        else:
                            logger.error("No client secrets available")
                            raise ValueError("No client secrets available")
                        
                        logger.info("Starting local server OAuth flow...")
                        self.credentials = flow.run_local_server(port=0)
                        logger.info("OAuth flow completed successfully")
                        
                        # Get user email after authentication
                        try:
                            import google.auth.transport.requests
                            import google.oauth2.id_token
                            request = google.auth.transport.requests.Request()
                            id_info = google.oauth2.id_token.verify_oauth2_token(
                                self.credentials.id_token, request
                            )
                            self.user_email = id_info.get('email')
                            logger.info(f"Authenticated user email: {self.user_email}")
                        except Exception as e:
                            logger.warning(f"Could not get user email after authentication: {e}")
                    
                    # Save credentials for future use
                    token_path = self._get_token_path()
                    logger.info(f"Saving credentials to {token_path}")
                    with open(token_path, 'wb') as token:
                        pickle.dump(self.credentials, token)
            
            # Build YouTube service
            logger.info("Building YouTube service...")
            self.youtube = build('youtube', 'v3', credentials=self.credentials)
            logger.info("YouTube service built successfully")
            return True
            
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}", exc_info=True)
            return False
    
    def _generate_content(self, video_metadata: Dict) -> Dict[str, str]:
        """Generate video title and description using DeepSeek."""
        try:
            if not self.deepseek_client:
                raise ValueError("DeepSeek client not initialized")

            # Extract metadata
            original_title = video_metadata.get('title', '')
            original_description = video_metadata.get('description', '')
            vision_analysis = video_metadata.get('vision_analysis', {})

            # Create a prompt that prioritizes original content
            prompt = f"""
            Create an engaging YouTube title and description based primarily on this video content:

            MAIN VIDEO CONTENT:
            Title: {original_title}
            Description: {original_description}

            SUPPORTING VISUAL DETAILS:
            {vision_analysis}

            REQUIREMENTS:

            1. Title (max 100 chars):
               - MUST maintain the core topic from the original title
               - Add 2-3 relevant emojis
               - Make it engaging while keeping the main subject
               Example: If original is about a polar bear crossing ice, the new title must also be about that specific action

            2. Description (max 500 chars):
               - First line MUST describe the exact action/subject from original title
               - Use supporting visual details to enhance the description
               - Add relevant hashtags at the end
               - Keep focus on the specific content, not generic nature descriptions

            Format exactly like this:
            *Title:* "Your Specific Title Here 🎥"

            *Description:*
            Your specific description focusing on the main content.
            Add supporting details from visual analysis.

            #RelevantHashtag #ContentSpecific #Trending

            IMPORTANT: Stay focused on the specific content (e.g., if it's about a polar bear crossing ice, don't make it generic about nature)
            """

            response = self.deepseek_client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a content specialist who creates engaging titles and descriptions while maintaining focus on the specific video content. Never generalize or deviate from the main subject."
                    },
                    {"role": "user", "content": prompt}
                ],
                stream=False
            )

            content = response.choices[0].message.content
            
            try:
                # Extract title between *Title:* and next newline
                title_match = re.search(r'\*Title:\*\s*"([^"]+)"', content)
                if not title_match:
                    raise ValueError("Could not extract title from response")
                title = title_match.group(1)

                # Extract description between *Description:* and hashtags
                desc_match = re.search(r'\*Description:\*\s*(.+?)(?=\s*#\w+)', content, re.DOTALL)
                if not desc_match:
                    raise ValueError("Could not extract description from response")
                description = desc_match.group(1).strip()

                # Extract hashtags
                hashtags = ' '.join(re.findall(r'#\w+', content))
                if not hashtags:
                    # Generate hashtags based on original content
                    main_subject = original_title.split('-')[0].strip()
                    hashtags = f"#{main_subject.replace(' ', '')} #Wildlife #Educational"
                
                # Combine description with hashtags
                full_description = f"{description}\n\n{hashtags}"

                # Log the generated content for debugging
                logger.info(f"Generated Title: {title}")
                logger.info(f"Generated Description: {full_description[:100]}...")
                
                return {
                    'title': title[:100],  # Ensure title length limit
                    'description': full_description[:500]  # Ensure description length limit
                }
            
            except Exception as e:
                logger.error(f"Error parsing DeepSeek response: {e}")
                logger.error(f"Raw response: {content}")
                # Use original title with minimal enhancement
                fallback_title = f"{original_title} 🎥"
                return {
                    'title': fallback_title,
                    'description': f"{original_description}\n\nWatch this incredible moment in nature! 🎬\n\n#{original_title.split()[0]} #Wildlife #Educational"
                }
            
        except Exception as e:
            logger.error(f"Error generating content with DeepSeek: {e}")
            return {
                'title': f"{original_title} 🎥",
                'description': f"{original_description}\n\nAn amazing wildlife moment! 🌿\n\n#{original_title.split()[0]} #Wildlife #Educational"
            }

    def _check_channel_exists(self) -> bool:
        """Check if user has a YouTube channel."""
        try:
            # Try to get channel info
            channels_response = self.youtube.channels().list(
                part='id',
                mine=True
            ).execute()
            
            return bool(channels_response.get('items'))
        except Exception as e:
            logger.error(f"Error checking channel existence: {e}")
            return False

    def _create_channel_url(self) -> str:
        """Generate YouTube channel creation URL."""
        return "https://www.youtube.com/create_channel"

    def upload_video(self, video_path: str, video_metadata: Optional[Dict] = None, 
                    privacy: str = 'private', tags: Optional[list] = None) -> Dict:
        """
        Upload a video to YouTube with auto-generated content.
        
        Args:
            video_path: Path to video file
            video_metadata: Optional metadata about the video
            privacy: Privacy status ('private', 'unlisted', or 'public')
            tags: List of video tags
            
        Returns:
            Dict containing upload response or error details
        """
        if not self.youtube:
            raise ValueError("YouTube service not initialized. Please authenticate first.")
        
        try:
            # Check if user has a YouTube channel
            if not self._check_channel_exists():
                logger.warning("No YouTube channel found for this account")
                return {
                    'success': False,
                    'error': 'No YouTube channel found',
                    'reason': 'channelRequired',
                    'create_channel_url': self._create_channel_url(),
                    'message': 'Please create a YouTube channel first by visiting the provided URL'
                }
            
            # Check if video is vertical (Shorts)
            cap = cv2.VideoCapture(video_path)
            width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / cap.get(cv2.CAP_PROP_FPS)
            cap.release()
            
            is_shorts = height > width  # Vertical video
            
            # Validate Shorts requirements
            if is_shorts:
                if duration > 60:
                    logger.warning("Video duration exceeds maximum allowed for Shorts (60 seconds)")
                logger.info(f"Processing vertical video as Shorts (duration: {duration:.2f}s, ratio: {height/width:.2f})")
            
            # Generate content using DeepSeek
            content = self._generate_content(video_metadata or {})
            
            # Initialize tags list
            if tags is None:
                tags = []
            
            # Add Shorts-specific metadata
            if is_shorts:
                # Add Shorts tags
                shorts_tags = ['Shorts', 'YouTubeShorts', 'shortsvideo']
                tags.extend(shorts_tags)
                
                # Ensure #Shorts is at the beginning of the title
                if not content['title'].startswith('#Shorts'):
                    content['title'] = f"#Shorts {content['title']}"
                
                # Add #Shorts at the beginning of description
                content['description'] = f"#Shorts\n\n{content['description']}"
            
            # Prepare video metadata
            body = {
                'snippet': {
                    'title': content['title'][:100],  # Ensure title length limit
                    'description': content['description'],
                    'tags': list(set(tags)),  # Remove duplicate tags
                    'categoryId': '22',  # People & Blogs category
                },
                'status': {
                    'privacyStatus': privacy,
                    'selfDeclaredMadeForKids': False,
                    'license': 'youtube'
                }
            }
            
            # Log metadata for debugging
            logger.info(f"Uploading video with metadata:")
            logger.info(f"Title: {body['snippet']['title']}")
            logger.info(f"Tags: {body['snippet']['tags']}")
            logger.info(f"Is Shorts: {is_shorts}")
            if is_shorts:
                logger.info(f"Video dimensions: {int(width)}x{int(height)}")
                logger.info(f"Duration: {duration:.2f}s")
            
            # Create media file upload
            media = MediaFileUpload(
                video_path,
                mimetype='video/mp4',
                resumable=True,
                chunksize=1024*1024  # 1MB chunks
            )
            
            # Execute upload request with only valid parts
            parts = ['snippet', 'status']
            
            # Execute upload request
            logger.info(f"Starting upload of {'Shorts' if is_shorts else 'regular'} video: {content['title']}")
            request = self.youtube.videos().insert(
                part=','.join(parts),
                body=body,
                media_body=media
            )
            
            # Upload the video
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"Upload progress: {progress}%")
            
            logger.info(f"Upload complete! Video ID: {response['id']}")
            
            # Return upload details
            return {
                'success': True,
                'video_id': response['id'],
                'url': f'https://youtu.be/{response["id"]}',
                'title': content['title'],
                'description': content['description'],
                'privacy': privacy,
                'is_shorts': is_shorts,
                'tags': body['snippet']['tags'],
                'dimensions': f"{int(width)}x{int(height)}",
                'duration': f"{duration:.2f}s"
            }
            
        except HttpError as e:
            error_details = {
                'success': False,
                'error': str(e),
                'reason': e.error_details[0]['reason'] if e.error_details else 'unknown'
            }
            logger.error(f"Upload error: {error_details}")
            return error_details
            
        except Exception as e:
            error_details = {
                'success': False,
                'error': str(e),
                'reason': 'unknown'
            }
            logger.error(f"Unexpected error during upload: {str(e)}")
            return error_details 