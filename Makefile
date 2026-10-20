# Version of the operator, its image tag and its OLM bundle.
VERSION ?= 0.3.0

# Registry and name for the operator, bundle and catalog images.
IMAGE_TAG_BASE ?= ghcr.io/redhat-na-ssa/openshift-node-upgrade-mutex-operator
IMG ?= $(IMAGE_TAG_BASE):$(VERSION)
BUNDLE_IMG ?= $(IMAGE_TAG_BASE)-bundle:v$(VERSION)
CATALOG_IMG ?= $(IMAGE_TAG_BASE)-catalog:v$(VERSION)

# OLM channel. The community catalogs ship this operator on alpha.
CHANNELS ?= alpha
DEFAULT_CHANNEL ?= alpha
BUNDLE_GEN_FLAGS ?= -q --overwrite --version $(VERSION) --channels=$(CHANNELS) --default-channel=$(DEFAULT_CHANNEL)
PACKAGE ?= openshift-node-upgrade-mutex-operator
CSV_BASE = config/manifests/bases/$(PACKAGE).clusterserviceversion.yaml

CONTAINER_TOOL ?= docker
PLATFORMS ?= linux/amd64,linux/arm64,linux/ppc64le,linux/s390x
KUBECTL ?= kubectl
PYTHON ?= python3

# Tool versions. ansible-operator matches the base image in the Dockerfile.
ANSIBLE_OPERATOR_VERSION ?= v1.42.3
OPERATOR_SDK_VERSION ?= v1.42.3
OPM_VERSION ?= v1.74.0
KUSTOMIZE_VERSION ?= v5.8.3

OS := $(shell uname -s | tr '[:upper:]' '[:lower:]')
ARCH := $(shell uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')
LOCALBIN ?= $(shell pwd)/bin
ANSIBLE_OPERATOR ?= $(LOCALBIN)/ansible-operator-$(ANSIBLE_OPERATOR_VERSION)
OPERATOR_SDK ?= $(LOCALBIN)/operator-sdk-$(OPERATOR_SDK_VERSION)
OPM ?= $(LOCALBIN)/opm-$(OPM_VERSION)
KUSTOMIZE ?= $(LOCALBIN)/kustomize-$(KUSTOMIZE_VERSION)

.PHONY: all
all: lint test-unit docker-build

##@ General

.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

.PHONY: lint
lint: ## Lint YAML and Ansible.
	yamllint .
	ansible-lint

.PHONY: test-unit
test-unit: ## Unit-test the rollout planner.
	$(PYTHON) -m pytest tests/unit

.PHONY: test-e2e
test-e2e: ## Run the end-to-end test against the current cluster (the operator must be running; see docs/development.md).
	$(PYTHON) -m pytest -v tests/e2e

.PHONY: run
run: ansible-operator install ## Run the operator locally against the current cluster.
	ANSIBLE_ROLES_PATH="$(shell pwd)/roles" $(ANSIBLE_OPERATOR) run --watches-file=./watches.yaml --max-concurrent-reconciles=1

##@ Build

.PHONY: docker-build
docker-build: ## Build the operator image.
	$(CONTAINER_TOOL) build -t $(IMG) .

.PHONY: docker-push
docker-push: ## Push the operator image.
	$(CONTAINER_TOOL) push $(IMG)

.PHONY: docker-buildx
docker-buildx: ## Build and push the operator image for every platform in PLATFORMS.
	- $(CONTAINER_TOOL) buildx create --name $(PACKAGE)-builder
	$(CONTAINER_TOOL) buildx use $(PACKAGE)-builder
	- $(CONTAINER_TOOL) buildx build --push --platform=$(PLATFORMS) --tag $(IMG) -f Dockerfile .
	- $(CONTAINER_TOOL) buildx rm $(PACKAGE)-builder

##@ Deployment

.PHONY: install
install: kustomize ## Install the CRDs.
	$(KUSTOMIZE) build config/crd | $(KUBECTL) apply -f -

.PHONY: uninstall
uninstall: kustomize ## Remove the CRDs (and every MutexRule, MutexTarget and MutexRunConfig).
	$(KUSTOMIZE) build config/crd | $(KUBECTL) delete --ignore-not-found -f -

.PHONY: deploy
deploy: kustomize ## Deploy the operator image IMG.
	cd config/manager && $(KUSTOMIZE) edit set image controller=$(IMG)
	$(KUSTOMIZE) build config/default | $(KUBECTL) apply -f -

.PHONY: undeploy
undeploy: kustomize ## Remove the operator. Delete MutexRunConfigs first so their pools are restored.
	$(KUSTOMIZE) build config/default | $(KUBECTL) delete --ignore-not-found -f -

##@ OLM

.PHONY: bundle
bundle: kustomize operator-sdk ## Generate and validate the OLM bundle in bundle/.
	cd config/manager && $(KUSTOMIZE) edit set image controller=$(IMG)
	yq -i '.metadata.annotations.containerImage = "$(IMG)" | .spec.description = load_str("docs/operatorhub.md")' $(CSV_BASE)
	$(KUSTOMIZE) build config/manifests | $(OPERATOR_SDK) generate bundle $(BUNDLE_GEN_FLAGS)
	yq -i '. *= load("custom-annotations.yaml")' bundle/metadata/annotations.yaml
	$(OPERATOR_SDK) bundle validate ./bundle --select-optional suite=operatorframework

.PHONY: bundle-build
bundle-build: ## Build the bundle image.
	$(CONTAINER_TOOL) build -f bundle.Dockerfile -t $(BUNDLE_IMG) .

.PHONY: bundle-push
bundle-push: ## Push the bundle image.
	$(CONTAINER_TOOL) push $(BUNDLE_IMG)

.PHONY: catalog
catalog: opm ## Generate a file-based catalog with the pushed bundle BUNDLE_IMG, for test installs.
	rm -rf catalog && mkdir -p catalog/$(PACKAGE)
	$(OPM) init $(PACKAGE) --default-channel=$(DEFAULT_CHANNEL) --output=yaml > catalog/$(PACKAGE)/index.yaml
	$(OPM) render $(BUNDLE_IMG) --output=yaml >> catalog/$(PACKAGE)/index.yaml
	printf -- '---\nschema: olm.channel\npackage: %s\nname: %s\nentries:\n  - name: %s.v%s\n' \
		$(PACKAGE) $(DEFAULT_CHANNEL) $(PACKAGE) $(VERSION) >> catalog/$(PACKAGE)/index.yaml
	$(OPM) validate catalog
	$(OPM) generate dockerfile catalog

.PHONY: catalog-build
catalog-build: ## Build the catalog image.
	$(CONTAINER_TOOL) build -f catalog.Dockerfile -t $(CATALOG_IMG) .

.PHONY: catalog-push
catalog-push: ## Push the catalog image.
	$(CONTAINER_TOOL) push $(CATALOG_IMG)

##@ Tools

$(LOCALBIN):
	mkdir -p $(LOCALBIN)

.PHONY: ansible-operator
ansible-operator: $(ANSIBLE_OPERATOR) ## Download ansible-operator.
$(ANSIBLE_OPERATOR): | $(LOCALBIN)
	curl -sSLfo $@ https://github.com/operator-framework/ansible-operator-plugins/releases/download/$(ANSIBLE_OPERATOR_VERSION)/ansible-operator_$(OS)_$(ARCH)
	chmod +x $@

.PHONY: operator-sdk
operator-sdk: $(OPERATOR_SDK) ## Download operator-sdk.
$(OPERATOR_SDK): | $(LOCALBIN)
	curl -sSLfo $@ https://github.com/operator-framework/operator-sdk/releases/download/$(OPERATOR_SDK_VERSION)/operator-sdk_$(OS)_$(ARCH)
	chmod +x $@

.PHONY: opm
opm: $(OPM) ## Download opm.
$(OPM): | $(LOCALBIN)
	curl -sSLfo $@ https://github.com/operator-framework/operator-registry/releases/download/$(OPM_VERSION)/$(OS)-$(ARCH)-opm
	chmod +x $@

.PHONY: kustomize
kustomize: $(KUSTOMIZE) ## Download kustomize.
$(KUSTOMIZE): | $(LOCALBIN)
	curl -sSLf https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/$(KUSTOMIZE_VERSION)/kustomize_$(KUSTOMIZE_VERSION)_$(OS)_$(ARCH).tar.gz \
		| tar xzf - -C $(LOCALBIN) kustomize
	mv $(LOCALBIN)/kustomize $@
