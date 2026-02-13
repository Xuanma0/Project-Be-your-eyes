FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY main.py /app/main.py

ENV OCR_SLEEP_MS=80
ENV OCR_TIMEOUT_PROB=0

EXPOSE 9102
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9102"]
