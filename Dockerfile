# The public demo. Only the code and the sample invoices go into the image: no .env, no secrets/.
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DEMO_SEED_DIR=/app/demo_seed DEMO_DATA_DIR=/tmp/demo_data INVOICE_MODEL=claude-haiku-5-5
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .
COPY demo_seed ./demo_seed
CMD ["python", "-m", "invoice_pipeline", "demo"]
