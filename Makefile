.PHONY: data services infra pipeline all

WSL_GW := $(shell ip route | grep default | awk '{print $$3}')
export PGHOST ?= $(if $(WSL_GW),$(WSL_GW),localhost)
export LOCALSTACK_ENDPOINT ?= $(if $(WSL_GW),http://$(WSL_GW):4566,http://localhost:4566)
export MLFLOW_TRACKING_URI ?= $(if $(WSL_GW),http://$(WSL_GW):5000,http://localhost:5000)
export PGPORT ?= 5432
export PGUSER ?= taobao
export PGPASSWORD ?= taobao123
export PGDATABASE ?= taobao

data:
	bash fetch_dataset.sh

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