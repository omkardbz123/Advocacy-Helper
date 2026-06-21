import os
from dotenv import load_dotenv

# Load .env file using absolute path relative to this file's directory
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(dotenv_path=env_path)

class Config:
    # YouTube
    YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY', '')

    # Instagram
    INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME', '')
    INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD', '')

    # Gemini
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

    # NVIDIA
    NVIDIA_API_KEY = os.getenv('NVIDIA_API_KEY', '')
    NVIDIA_API_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
    NVIDIA_MODEL = 'minimaxai/minimax-m3'

    # Cloudflare
    CLOUDFLARE_WORKER_URL = os.getenv('CLOUDFLARE_WORKER_URL', '')
    CLOUDFLARE_API_SECRET = os.getenv('CLOUDFLARE_API_SECRET', '')

    # Admin
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'oma')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'omya28')

    # Paths
    TEMP_MEDIA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_media')
    PLAYWRIGHT_SESSION_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'playwright_session')

    @classmethod
    def update_env(cls, key, value):
        """Update a value in .env file and reload"""
        env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
        lines = []
        found = False
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                lines = f.readlines()
        for i, line in enumerate(lines):
            if line.startswith(f'{key}='):
                lines[i] = f'{key}={value}\n'
                found = True
                break
        if not found:
            lines.append(f'{key}={value}\n')
        with open(env_path, 'w') as f:
            f.writelines(lines)
        os.environ[key] = value
        setattr(cls, key, value)


# Seed search queries
YOUTUBE_SEED_QUERIES = [
    "why veganism is wrong",
    "debunking veganism myths",
    "ex vegan why I quit",
    "anti vegan arguments science",
    "why I stopped being vegan",
    "vegan vs meat eater debate",
    "carnivore diet destroys vegan",
    "veganism is unhealthy proof",
    "ethical animal farming defense",
    "vegan cringe compilation",
    "problems with veganism",
    "vegan diet dangers",
]

INSTAGRAM_SEED_QUERIES = [
    # Tags that pro-meat / carnivore / anti-vegan users genuinely post under
    # (NOT #antivegan — vegans flood that tag as counter-protest)
    "carnivorediet",       # Genuine carnivore community
    "meatheals",           # Pro-meat healing narrative
    "exvegan",             # Ex-vegans sharing their stories
    "carnivoremd",         # Shawn Baker's community tag
    "noseplastivia",       # Paul Saladino community
    "beefonly",            # Beef-only diet advocates
    "liverking",           # Liver King audience tag
    "ancestraldiet",       # Ancestral / primal eating
    "meatisbetterforyou",  # Pro-meat messaging
    "veganismkills",       # Explicit anti-vegan tag
    "carnivorewayoflife",  # Lifestyle carnivore content
    "dairyismurder",       # Counter-tag (bait for debate reels)
    "prolife4animals",     # Animal agriculture defense
    "sustainablefarming",  # Factory farming defense angle
    "ethicalmeat",         # Ethical omnivore / ranching
]
