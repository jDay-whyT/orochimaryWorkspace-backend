FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Clean any bytecode that might have been copied
RUN find /app -type d -name __pycache__ -exec rm -rf {} + || true
RUN find /app -type f -name "*.pyc" -delete || true

EXPOSE 8080

CMD ["python", "-m", "app.server"]
