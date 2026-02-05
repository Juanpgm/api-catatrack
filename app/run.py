from .main import app

# This module exists to handle Railway's attempt to import app.run
# It simply re-exports the app from app.main