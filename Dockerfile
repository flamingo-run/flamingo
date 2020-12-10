ARG PYTHON_VERSION=3.8-slim
FROM python:$PYTHON_VERSION

# Install OS dependencies
RUN apt update
RUN apt install -y git make

# Point to app folder
ARG APP_HOME=/app
WORKDIR $APP_HOME

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
ENTRYPOINT python -m sanic main.app --host=0.0.0.0 --port=$PORT
