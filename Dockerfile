# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8765 \
    ECG_DATA_ROOT=/opt/cardioinsight/demo-cases \
    ECG_APP_DATA_ROOT=/data/app

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

# Only generated, non-identifiable records are included in the public demo image.
# Real or identifiable ECG files must be supplied separately on a private read-only volume.
ARG ECG_SYNTHETIC_CASE_COUNT=10
RUN python scripts/generate_synthetic_demo.py \
      --output /opt/cardioinsight/demo-cases \
      --cases "${ECG_SYNTHETIC_CASE_COUNT}" \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin cardioinsight \
    && mkdir -p /data/app \
    && chown -R cardioinsight:cardioinsight /data /opt/cardioinsight

USER cardioinsight

EXPOSE 8765
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import json,os,sys,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8765')+'/api/health',timeout=4)); sys.exit(0 if d.get('status')=='ok' and d.get('data_root_found') else 1)"

CMD ["python", "scripts/start_web.py"]
