.DEFAULT_GOAL := help

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

.PHONY: setup-env
setup-env: ## Create .venv and install all requirements (action, mcp_tools, skill)
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r action/scripts/requirements-dev.txt
	$(PIP) install -r mcp_tools/requirements.txt
	$(PIP) install -r skill/pprof_analyzer/requirements.txt
	$(PIP) install -e .

.PHONY: npm-install-action
npm-install-action: ## Install npm deps (pprof-to-md) for the GitHub Action
	cd action && npm ci

.PHONY: install-pprof-to-md
install-pprof-to-md: ## Install pprof-to-md globally (required by skill & MCP paths)
	npm install -g pprof-to-md

.PHONY: mcp-http-run
mcp-http-run: ## Run the MCP HTTP server locally (0.0.0.0:9000)
	$(PYTHON) mcp_server_http.py --host 0.0.0.0 --port 9000

.PHONY: mcp-stdio-run
mcp-stdio-run: ## Run the MCP stdio server locally
	$(PYTHON) mcp_server.py

.PHONY: mcp-http-docker-build
mcp-http-docker-build: ## Build the MCP HTTP server Docker image
	docker build -t pprof-analyzer-mcp .

.PHONY: mcp-http-docker-run
mcp-http-docker-run: ## Run the MCP HTTP server in Docker (NETWORK=host for --network host)
ifeq ($(NETWORK),host)
	docker run -d --network host --name mcp-server pprof-analyzer-mcp --host 0.0.0.0 --port 8000
else
	docker run -p 8000:8000 --name mcp-server pprof-analyzer-mcp
endif

.PHONY: build-claude-skill
build-claude-skill: ## Build the distributable Claude skill zip
	skill/build-zip.sh

.PHONY: release-tag
release-tag: ## Bump the project version everywhere (usage: make release-tag <version>)
	@VERSION="$(filter-out $@,$(MAKECMDGOALS))"; \
	if [ -z "$$VERSION" ]; then \
		echo "Usage: make release-tag <version>  (e.g. make release-tag 0.1.1)"; \
		exit 1; \
	fi; \
	$(PYTHON) scripts/bump_version.py "$$VERSION"

SKILL_INSTALL_DIR := /tmp/pprof-analyzer-skill-install

.PHONY: extract-claude-skill
extract-claude-skill: build-claude-skill
	rm -rf $(SKILL_INSTALL_DIR)
	unzip -o skill/pprof-analyzer-skill.zip -d $(SKILL_INSTALL_DIR)

.PHONY: install-claude-skill
install-claude-skill: extract-claude-skill ## Unzip and install the Claude skill into ~/.claude/skills
	cd $(SKILL_INSTALL_DIR)/pprof-analyzer-skill && ./SETUP.sh install

.PHONY: verify-claude-skill
verify-claude-skill: extract-claude-skill ## Verify the installed Claude skill
	cd $(SKILL_INSTALL_DIR)/pprof-analyzer-skill && ./SETUP.sh verify

.PHONY: uninstall-claude-skill
uninstall-claude-skill: extract-claude-skill ## Uninstall the Claude skill from ~/.claude/skills
	cd $(SKILL_INSTALL_DIR)/pprof-analyzer-skill && ./SETUP.sh uninstall

.PHONY: lint
lint: ## Run pyright type checking
	$(VENV)/bin/pyright --project pyproject.toml

.PHONY: test
test: ## Run the full test suite (repo-root pytest testpaths)
	$(PYTHON) -m pytest

.PHONY: test-action
test-action: ## Run Action tests only
	$(PYTHON) -m pytest action/scripts/tests/

.PHONY: test-mcp
test-mcp: ## Run MCP tools tests only
	$(PYTHON) -m pytest mcp_tools/tests/

.PHONY: test-skill
test-skill: ## Run all skill tests only
	$(PYTHON) -m pytest skill/*/tests/

.PHONY: test-coverage
test-coverage: ## Run tests with coverage report
	$(PYTHON) -m pytest --cov=skill --cov=mcp_tools --cov=action/scripts --cov-report=term-missing

.PHONY: check
check: lint test ## Run lint + full test suite (pre-push gate)

.PHONY: clean
clean: ## Remove build artifacts and caches
	rm -f skill/pprof-analyzer-skill.zip
	find . -type d -name '__pycache__' -not -path './.venv/*' -not -path './node_modules/*' -exec rm -rf {} +
	rm -rf .pytest_cache
	find .ai_output -mindepth 1 -not -name '.gitkeep' -exec rm -rf {} +

# Swallow the version argument as a no-op target so `make release-tag 0.1.1`
# doesn't fail with "No rule to make target '0.1.1'". Must stay the LAST rule
# in the file so it never shadows a real target.
%:
	@:
