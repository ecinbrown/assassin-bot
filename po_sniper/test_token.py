import requests
import sys

def check_token(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        resp = requests.get(url)
        print(f"Status Code: {resp.status_code}")
        print(f"Response: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    token = "7771345334:AAG4o1afylJuHWqT2YUnm2oFfcdfURnlbUE"
    check_token(token)
