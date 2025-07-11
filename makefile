.PHONY: help
help: ## Show this help
	@egrep -h '\s##\s' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: docs
docs: ## Build the docs
	@poetry run mike deploy $@ latest --update-aliases --push

.PHONY: update
update: ## Update the docs
	@poetry update

rundocs: ## Run the docs locally
	@poetry run mkdocs serve

precommit: ## Run pre-commit hooks
	@git add . & poetry run pre-commit run --all-files

.PHONY: test
test: ## Run the tests
	@poetry run mkdocs gh-deploy --force


.PHONY: deploy
deploy: update  ## Deploy for production
	@poetry build
	@poetry publish

.PHONY:install_dev
install_dev: ## Install dev dependencies
	@poetry install
	@poetry run pre-commit install
	@poetry run pre-commit autoupdate

