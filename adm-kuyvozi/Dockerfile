FROM python:3.11-alpine
WORKDIR /app

COPY requirements.txt ./
RUN apk add --no-cache wget tesseract-ocr-data-rus libxml2-dev libxslt-dev jpeg-dev gcc g++ musl-dev freetype freetype-dev font-noto poppler-utils && \
    pip install --no-cache-dir -r requirements.txt && \
    apk del libxml2-dev libxslt-dev jpeg-dev gcc musl-dev

COPY . .

CMD [ "python", "./scrap.py" ]
