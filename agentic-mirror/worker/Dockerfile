FROM python:3.12-slim

WORKDIR /app

COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common /app/common
COPY worker /app/worker

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8001
CMD ["uvicorn", "worker.main:app", "--host", "0.0.0.0", "--port", "8001"]
