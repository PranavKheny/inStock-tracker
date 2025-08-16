# Playwright image with Python + Chromium (matches your 1.54.0 pin)
FROM mcr.microsoft.com/playwright/python:v1.54.0-jammy

WORKDIR /app

# Install Python deps
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . /app

# Expose web server
ENV PORT=8080
CMD ["bash", "-lc", "gunicorn -b 0.0.0.0:$PORT serve:app --workers 1 --threads 1 --timeout 180"]


