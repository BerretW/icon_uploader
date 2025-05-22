FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE ${PORT:-5000}
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-5000} --workers 4 --threads 2 --timeout 120 app:app"]