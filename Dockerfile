FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    nginx \
    gettext-base \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY python/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY python/ ./python/
COPY dist/ /usr/share/nginx/html
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf.template
COPY docker/start.sh ./start.sh
RUN chmod +x ./start.sh

RUN mkdir -p /app/data/audio /app/data/videos /app/data/thumbnails \
             /app/data/scripts /app/logs

ENV PYTHONPATH=/app/python:/app
ENV DATABASE_PATH=/app/data/tubebot.db
ENV LOG_LEVEL=INFO
ENV PORT=8080

EXPOSE 8080

CMD ["./start.sh"]
