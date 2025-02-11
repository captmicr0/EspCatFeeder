FROM python:3.13-slim

WORKDIR /app

COPY FeedDirector.py .
COPY index.html .

RUN pip install requests

ENV HTTP_ADDR=''
ENV HTTP_PORT=8000

EXPOSE $HTTP_PORT

CMD ["python", "FeedDirector.py"]
