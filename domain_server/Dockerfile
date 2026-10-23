FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV EVAL_DB_PATH=/data/eval.sqlite
EXPOSE 8030
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8030"]
