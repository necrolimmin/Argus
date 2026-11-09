# Video of Hik-Connect / EZVIZ cameras from the vendor cloud into go2rtc.
# ffmpeg only copies the stream (no transcoding).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY media.py bridge.py ./
# Not root: the bridge parses data from the internet.
RUN useradd -r -u 10002 cloud
USER cloud
EXPOSE 8092
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8092/health', timeout=2)" || exit 1
CMD ["python", "bridge.py"]
