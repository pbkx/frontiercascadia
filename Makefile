.PHONY: setup dev test check
setup:
	./scripts/setup.sh
dev:
	./scripts/dev.sh
test:
	.venv/bin/python -m pytest backend/tests -q
check: test
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck
	npm --prefix frontend run build
