"""
Shared Gemini client.
"""

import os
from dotenv import load_dotenv
from google import genai

GEMINI_MODEL = "gemini-3.5-flash-lite"

load_dotenv()
client = genai.Client(api_key = os.getenv("GEMINI_API_KEY"))
