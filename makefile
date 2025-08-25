.PHONY: help
help: ## Show this help
	@egrep -h '\s##\s' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: docs
docs: ## Build the docs
	@uv run mike deploy $@ latest --update-aliases --push

.PHONY: update
update: ## Update the docs
	@uv lock
	@uv sync

rundocs: ## Run the docs locally
	@uv run mkdocs serve

precommit: ## Run pre-commit hooks
	@git add . & uv run pre-commit run --all-files

.PHONY: test
test: ## Run the tests
	@uv run mkdocs gh-deploy --force


.PHONY: deploy
deploy: update  ## Deploy for production
	@uv build
	@uv publish

.PHONY:install_dev
install_dev: ## Install dev dependencies
	@uv install
	@uv run pre-commit install
	@uv run pre-commit autoupdate

patch: ## Increment patch
	@uv version --bump patch


minor: ## Increment minor
	@uv version --bump minor

major: ## Increment major
	@uv version --bump major

alpha: ## Increment alpha
	@uv version --bump alpha

beta: ## Increment beta
	@uv version --bump beta

stable: ## Increment stable
	@uv version --bump stable

dev: ## Increment dev
	@uv version --bump dev
