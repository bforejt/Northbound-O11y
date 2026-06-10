FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py panos_api.py ./
COPY modules/ modules/

# ENTRYPOINT so `docker compose run panos-connector --once` just appends flags.
ENTRYPOINT ["python", "main.py"]
