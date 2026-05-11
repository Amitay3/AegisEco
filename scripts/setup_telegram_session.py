"""
One-time Telegram authentication.
Run this ONCE from the project root to create the session file:

    python scripts/setup_telegram_session.py

You will be prompted for your phone number and a confirmation code sent by Telegram.
After that, a file called 'aegiseco_telegram.session' is saved in the project root
and the search_telegram_channels_tool will work without any further interaction.

Requirements:
  - TELEGRAM_API_ID and TELEGRAM_API_HASH in your .env file
  - Get these from https://my.telegram.org -> API development tools
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from telethon.sync import TelegramClient

load_dotenv()

api_id = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")

if not api_id or not api_hash:
    print("Error: TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in your .env file.")
    print("Get them from: https://my.telegram.org -> API development tools")
    sys.exit(1)

session_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aegiseco_telegram")

print("Starting Telegram authentication...")
print("You will receive a code via Telegram or SMS.\n")

with TelegramClient(session_path, int(api_id), api_hash) as client:
    client.start()
    me = client.get_me()
    print(f"\nAuthenticated as: {me.first_name} (@{me.username})")
    print(f"Session saved to: {session_path}.session")
    print("\nThe Telegram monitoring tool is now ready to use.")
