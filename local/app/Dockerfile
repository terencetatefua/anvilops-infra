# ============================================================================
# anvil-app image — multi-stage, non-root, minimal, signal-safe.
# Local build is stdlib-only; the dependency layer is ready for boto3 when you
# flip to AI_BACKEND=bedrock on AWS (just uncomment it in requirements.txt).
# ============================================================================

FROM python:3.12.8-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt
FROM python:3.12.8-slim AS runtime
RUN groupadd --system app && useradd --system --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=app:app main.py .
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"
CMD ["python", "main.py"]