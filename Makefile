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
	@cd flamingo && poetry run pylint --rcfile=../.pylintrc flamingo

unit:
	@echo "Running unit tests ..."
	ENV=test poetry run coverage run flamingo/manage.py test flamingo --no-input

run-server:
	@poetry run python flamingo/main.py


.PHONY: setup dependencies update test check lint unit static migrate run-server
