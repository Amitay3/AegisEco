import os
import requests
from crewai.tools import tool


def _send_telegram(message: str) -> str:
    """Send a message to the Telegram channel. Callable without the CrewAI wrapper."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        return "Error: Telegram credentials (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID) are missing from the environment."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return "Success: The alert was successfully broadcasted to the Telegram channel."
    except Exception as e:
        return f"Failed to send Telegram alert. Error: {str(e)}"


@tool("Send Telegram Alert")
def send_telegram_alert_tool(message: str) -> str:
    """
    Sends a formatted emergency alert message directly to the AegisEco Telegram Emergency Feed.
    Input MUST be a clearly formatted string containing the alert details.
    """
    return _send_telegram(message)
