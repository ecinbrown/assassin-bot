# Lightweight Python image — NO Chromium needed!
FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all bot files
COPY . .

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1

# Command to run the bot
CMD ["python", "main.py"]
