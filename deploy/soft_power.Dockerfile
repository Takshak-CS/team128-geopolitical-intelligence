# Build context: ./services/soft_power
# The module's own dash/backend/Dockerfile copies only dash/backend, but files mode
# reads ../../output relative to the backend, so the image keeps the repo layout.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_SOURCE=files
WORKDIR /srv/soft_power
COPY dash/backend/requirements.txt dash/backend/requirements.txt
RUN pip install --no-cache-dir -r dash/backend/requirements.txt pandas pyarrow numpy scikit-learn
COPY dash/backend/ dash/backend/
COPY output/ output/
WORKDIR /srv/soft_power/dash/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
