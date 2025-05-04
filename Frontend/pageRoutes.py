from nicegui import app

class PageRoutes:
    def __init__(self, app):
        self.LOGIN_PATH = "/login"
        self.SIGNUP_PATH = "/signup"
        self.HOME_PATH = "/"
        self.MAIN_PATH = "/main"

pageRoutes = PageRoutes(app)