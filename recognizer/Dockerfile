# CUDA 12 + cuDNN 9 is what onnxruntime-gpu 1.19 is built against.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY argus_recognizer ./argus_recognizer

# Face models (~300 MB archive) download here on first start; keep it on a volume.
VOLUME /root/.insightface
EXPOSE 8100
CMD ["python3", "-m", "uvicorn", "argus_recognizer.main:app", "--host", "0.0.0.0", "--port", "8100"]
