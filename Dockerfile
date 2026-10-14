FROM python:3.12-slim AS base
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY didup_calendar_sync.py .

# Stage di test: gira nella stessa immagine di produzione (usato dalla CI)
FROM base AS test
COPY tests/ tests/
RUN python -m unittest discover -s tests -v

FROM base
# Versione mostrata nel log all'avvio (la CI passa AAAA.MM.GG-sha)
ARG VERSION=dev
ENV ARGO_STATE=/data/state.json TZ=Europe/Rome APP_VERSION=$VERSION
LABEL org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.title="didup-calendar-sync" \
      org.opencontainers.image.description="Argo didUP Famiglia -> Google Calendar + notifiche (non ufficiale)" \
      org.opencontainers.image.licenses="MIT"
VOLUME /data
# /metrics e /healthz, solo se METRICS_PORT è impostata
EXPOSE 9105
ENTRYPOINT ["python", "didup_calendar_sync.py", "-c", "/data/config.toml"]
CMD ["--loop", "1800"]
