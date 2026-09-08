FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 10001 appuser
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER appuser
CMD ["uvicorn","lead_engine.api:app","--host","0.0.0.0","--port","8000","--no-proxy-headers","--no-access-log"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir -r requirements-dev.txt
USER appuser

FROM runtime AS production
