# ResearchNexus backend: FastAPI on uvicorn, CPU only.
#
#   docker build -t researchnexus-backend ./backend
#
# No secrets are baked in: every RESEARCHNEXUS_* setting comes from the
# environment at run time (ENVIRONMENT_VARIABLES.md). Uploaded PDFs live in
# /data, which must be a mounted volume (EFS on AWS). The relevance model
# (BAAI/bge-small-en-v1.5, ~70 MB, ONNX) is downloaded at build time, so a
# container never needs to fetch it.

FROM python:3.11-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml README.md ./
COPY app ./app
# every dependency as a wheel; nothing GPU-only is installed (no torch/CUDA)
RUN pip install --upgrade pip && pip wheel --wheel-dir /wheels .

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RESEARCHNEXUS_DATA_DIR=/data \
    RESEARCHNEXUS_MODELS_DIR=/opt/models
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home app \
    && mkdir -p /app /data /opt/models \
    && chown app:app /data
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --upgrade pip && pip install --no-deps /wheels/*.whl && rm -rf /wheels
COPY alembic.ini ./
COPY migrations ./migrations
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
    && python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')" \
    && chmod -R a+rX /opt/models

USER app
EXPOSE 8000
# liveness only: the process answers (readiness -- database and schema -- is /health/ready, for the load balancer)
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=4).status == 200 else 1)"
ENTRYPOINT ["docker-entrypoint.sh"]
# --proxy-headers: the client address comes from the load balancer's X-Forwarded-For
# (only the load balancer can reach the container, so it is trusted);
# --no-access-log: the app writes its own JSON access line, with the request id
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "30", "--no-server-header", "--no-access-log"]
