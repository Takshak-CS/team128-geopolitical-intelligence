# Build context: ./services/policy_stance
# torch / torch-geometric are left out: the module falls back to a random-walk
# embedding without them (its documented behaviour), and they add ~2 GB.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg
WORKDIR /app
COPY requirements.txt .
RUN grep -v -E '^(torch|torch-geometric)==' requirements.txt > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt
COPY backend/ ./backend/
COPY data_processing/ ./data_processing/
COPY visualization/ ./visualization/
# Datasets are mounted at /app/data; the pipeline cache is written to /app/outputs.
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
