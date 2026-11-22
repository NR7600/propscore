FROM python:3.13-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    PROPSCORE_REFRESH_HOUR=5

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run.py README.md DEPLOY.md ./
COPY propscore ./propscore
COPY app ./app
COPY templates ./templates
# Board JSON is generated on first boot (and daily) via `python run.py nba`.
# Do not COPY output/ — it is gitignored and may be absent in a fresh deploy.
RUN mkdir -p output cache

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
