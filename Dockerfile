FROM node:24-bookworm-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 MY_AGENT_MODE=demo
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY demo_files/example.txt ./demo_files/
COPY --from=frontend-build /build/dist/ ./frontend/dist/
CMD ["sh", "-c", "exec python -m uvicorn src.server.api:app --host 0.0.0.0 --port \"${PORT:-10000}\" --workers 1"]
