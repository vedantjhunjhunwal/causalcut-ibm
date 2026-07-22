# CAUSALCUT — merged modular monolith (ingestion spine + analytical engine).
# One image runs the whole Python system (design doc Appendix B: docker-compose,
# not k8s; single container for the monolith).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update && apt-get install -y --no-install-recommends curl \
      libgomp1 && rm -rf /var/lib/apt/lists/*

RUN groupadd -r causalcut && useradd -r -g causalcut causalcut

# Dependencies first for layer caching. ortools/networkx are the analytical
# half; everything else is the ingestion spine.
COPY requirements.txt requirements-full.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-full.txt \
 && pip install --no-cache-dir numpy pandas scikit-learn joblib xgboost lightgbm scipy

# Application code
COPY app ./app
COPY scripts ./scripts
COPY scenarios ./scenarios

# Inference modules + trained model artifacts for in-process mode
COPY src ./src
COPY .models ./.models
COPY regulatory_rag ./regulatory_rag
COPY realtime ./realtime

# Durable state: SQLite plant-state store + write-ahead audit log both live here.
RUN mkdir -p /srv/data/audit && chown -R causalcut:causalcut /srv
USER causalcut

ENV CAUSALCUT_DB_PATH=/srv/data/causalcut.db \
    CAUSALCUT_AUDIT_BASE_PATH=/srv/data/audit

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
