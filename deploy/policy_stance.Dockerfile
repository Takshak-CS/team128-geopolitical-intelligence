# Build context: ./services/policy_stance   (additional context "deploy" = ./deploy)
# requirements.txt pins versions that were never tested together with the rest of the
# platform; the pins are dropped and the tested constraints decide instead.
# torch / torch-geometric are left out: the module falls back to a classical embedding
# without them (its documented behaviour), and they add ~2 GB.
# syntax=docker/dockerfile:1
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg
WORKDIR /app
COPY --from=deploy constraints.txt /tmp/constraints.txt
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    sed -E 's/[=<>]=.*$//' requirements.txt | grep -v -E '^(torch|torch-geometric)\s*$' > /tmp/req.txt \
 && pip install -r /tmp/req.txt -c /tmp/constraints.txt
COPY backend/ ./backend/
COPY data_processing/ ./data_processing/
COPY visualization/ ./visualization/
# Datasets are mounted at /app/data; the pipeline cache is written to /app/outputs.
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
