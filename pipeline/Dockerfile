FROM python:3.12-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN python -m venv /opt/venv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

# Build-time integrity gate: the self-verifying stages must pass under the
# strict warnings-as-errors flag before the image is allowed to build.
RUN python -W error stage4_razor_reranker.py > /dev/null \
    && python -W error stage5_cognitive_verifier.py > /dev/null \
    && python -W error stage3_hydrator.py > /dev/null

EXPOSE 8090
CMD ["uvicorn", "stage5_cognitive_verifier:app", "--host", "0.0.0.0", "--port", "8090"]
