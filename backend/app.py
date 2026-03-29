

"""
app.py
------
FastAPI backend for the eCommerce VoiceBot.
Responsibilities:
    1. LiveKit token generation (/token)
    2. Serving static frontend files (index.html, assets)
    3. Health check endpoint
Note: All real-time audio/voice logic is handled by the agent worker (see agent.py).
"""



import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from logging_config import setup_logging

# Load environment variables from .env at project root
load_dotenv(Path(__file__).parent.parent / ".env")

# Configure logging for the backend API (writes to logs/backend.log)
logger = setup_logging("voicebot-backend", "backend.log")

# Initialize FastAPI app
app = FastAPI(title="E-Commerce Voicebot Backend")

# Health check endpoint for monitoring and orchestration
@app.get("/health")
def health_check():
    """
    Health check endpoint for backend status.
    Returns:
        dict: Simple status dict for monitoring/orchestration.
    """
    return {"status": "ok"}

# CORS Configuration (allow all origins for demo/dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



@app.get("/token")
def get_token(identity: str = "guest", room: str | None = None):
    """
    Generate a LiveKit access token for a given user/room.
    Args:
        identity (str): User identity.
        room (str, optional): Room name. Defaults to None.
    Returns:
        dict: {"token": <jwt>, "url": <livekit_url>}
    """
    from livekit import api

    if not room:
        safe_identity = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in identity)
        room = f"ecommerce-room-{safe_identity}"

    # Get credentials from environment
    api_key = os.environ.get("LIVEKIT_API_KEY", "devkey")
    api_secret = os.environ.get("LIVEKIT_API_SECRET", "secret")

    # Create token using method chaining (LiveKit SDK >=1.1.0)
    token = (
        api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_subscribe=True,
            )
        )
    )

    return {
        "token": token.to_jwt(),
        "url": os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
    }


# Serve Frontend Static Files (index.html, assets, SPA fallback)
frontend_path = Path(__file__).parent.parent / "frontend"

@app.get("/{full_path:path}")
async def serve_static(full_path: str):
    """
    Serve static files for the frontend. If file not found, fallback to index.html (SPA routing).
    Args:
        full_path (str): Path to requested file (relative to /frontend)
    Returns:
        FileResponse: The requested file or index.html
    """
    # If requesting root, serve index.html
    if not full_path:
        return FileResponse(frontend_path / "index.html")

    # Try to serve the requested file
    file_path = frontend_path / full_path
    if file_path.is_file():
        return FileResponse(file_path)

    # If file not found, serve index.html (for SPA routing)
    return FileResponse(frontend_path / "index.html")

if __name__ == "__main__":
    # Run the FastAPI app with Uvicorn for local development
    import uvicorn
    port = int(os.environ.get("BACKEND_PORT", 5001))
    logger.info(f"Starting backend on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)
