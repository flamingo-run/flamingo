ARG PYTHON_VERSION=3.9-slim
FROM python:$PYTHON_VERSION

# Install OS dependencies
RUN apt update -y
RUN apt install -y git build-essential

# Point to app folder
ARG APP_HOME=/app
WORKDIR $APP_HOME

# Service must listen to $PORT environment variable.
# This default value facilitates local development.
ENV PORT 8080

# Setting this ensures print statements and log messages
# promptly appear in Cloud Logging.
ENV PYTHONUNBUFFERED TRUE

# Install dependencies
RUN pip install -U pip poetry
RUN poetry config virtualenvs.create false
COPY pyproject.toml .
COPY poetry.lock .
COPY Makefile .
RUN poetry install --no-dev --no-root

# Copy local code to the container image.
COPY . .

# Prepare image entrypoint
WORKDIR $APP_HOME/flamingo
ENTRYPOINT python main.py
