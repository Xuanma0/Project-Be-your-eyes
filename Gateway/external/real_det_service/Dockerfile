FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY main.py /app/main.py

EXPOSE 9001
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "9001"]
