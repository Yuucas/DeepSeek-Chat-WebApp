import os
from dotenv import load_dotenv
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from contextlib import asynccontextmanager
import asyncio

# Use relative imports within the backend package
from .algorithm import llm
from .routes import router
from .database import async_main # Import DB session dependency

load_dotenv() # Load .env variables

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY not configured in .env file for session middleware")

# --- FastAPI Lifespan for Model Loading ---
@asynccontextmanager
async def lifespan(the_app: FastAPI):
    print("Database: Creating tables...")
    await async_main()
    print("Backend: Loading LLM...")
    llm.load_llm()
    print("Backend: LLM loaded.")
    yield
    print("Backend: Shutting down.")
    # Cleanup if needed

app = FastAPI(lifespan=lifespan, title="Chat App Backend API")

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    # https_only=True,
    # max_age=14 * 24 * 60 * 60, 
    # same_site="lax", 
)

app.include_router(router)

