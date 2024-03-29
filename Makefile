setup:
	@pip install -U pip poetry

dependencies:
	@make setup
	@poetry install --no-root

update:
	@poetry update

test:
	@make check
	@make lint
	@make unit

check:
	@poetry check

lint:
	@echo "Checking code style ..."
	@poetry run black --check flamingo
	@poetry run pylint flamingo

unit:
	@echo "Running unit tests ..."
	ENV=test poetry run coverage run flamingo/manage.py test flamingo --no-input

shell:
	@PYTHONPATH=flamingo poetry run python

run-server:
	@poetry run python flamingo/main.py


.PHONY: setup dependencies update test check lint unit shell static migrate run-server
