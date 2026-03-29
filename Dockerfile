# seq2pipe v2.0.0 — Reproducible container
# Builds a self-contained environment with QIIME2 + Ollama + seq2pipe
#
# Build:  docker build -t seq2pipe:2.0.0 .
# Run:    docker run -v ~/data:/data seq2pipe:2.0.0 --fastq-dir /data --ai-driven
#
# For GPU (Ollama acceleration):
#   docker run --gpus all -v ~/data:/data seq2pipe:2.0.0 --fastq-dir /data --ai-driven

FROM condaforge/miniforge3:latest AS base

# Version lock
LABEL version="2.0.0"
LABEL description="seq2pipe: Autonomous closed-loop microbiome analysis"
LABEL maintainer="Tsubasa Sato"

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git && \
    rm -rf /var/lib/apt/lists/*

# QIIME2 environment (version-locked)
RUN conda create -n qiime2 -c https://packages.qiime2.org/qiime2/2024.10/amplicon/released \
    -c conda-forge -c bioconda -c defaults \
    qiime2-amplicon=2024.10 python=3.10 \
    --yes && \
    conda clean --all --yes

# Activate QIIME2 env by default
ENV PATH="/opt/conda/envs/qiime2/bin:$PATH"
ENV CONDA_DEFAULT_ENV=qiime2

# Python analysis deps (version-locked)
RUN pip install --no-cache-dir \
    matplotlib==3.9.* \
    seaborn==0.13.* \
    pandas==2.2.* \
    numpy==1.26.* \
    scikit-learn==1.5.* \
    scipy==1.14.* \
    networkx==3.3.* \
    statsmodels==0.14.* \
    biom-format==2.1.*

# Install Ollama
RUN curl -fsSL https://ollama.com/install.sh | sh

# Copy seq2pipe
WORKDIR /opt/seq2pipe
COPY . .

# Pull default model
RUN ollama serve & sleep 5 && ollama pull qwen2.5-coder:7b && pkill ollama || true

# Entrypoint
COPY <<'ENTRYPOINT' /opt/seq2pipe/docker-entrypoint.sh
#!/bin/bash
set -e
# Start Ollama in background
ollama serve &>/dev/null &
sleep 3
# Run seq2pipe
exec python3 /opt/seq2pipe/cli.py "$@"
ENTRYPOINT
RUN chmod +x /opt/seq2pipe/docker-entrypoint.sh

ENTRYPOINT ["/opt/seq2pipe/docker-entrypoint.sh"]
CMD ["--help"]
