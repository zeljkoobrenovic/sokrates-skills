FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
EXPOSE 8080
USER root
CMD ["python", "-m", "app"]
