"""Voice AI agent via LiveKit.

Enables voice conversations with Clow.
Install: pip install livekit-agents livekit-plugins-openai
"""
import logging
import os

logger = logging.getLogger(__name__)
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")


def is_available() -> bool:
    try:
        import livekit.agents
        return bool(LIVEKIT_URL and LIVEKIT_API_KEY)
    except ImportError:
        return False


def get_voice_config() -> dict:
    return {
        "available": is_available(),
        "livekit_url": LIVEKIT_URL or "not configured",
        "has_api_key": bool(LIVEKIT_API_KEY),
        "setup": (
            "Para ativar voz: 1) Crie conta em https://cloud.livekit.io "
            "2) Adicione LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET ao .env "
            "3) pip install livekit-agents"
        ) if not is_available() else "Voice AI ativo.",
    }


async def create_voice_session(room_name: str = "clow-voice") -> dict:
    if not is_available():
        return {"error": "LiveKit not configured", "setup": get_voice_config()["setup"]}
    try:
        from livekit import api
        token = api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        token.with_identity("clow-user")
        token.with_grants(api.VideoGrants(room_join=True, room=room_name))
        return {"status": "ready", "room": room_name, "token": token.to_jwt(), "url": LIVEKIT_URL}
    except Exception as e:
        return {"error": str(e)}
