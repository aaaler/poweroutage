FROM python:3-alpine
WORKDIR /app

COPY requirements.txt ./
RUN apk add --no-cache wget libxml2-dev libxslt-dev jpeg-dev gcc musl-dev

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "./scrap.py" ]
