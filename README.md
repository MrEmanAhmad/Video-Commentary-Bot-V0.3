# Video Automator By Mani 🎬

A powerful AI-powered video commentary bot that automatically generates engaging commentary for your videos. Built with Streamlit, OpenAI, DeepSeek, and Google Cloud technologies.

## Features ✨

- **Multiple Commentary Styles**: Choose from various commentary styles to match your content
- **Multi-Language Support**: Generate commentary in different languages
- **AI Model Selection**: Choose between different AI models for generation
- **Professional Voice Synthesis**: High-quality voice generation
- **Responsive Design**: Works perfectly on all devices
- **Sample Videos**: View example videos with generated commentary

## Requirements 📋

- Python 3.8+
- OpenAI API Key
- DeepSeek API Key
- Google Cloud Credentials
- FFmpeg (for video processing)

## Installation 🚀

1. Clone the repository:
```bash
git clone https://github.com/MrEmanAhmad/VideoAuotmatorByMani.git
cd VideoAuotmatorByMani
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
   - Create a `.env` file based on `.env.example`
   - Add your API keys and credentials

## Usage 💡

1. Run the Streamlit app:
```bash
streamlit run streamlit_app.py
```

2. Open your browser and navigate to the provided URL
3. Choose your preferred settings in the sidebar
4. Enter a video URL or view sample videos
5. Click process and wait for the magic!

## Limitations ⚠️

- Maximum video size: 50MB
- Maximum duration: 5 minutes
- Supported formats: MP4, MOV, AVI

## Contributing 🤝

Contributions are welcome! Please feel free to submit a Pull Request.

## License 📄

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author ✍️

**Mani** - [MrEmanAhmad](https://github.com/MrEmanAhmad)

## Acknowledgments 🙏

- OpenAI for GPT models
- DeepSeek for AI capabilities
- Google Cloud for voice synthesis
- Streamlit for the awesome web framework 