FROM python:3.12-slim

RUN pip install --no-cache-dir "mlflow>=2.0" psycopg2-binary boto3

EXPOSE 5000

ENTRYPOINT ["mlflow"]