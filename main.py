import os
import sys

# Forzar codificación UTF-8 en stdout/stderr para compatibilidad con Windows
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from app.main import app

# For Railway, the app is imported here
# No need for if __name__ == "__main__" as Railway handles the server