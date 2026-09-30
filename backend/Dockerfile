FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .
# no-root: el proceso corre como 'dnd'; /data (bind mount con las
# DBs) debe ser escribible por él
RUN useradd --system --uid 10001 dnd \
    && mkdir -p /data && chown -R dnd:dnd /data /app
USER dnd
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
