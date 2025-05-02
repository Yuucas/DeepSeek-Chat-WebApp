import os
from fastapi import FastAPI
from nicegui import ui, app, Client

from . import api_client
from .pageRoutes import pageRoutes
from .pages import login, sign_up, main


# --- Page Definitions ---

@ui.page(path=pageRoutes.HOME_PATH)
async def route_root():
    if await api_client.api_get_current_user(): ui.navigate.to(pageRoutes.MAIN_PATH)
    else: ui.navigate.to(pageRoutes.LOGIN_PATH)

@ui.page(path=pageRoutes.LOGIN_PATH)
async def login_page(client: Client):
    await login.handle_login(client)


@ui.page(path=pageRoutes.SIGNUP_PATH)
async def signup_page(client: Client):
    await sign_up.handle_signup(client)


@ui.page(path=pageRoutes.MAIN_PATH)
async def main_chat_page(client: Client):
    await main.handle_main_chat_page(client)
    

# --- init_nicegui ---
def init_nicegui(fastapi_app: FastAPI):
     ui.run_with(
         fastapi_app,
         mount_path="/",
         storage_secret=os.getenv("SECRET_KEY"),
         title="AI Chat",
         dark=True,
     )