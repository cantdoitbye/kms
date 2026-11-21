FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models/hf \
    MODEL_CACHE_DIR=/models/fastembed

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Bake the ONNX embedding + reranker models (and tokenizer) into the image:
# fast, offline first start with no download on every cold boot.
COPY app ./app
RUN python -c "from app.retrieval.embedder import get_embedder, get_reranker; get_embedder(); get_reranker()"

COPY eval ./eval
COPY tests ./tests

# Render / most PaaS inject $PORT; default to 8000 locally.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
