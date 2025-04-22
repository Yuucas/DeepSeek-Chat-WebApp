# file: run.py
import uvicorn
import os
from dotenv import load_dotenv
import asyncio # Import asyncio

# Try installing and using winloop for potentially better performance/stability on Windows
try:
    import winloop
    print("Attempting to use winloop event loop policy.")
    asyncio.set_event_loop_policy(winloop.EventLoopPolicy())
except ImportError:
    print("winloop not found, using default asyncio event loop.")
    pass # Fallback to default if winloop is not installed

# Load environment variables first
load_dotenv()

# Import the FastAPI app instance from the backend
from Backend.main import app as fastapi_app
# Import the NiceGUI initialization function from the frontend
from Frontend.main import init_nicegui

# Initialize NiceGUI by mounting it onto the FastAPI app
init_nicegui(fastapi_app)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000)) # Allow port override via env var
    host = os.getenv("HOST", "0.0.0.0")
    reload = os.getenv("RELOAD", "true").lower() == "true" # Allow disabling reload

    # Check if adapter path exists before starting
    adapter_path = os.getenv("ADAPTER_PATH")
    if not adapter_path or not os.path.exists(adapter_path):
         print("-" * 50)
         print(f"ERROR: LLM Adapter path not found or not set: {adapter_path}")
         print("Please ensure ADAPTER_PATH in your .env file points to the correct directory.")
         print("-" * 50)
         # Optionally exit here if model is critical for startup
         # import sys
         # sys.exit(1)
    else:
         print(f"Found adapter path: {adapter_path}")


    print(f"Starting server on {host}:{port} with reload={'enabled' if reload else 'disabled'}...")
    uvicorn.run(
        "run:fastapi_app", # Point to the app instance in *this* run.py file
        host=host,
        port=port,
        reload=reload,
        reload_dirs=["backend", "frontend"] # Watch backend and frontend folders for changes
    )