FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Build the trained model bundle into the image if the repository copy is missing
RUN python -c "from src.pipeline.engine import load_models; load_models()"

EXPOSE 8000

# Bind to 0.0.0.0 inside the container; publish with `-p 127.0.0.1:8000:8000` so the
# console is reachable from the host only. Run with `--network none` for a hard air gap
# when only the CLI pipeline is needed.
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
