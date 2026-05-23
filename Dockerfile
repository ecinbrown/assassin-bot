FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY trading_bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY trading_bot/hyper_L/ ./hyper_L/

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Run the Assassin Telegram Controller
CMD ["python", "hyper_L/assassin_telegram.py", "--paper", "--balance", "10"]
