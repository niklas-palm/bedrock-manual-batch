.ONESHELL:
SHELL := /bin/bash

# Help function to display available commands
.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

# Default target when just running 'make'
.DEFAULT_GOAL := help

# Environment variables with default values
export STACKNAME ?= manual-bedrock-batch
export REGION ?= us-west-2
export PROJECT ?= manual-bedrock-batch

# Mark targets that don't create files as .PHONY
.PHONY: build deploy delete sync logs logs.tail validate go outputs run-workflow

validate: ## Validates and lints the SAM template
	@echo "Validating SAM template..."
	sam validate --lint

build: ## Downloads all dependencies and builds resources
	@echo "Building SAM application..."
	sam build

deploy: ## Deploys the artifacts from the previous build
	@echo "Deploying stack $(STACKNAME) to region $(REGION)..."
	sam deploy \
		--stack-name $(STACKNAME) \
		--resolve-s3 \
		--capabilities CAPABILITY_IAM \
		--region $(REGION) \
		--no-fail-on-empty-changeset \
		--tags project=$(PROJECT)

delete: ## Deletes the CloudFormation stack
	@echo "Deleting stack $(STACKNAME) from region $(REGION)..."
	sam delete \
		--stack-name $(STACKNAME) \
		--region $(REGION) \
		--no-prompts

go: build deploy ## Build and deploys the stack

# Local development commands
sync: ## Enables hot-reloading from the local environment. Saving triggers live-update
	@echo "Starting hot-reloading with resources in stack: $(STACKNAME)"
	sam sync \
		--watch \
		--stack-name $(STACKNAME) \
		--region $(REGION)

logs: ## Fetches the latest logs
	@echo "Fetching latest logs from stack: $(STACKNAME)"
	sam logs \
		--stack-name $(STACKNAME) \
		--region $(REGION)

logs.tail: ## Starts tailing the logs in real-time
	@echo "Starting to tail the logs from stack: $(STACKNAME)"
	sam logs \
		--stack-name $(STACKNAME) \
		--region $(REGION) \
		--tail

# Test commands
outputs: ## Fetch CloudFormation outputs and store them in .env file
	@echo "Fetching CloudFormation outputs..."
	@aws cloudformation describe-stacks \
		--stack-name $(STACKNAME) \
		--region $(REGION) \
		--query 'Stacks[0].Outputs[*].{Key:OutputKey,Value:OutputValue}' \
		--output json > .stack-outputs.json

run-workflow: outputs ## Run the workflow. Usage: make run-workflow INPUT=path/to/file.csv NAME=job-name
	@if [ -z "$(INPUT)" ]; then \
		echo "Error: INPUT parameter is required. Usage: make run-workflow INPUT=path/to/file.csv NAME=job-name"; \
		exit 1; \
	fi
	@if [ -z "$(NAME)" ]; then \
		echo "Error: NAME parameter is required. Usage: make run-workflow INPUT=path/to/file.csv NAME=job-name"; \
		exit 1; \
	fi
	@if [ ! -f "$(INPUT)" ]; then \
		echo "Error: File $(INPUT) does not exist"; \
		exit 1; \
	fi
	$(eval STATE_MACHINE_ARN := $(shell cat .stack-outputs.json | jq -r '.[] | select(.Key=="StateMachineArn") | .Value'))
	$(eval INPUT_BUCKET := $(shell cat .stack-outputs.json | jq -r '.[] | select(.Key=="JobBucketName") | .Value'))
	$(eval JOB_PREFIX := $(NAME)-$(shell date +%Y-%m-%d-%H-%M-%S))
	$(eval S3_KEY := jobs/$(JOB_PREFIX)/input/$(shell basename $(INPUT)))
	@echo "Uploading CSV to S3..."
	aws s3 cp $(INPUT) s3://$(INPUT_BUCKET)/$(S3_KEY)
	@echo "Starting Step Functions execution..."
	aws stepfunctions start-execution \
		--state-machine-arn $(STATE_MACHINE_ARN) \
		--input "{\"bucket\": \"$(INPUT_BUCKET)\", \"key\": \"$(S3_KEY)\", \"job_prefix\": \"jobs/$(JOB_PREFIX)\"}" \
		--region $(REGION)

