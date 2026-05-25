# Dockerfile do worker do F1 RAG Distributed.
#
# Esta imagem empacota o código Python da aplicação para rodar como worker
# distribuído (consumindo jobs de SQS em §4.4). Por enquanto, sem worker.py
# de fato — o container fica vivo via `tail -f /dev/null` para permitir
# desenvolvimento interativo (docker exec).

FROM python:3.11-slim

# Dependências de sistema (algumas libs Python precisam de build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia requirements primeiro para aproveitar cache de layer.
# requirements.txt referencia dados/requirements.txt via "-r", então ambos precisam estar disponíveis.
COPY requirements.txt ./
COPY dados/requirements.txt dados/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# boto3 — cliente AWS para SQS/CloudWatch (não está no requirements.txt principal)
RUN pip install --no-cache-dir "boto3==1.35.0"

# Copia o restante do código (depois do install para não invalidar cache)
COPY . .

# Variáveis de ambiente default — sobrescritas via docker-compose
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    OLLAMA_BASE_URL=http://harness-rag-ollama:11434 \
    OLLAMA_HOST=http://harness-rag-ollama:11434 \
    AWS_ENDPOINT_URL=http://harness-rag-localstack:4566 \
    AWS_DEFAULT_REGION=us-east-1 \
    AWS_ACCESS_KEY_ID=test \
    AWS_SECRET_ACCESS_KEY=test

# Notas sobre as duas vars do Ollama:
# - OLLAMA_BASE_URL: lido por langchain (ChatOllama no agents/generator.py)
# - OLLAMA_HOST:     lido pelo cliente nativo da lib `ollama` (usado por
#                    agents/retriever.py e dados/ingestion.py via ollama.embed())
# Manter as duas até unificarmos em um wrapper que aceite host explícito.

# Placeholder até §4.4 implementar o worker.py
CMD ["tail", "-f", "/dev/null"]
