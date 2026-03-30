FROM python:3.11-slim
WORKDIR /app
COPY app.py .
COPY app_fixed.py .
RUN pip install --no-cache-dir flask

ENV APP_MODE=vulnerable
EXPOSE 5000

CMD if [ "$APP_MODE" = "fixed" ]; then python app_fixed.py; else python app.py; fi
