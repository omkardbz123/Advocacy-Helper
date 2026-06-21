"""
Entry point for Animal Advocacy Helper.
Starts the Flask admin dashboard on localhost:5000.
The scraper is controlled from the dashboard UI.
"""
import os
import sys

# Ensure stdout/stderr are UTF-8 configured to avoid encoding issues on Windows
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    sys.stderr.reconfigure(encoding='utf-8', errors='backslashreplace')
except AttributeError:
    pass

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from admin.app import create_app, socketio

if __name__ == '__main__':
    app = create_app()
    print("\n" + "="*50)
    print("  Animal Advocacy Helper — Admin Dashboard")
    print("  Open: http://localhost:5000")
    print("  Login: oma / omya28")
    print("="*50 + "\n")
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
