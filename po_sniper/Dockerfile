# Use the official Microsoft Playwright Python image
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all bot files (including auth_state.json)
COPY . .

# Set environment variables for Python
ENV PYTHONUNBUFFERED=1

# Command to run the bot
CMD ["python", "main.py"]
