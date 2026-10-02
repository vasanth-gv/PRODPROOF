FROM python:3.12-slim

WORKDIR /app

# PyMySQL is pure Python; the `cryptography` package (used for MySQL's
# caching_sha2_password auth) ships prebuilt wheels for slim images, so no
# extra system build deps are required here.

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# In production, drop --reload and put a real process manager / multiple
# workers in front (see docker-compose.yml healthcheck + README).
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
