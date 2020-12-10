ARG PYTHON_VERSION=3.8-slim
FROM python:$PYTHON_VERSION

# Point to app folder
ARG APP_HOME=/app
WORKDIR $APP_HOME

# Install dependencies
RUN pip install -U pip poetry
COPY pyproject.toml .
COPY poetry.lock .
RUN poetry export -f requirements.txt --output requirements.txt
RUN pip install -r requirements.txt

# Service must listen to $PORT environment variable.
# This default value facilitates local development.
ENV PORT 8080

# Setting this ensures print statements and log messages
# promptly appear in Cloud Logging.
ENV PYTHONUNBUFFERED TRUE

# Copy local code to the container image
COPY . .

# Image entrypoint
CMD exec python ./flamingo/main.py
