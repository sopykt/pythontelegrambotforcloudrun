FROM python:3.11-slim-bullseye

# 1. Install system dependencies for wkhtmltoimage and fonts
RUN apt-get update && apt-get install -y \
    wkhtmltopdf \
    libxrender1 \
    fonts-noto \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
