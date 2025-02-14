# Use Python 3.10 slim image as base
FROM python:3.10-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    PORT=8501 \
    RAILWAY_ENVIRONMENT=production \
    DEBIAN_FRONTEND=noninteractive \
    # Add OAuth redirect URI environment variable
    OAUTH_REDIRECT_URI="/_stcore/authorize" \
    RAILWAY_PUBLIC_DOMAIN="video-commentary-bot-v03-production.up.railway.app" \
    STREAMLIT_SERVER_ENABLE_STATIC_SERVING=true \
    STREAMLIT_SERVER_BASE_URL_PATH="" \
    STREAMLIT_SERVER_ENABLE_CORS=false \
    STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false \
    STREAMLIT_SERVER_MAX_MESSAGE_SIZE=200 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_THEME_BASE="dark" \
    STREAMLIT_SERVER_COOKIE_SECRET="your-secret-key-here" \
    STREAMLIT_SERVER_COOKIE_EXPIRY_DAYS=30 \
    STREAMLIT_SERVER_ENABLE_WEBSOCKET_COMPRESSION=true \
    STREAMLIT_SERVER_RUN_ON_SAVE=true \
    STREAMLIT_LOGGER_LEVEL="info" \
    STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=true \
    STREAMLIT_CLIENT_TOOLBAR_MODE="minimal" \
    STREAMLIT_GLOBAL_DEVELOPMENT_MODE=false \
    STREAMLIT_GLOBAL_SUPPRESS_DEPRECATION_WARNINGS=true \
    STREAMLIT_GLOBAL_SHOW_WARNING_ON_DIRECT_EXECUTION=false \
    STREAMLIT_GLOBAL_DISABLE_WATCHDOG_WARNING=true \
    STREAMLIT_GLOBAL_SHOW_WIDGET_CALLBACK_WARNING=false \
    STREAMLIT_SERVER_ENABLE_XFRAME_OPTIONS=false \
    STREAMLIT_SERVER_ENABLE_COOKIE_BASED_SESSION_HANDLING=true

# Create a non-root user
RUN useradd -m -s /bin/bash app_user

# Add Chrome repository and install system dependencies
RUN apt-get update && \
    apt-get install -y wget gnupg2 && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    google-chrome-stable \
    chromium-driver \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1-mesa-glx \
    git \
    libmagic1 \
    libpython3-dev \
    build-essential \
    python3-dev \
    pkg-config \
    curl \
    unzip \
    xvfb \
    libxi6 \
    libgconf-2-4 \
    default-jdk \
    apt-transport-https \
    ca-certificates \
    # Video processing dependencies
    libavcodec-extra \
    libavformat-dev \
    libswscale-dev \
    libv4l-dev \
    libxvidcore-dev \
    libx264-dev \
    libatlas-base-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    # Additional dependencies for Python packages
    python3-pip \
    python3-setuptools \
    python3-wheel \
    gcc \
    g++ \
    # Cleanup
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set up Chrome and ChromeDriver
ENV CHROME_BIN=/usr/bin/google-chrome \
    CHROME_PATH=/usr/bin/google-chrome \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver \
    DISPLAY=:99

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with optimizations - split into smaller chunks for better error handling
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    echo "Installing base dependencies..." && \
    pip install --no-cache-dir --verbose numpy==1.24.3 pandas==2.2.3 psutil==5.9.8 python-dotenv==1.0.0 selenium==4.28.1 webdriver-manager==4.0.2 undetected-chromedriver==3.5.5 openai==1.3.5 cloudinary==1.38.0 aiohttp==3.9.3 aiosignal==1.3.2 aiodns==3.1.1 aiolimiter==1.1.1 google-cloud-vision==3.9.0 google-cloud-texttospeech==2.14.1 moviepy==1.0.3 ffmpeg-python==0.2.0 && \
    echo "Installing OpenCV..." && \
    pip install --no-cache-dir --verbose opencv-python-headless==4.11.0.86 && \
    echo "Installing core ML dependencies..." && \
    pip install --no-cache-dir --verbose scikit-image==0.25.1 scipy==1.15.1 && \
    echo "Installing web dependencies..." && \
    pip install --no-cache-dir --verbose streamlit==1.31.0 fastapi==0.115.8 uvicorn==0.34.0 && \
    echo "Installing Google Cloud dependencies..." && \
    pip install --no-cache-dir --verbose \
    google-cloud-vision==3.9.0 \
    google-cloud-texttospeech==2.14.1 \
    google-api-python-client>=2.161.0 \
    google-auth-httplib2>=0.2.0 \
    google-auth-oauthlib>=1.2.1 \
    google-auth>=2.38.0 && \
    echo "Installing Telegram dependencies..." && \
    pip install --no-cache-dir --verbose "python-telegram-bot[job-queue]==20.7" && \
    echo "Installing remaining requirements..." && \
    pip install --no-cache-dir --verbose -r requirements.txt 2>&1 | tee pip_install.log && \
    echo "Installing yt-dlp..." && \
    pip install --no-cache-dir --verbose yt-dlp && \
    # Clean up pip cache
    rm -rf /root/.cache/pip/* && \
    # Pre-compile Python files
    python -m compileall /app

# Create necessary directories with proper structure
RUN mkdir -p \
    /home/app_user/.streamlit \
    /home/app_user/.cache/yt-dlp \
    /home/app_user/.cache/youtube-dl \
    /home/app_user/.cache/selenium \
    /home/app_user/.config/chromium \
    /home/app_user/.config/google-chrome \
    /home/app_user/.video_bot/tokens \
    /app/credentials \
    /app/analysis_temp \
    /app/sample_generated_videos \
    /app/framesAndLogo/Nature \
    /app/framesAndLogo/News \
    /app/framesAndLogo/Funny \
    /app/framesAndLogo/Infographic

# Copy Streamlit config
COPY .streamlit/config.toml /home/app_user/.streamlit/config.toml

# Copy sample generated videos
COPY sample_generated_videos/*.mp4 /app/sample_generated_videos/

# Copy the entire application
COPY . .

# Create example configuration files
RUN cp railway.json.example railway.json || true && \
    mkdir -p credentials && \
    cp credentials/google_credentials.example.json credentials/google_credentials.json || true

# Set proper permissions before switching user
RUN chown -R app_user:app_user \
    /app \
    /home/app_user/.streamlit \
    /home/app_user/.cache \
    /home/app_user/.config \
    /home/app_user/.video_bot \
    && chmod -R 755 /app pipeline \
    && chmod -R 777 \
    /app/credentials \
    /app/analysis_temp \
    /app/sample_generated_videos \
    /app/framesAndLogo \
    /home/app_user/.config \
    /home/app_user/.streamlit \
    /home/app_user/.cache \
    /home/app_user/.video_bot/tokens

# Switch to non-root user
USER app_user

# Set environment variables for the application
ENV HOME=/home/app_user \
    PYTHONPATH=${PYTHONPATH}:/app \
    SELENIUM_CACHE_PATH=/home/app_user/.cache/selenium \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    # OpenCV optimizations
    OPENCV_FFMPEG_CAPTURE_OPTIONS="video_codec;h264_cuvid" \
    OPENCV_VIDEOIO_PRIORITY_BACKEND=2 \
    # FFmpeg optimizations
    FFREPORT=file=/app/analysis_temp/ffmpeg-%p-%t.log \
    # Chrome/Selenium settings
    SELENIUM_HEADLESS=true \
    PYTHONWARNINGS="ignore:Unverified HTTPS request" \
    STREAMLIT_SERVER_COOKIE_SECRET="${STREAMLIT_SERVER_COOKIE_SECRET}" \
    STREAMLIT_SERVER_ENABLE_COOKIE_BASED_SESSION_HANDLING=true \
    STREAMLIT_SERVER_COOKIE_EXPIRY_DAYS=30

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8501}/_stcore/health || exit 1

# Expose the port that will be used by Streamlit
EXPOSE ${PORT:-8501}

# Start Xvfb and run Streamlit with optimized settings
CMD Xvfb :99 -screen 0 1280x1024x24 -ac +extension GLX +render -noreset & \
    streamlit run \
    --server.port=${PORT:-8501} \
    --server.address=0.0.0.0 \
    --server.maxUploadSize=50 \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --server.maxMessageSize=200 \
    --browser.gatherUsageStats=false \
    --theme.base=dark \
    streamlit_app.py 