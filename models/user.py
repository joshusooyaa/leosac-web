"""
User model for Flask-Login integration.
"""
from flask_login import UserMixin

class LeosacUser(UserMixin):
    """User model for Leosac authentication"""
    
    def __init__(self, user_id, username, rank=None):
        self.id = user_id
        self.username = username
        self.rank = rank
    
    def get_id(self):
        return str(self.id)
    
    def is_authenticated(self):
        return True
    
    def is_active(self):
        return True
    
    def is_anonymous(self):
        return False 