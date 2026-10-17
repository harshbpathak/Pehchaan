# Pehchan AI on a Hugging Face Docker Space; the graph lives in FalkorDB Cloud.
# The Space repository needs only this file and README.md. The app is cloned from GitHub,
# and the two local models are downloaded at build time so cold starts skip the download.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Spaces run containers as user 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PEHCHAN_MODEL_DIR=/home/user/models \
    PYTHONUNBUFFERED=1
WORKDIR /home/user

ARG PEHCHAN_REPO=https://github.com/harshbpathak/Pehchaan.git
# CD replaces this with the exact commit that passed CI; a branch name also works.
ARG PEHCHAN_REF=main
RUN git clone "$PEHCHAN_REPO" app && git -C app checkout "$PEHCHAN_REF"
WORKDIR /home/user/app

RUN pip install --no-cache-dir --user "torch==2.14.1" --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --user -c requirements.lock -e ".[semantic,server]"
RUN python -m pehchan.cli download-models

EXPOSE 7860
# One worker: the service serializes model and graph work. Trust the Spaces proxy's
# X-Forwarded-For so the public rate limit applies per visitor.
CMD ["uvicorn", "pehchan.api:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
