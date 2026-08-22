"""
Redirect wrapper: Routes hyper_L/assassin_telegram.py entrypoints to the new Assassin Bot v2 (main.py)
"""
import os
import sys
import asyncio

# Ensure project root is in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import main

if __name__ == "__main__":
    try:
        asyncio.run(main.main())
    except KeyboardInterrupt:
        print("Exited.")
