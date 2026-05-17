FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10

WORKDIR /app/backend

COPY requirements.txt .
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --upgrade pip -i ${PIP_INDEX_URL} && \
    pip install --default-timeout=300 --retries=10 -i ${PIP_INDEX_URL} -r requirements.txt

COPY . .

EXPOSE 8090 5101 5102 5103 5104 8101 8102 8103 8104

CMD ["python", "api_server.py"]
