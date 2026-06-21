from flask_login import UserMixin
import logging
from scraper.config import Config

logger = logging.getLogger(__name__)

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

# Simple hardcoded user loading
def get_user_by_username(username):
    if username == Config.ADMIN_USERNAME:
        return User(1, Config.ADMIN_USERNAME)
    return None

def get_user_by_id(user_id):
    if str(user_id) == '1':
        return User(1, Config.ADMIN_USERNAME)
    return None

def verify_login(username, password) -> bool:
    return username == Config.ADMIN_USERNAME and password == Config.ADMIN_PASSWORD
