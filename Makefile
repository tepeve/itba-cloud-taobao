.PHONY: data services infra pipeline all

data:
	uv run python scripts/fetch_dataset.py

services:
	docker compose up -d --build

infra:
	tofu -chdir=terraform init
	tofu -chdir=terraform apply -var="alb_asg_enabled=false"

pipeline:
	uv run python init_db.py
	uv run python data_bootstrap.py
	uv run python pipeline_features.py
	uv run python pipeline_training.py
	uv run python pipeline_inference.py

all: data infra pipeline
	@echo "Pipeline completo. Servicios (services) deben levantarse por separado en PowerShell (docker compose up -d --build)."
