import os
from passlib.context import CryptContext
from dotenv import load_dotenv
# For simplified session management via NiceGUI storage, JWT might be less necessary
# from datetime import datetime, timedelta, timezone
# from typing import Optional
# import jwt # from pyjwt
# from jose import JWTError, jwt

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
# ALGORITHM = os.getenv("ALGORITHM", "HS256") # Needed if using JWT
# ACCESS_TOKEN_EXPIRE_MINUTES = 30 # Example expiry if using JWT

if not SECRET_KEY:
    raise ValueError("No SECRET_KEY found in environment variables")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)