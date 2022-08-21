.PHONY: help
help: ## Show this help
	@egrep -h '\s##\s' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.PHONY: docs
docs: ## Build the docs
	@poetry run mike deploy $@ latest --update-aliases --push

rundocs: ## Run the docs locally
	@poetry run mike deploy $@ --update-aliases latest
	@poetry run mike serve
