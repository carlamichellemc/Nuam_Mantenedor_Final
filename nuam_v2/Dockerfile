FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV NUAM_ENV=produccion NUAM_STORAGE_DIR=/app/data/storage
EXPOSE 8080
CMD ["gunicorn", "-w", "4", "--threads", "8", "-b", "0.0.0.0:8080", "app:app"]
