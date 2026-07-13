FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN python -W error -m py_compile \
    stage3_hydrator.py \
    stage4_razor_reranker.py \
    stage5_cognitive_verifier.py \
    operations_service.py \
    internal_service_auth.py \
    review_operations.py \
    shadow_operations.py \
    stream_worker.py \
    && python -W error -c "import stage3_hydrator, stage4_razor_reranker, stage5_cognitive_verifier, stream_worker"

EXPOSE 8090
CMD ["uvicorn", "stage5_cognitive_verifier:app", "--host", "0.0.0.0", "--port", "8090"]
