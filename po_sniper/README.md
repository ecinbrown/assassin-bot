# PocketOption "Terminal Velocity" Sniper Bot
A headless, high-frequency browser automation bot for exploiting the 72.7% terminal velocity edge on PocketOption OTC pairs.

## Deployment Instructions for Render

1. Run `python generate_auth.py` locally on your PC.
2. Log into PocketOption and switch to Demo/Real.
3. Come back to the terminal and press Enter. This generates `auth_state.json`.
4. Push all these files (including `auth_state.json`) to your GitHub repository.
5. Create a new Web Service on Render, connect this repository.
6. Set the Environment to **Docker**.
7. Deploy.
