# VERSION defines the project version for the bundle.
# The release version is kept in .envrc (MAJOR/MINOR/PATCH), which direnv exports.
# Without direnv it is read from .envrc here. To build another version:
# - pass VERSION as an argument (e.g make bundle VERSION=0.0.2)
# - or export VERSION in the environment
ifeq ($(origin VERSION),undefined)
VERSION := $(shell sed -n 's/^export MAJOR=//p' .envrc).$(shell sed -n 's/^export MINOR=//p' .envrc).$(shell sed -n 's/^export PATCH=//p' .envrc)
endif

# CHANNELS define the bundle channels used in the bundle.
# Add a new line here if you would like to change its default config. (E.g CHANNELS = "candidate,fast,stable")
# To re-generate a bundle for other specific channels without changing the standard setup, you can:
# - use the CHANNELS as arg of the bundle target (e.g make bundle CHANNELS=candidate,fast,stable)
# - use environment variables to overwrite this value (e.g export CHANNELS="candidate,fast,stable")
ifneq ($(origin CHANNELS), undefined)
BUNDLE_CHANNELS := --channels=$(CHANNELS)
endif

# DEFAULT_CHANNEL defines the default channel used in the bundle.
# Add a new line here if you would like to change its default config. (E.g DEFAULT_CHANNEL = "stable")
# To re-generate a bundle for any other default channel without changing the default setup, you can:
# - use the DEFAULT_CHANNEL as arg of the bundle target (e.g make bundle DEFAULT_CHANNEL=stable)
# - use environment variables to overwrite this value (e.g export DEFAULT_CHANNEL="stable")
ifneq ($(origin DEFAULT_CHANNEL), undefined)
BUNDLE_DEFAULT_CHANNEL := --default-channel=$(DEFAULT_CHANNEL)
endif
BUNDLE_METADATA_OPTS ?= $(BUNDLE_CHANNELS) $(BUNDLE_DEFAULT_CHANNEL)

# IMAGE_TAG_BASE defines the registry namespace and image name used for the operator,
# bundle and catalog images. It MUST be set to a registry you can push to before
# running any push or release target, for example:
#   make release IMAGE_TAG_BASE=quay.io/<org>/openshift-node-upgrade-mutex-operator
# (.envrc sets it for maintainers who use direnv). The default is a placeholder
# that `make release` refuses to use.
IMAGE_TAG_BASE ?= example.com/openshift-node-upgrade-mutex-operator

# BUNDLE_IMG defines the image:tag used for the bundle.
# You can use it as an arg. (E.g make bundle-build BUNDLE_IMG=<some-registry>/<project-name-bundle>:<tag>)
BUNDLE_IMG ?= $(IMAGE_TAG_BASE)-bundle:v$(VERSION)

# BUNDLE_DIR is where `make bundle` writes the bundle (manifests/, metadata/,
# tests/ and bundle.Dockerfile) for VERSION. bundles/ is git-ignored.
BUNDLE_DIR ?= bundles/$(VERSION)

# BUNDLE_GEN_FLAGS are the flags passed to the operator-sdk generate bundle command
BUNDLE_GEN_FLAGS ?= -q --overwrite --version $(VERSION) $(BUNDLE_METADATA_OPTS)

# USE_IMAGE_DIGESTS defines if images are resolved via tags or digests
# You can enable this value if you would like to use SHA Based Digests
# To enable set flag to true. The operator image (IMG) must then already be pushed.
USE_IMAGE_DIGESTS ?= false
ifeq ($(USE_IMAGE_DIGESTS), true)
	BUNDLE_GEN_FLAGS += --use-image-digests
endif

# Image URL to use all building/pushing image targets
IMG ?= $(IMAGE_TAG_BASE):$(VERSION)

# CONTAINER_TOOL defines the container tool used to build and push images
# (podman by default; use `make <target> CONTAINER_TOOL=docker` for docker).
CONTAINER_TOOL ?= podman

# Tool versions. Every tool is downloaded into $(LOCALBIN) at the pinned version,
# so builds do not depend on whatever happens to be on PATH. To use your own
# binary instead, pass its absolute path (e.g. make bundle OPM=/usr/local/bin/opm).
OPERATOR_SDK_VERSION ?= v1.42.3
KUSTOMIZE_VERSION ?= v5.8.3
YQ_VERSION ?= v4.54.1
# ansible-operator and opm follow the base images, so `make run` and the catalog
# tooling match what ships.
ifeq ($(origin ANSIBLE_OPERATOR_VERSION),undefined)
ANSIBLE_OPERATOR_VERSION := $(shell sed -n 's|^FROM quay.io/operator-framework/ansible-operator:\(v[0-9.]*\).*|\1|p' Dockerfile)
endif
ifeq ($(origin OPM_VERSION),undefined)
OPM_VERSION := $(firstword $(shell sed -n 's|^FROM quay.io/operator-framework/opm:\(v[0-9.]*\).*|\1|p' catalog.Dockerfile))
endif

.DEFAULT_GOAL := help

# Remove half-written targets (e.g. an interrupted tool download) on failure.
.DELETE_ON_ERROR:

.PHONY: all
all: docker-build ## Build the operator image (same as docker-build).

##@ General

# The help target prints out all targets with their descriptions organized
# beneath their categories. The categories are represented by '##@' and the
# target descriptions by '##'. The awk commands is responsible for reading the
# entire set of makefiles included in this invocation, looking for lines of the
# file as xyz: ## something, and then pretty-format the target and help. Then,
# if there's a line with ##@ something, that gets pretty-printed as a category.
# More info on the usage of ANSI control characters for terminal formatting:
# https://en.wikipedia.org/wiki/ANSI_escape_code#SGR_parameters
# More info on the awk command:
# http://linuxcommand.org/lc3_adv_awk.php

.PHONY: help
help: ## Display this help.
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

# DOCS are concatenated, in this order, into README.md by `make document`.
DOCS ?= docs/USAGE.md docs/DEVELOPMENT.md
CSV_BASE ?= config/manifests/bases/openshift-node-upgrade-mutex-operator.clusterserviceversion.yaml

.PHONY: document
document: yq operator-sdk ## Regenerate README.md from DOCS and the CSV description from docs/USAGE.md.
	$(YQ) -i '.spec.description=load_str("./docs/USAGE.md")' $(CSV_BASE)
	@# yq -i re-indents the whole CSV; this puts it back in the layout make bundle writes.
	$(OPERATOR_SDK) generate kustomize manifests -q
	awk 'FNR == 1 && NR != 1 { print "" } { print }' $(DOCS) > README.md

.PHONY: lint
lint: ## Lint roles/, the tests, the samples and the build YAML (needs yamllint and ansible-lint on PATH).
	yamllint -c hack/yamllint.yaml roles/ playbooks/ watches.yaml requirements.yml .ansible-lint hack/ .github/ \
		molecule/ config/samples/ config/testing/ config/scorecard/ sample-manifests/ tests/
	ansible-lint roles/
	@# Without --project-dir, ansible-lint takes molecule/ (the directory of -c) as the
	@# project, does not install ./requirements.yml and cannot resolve kubernetes.core.
	ansible-lint -c molecule/.ansible-lint --project-dir . molecule/

##@ Build

.PHONY: run
ANSIBLE_ROLES_PATH?="$(shell pwd)/roles"
run: ansible-operator ## Run against the configured Kubernetes cluster in ~/.kube/config
	$(ANSIBLE_OPERATOR) run

.PHONY: docker-build
docker-build: ## Build the operator image.
	$(CONTAINER_TOOL) build -t $(IMG) .

.PHONY: image-smoke-test
image-smoke-test: ## Check the built operator image (collections, python libs, role syntax) without a cluster.
	CONTAINER_TOOL=$(CONTAINER_TOOL) hack/image-smoke-test.sh $(IMG)

.PHONY: docker-push
docker-push: ## Push the operator image (or any image passed as IMG).
	$(CONTAINER_TOOL) push $(IMG)

# PLATFORMS defines the target platforms for the manager image to be built for, to provide
# support for multiple architectures (i.e. make docker-buildx IMG=myregistry/myoperator:0.0.1).
# With docker this needs buildx (https://docs.docker.com/build/buildx/); with podman it
# builds a manifest list (needs qemu-user-static for foreign architectures).
# Either way the image is pushed, so IMG must point to a registry you can push to.
PLATFORMS ?= linux/arm64,linux/amd64,linux/s390x,linux/ppc64le
MANIFEST_LIST ?= localhost/openshift-node-upgrade-mutex-operator-multiarch:$(VERSION)
.PHONY: docker-buildx
docker-buildx: ## Build and push the operator image for all PLATFORMS.
ifeq ($(notdir $(CONTAINER_TOOL)),docker)
	- $(CONTAINER_TOOL) buildx create --name openshift-node-upgrade-mutex-operator-builder
	$(CONTAINER_TOOL) buildx use openshift-node-upgrade-mutex-operator-builder
	$(CONTAINER_TOOL) buildx build --push --platform=$(PLATFORMS) --tag $(IMG) -f Dockerfile .
	- $(CONTAINER_TOOL) buildx rm openshift-node-upgrade-mutex-operator-builder
else
	- $(CONTAINER_TOOL) manifest rm $(MANIFEST_LIST)
	$(CONTAINER_TOOL) build --platform=$(PLATFORMS) --manifest $(MANIFEST_LIST) -f Dockerfile .
	$(CONTAINER_TOOL) manifest push --all $(MANIFEST_LIST) docker://$(IMG)
endif

##@ Deployment

ifndef ignore-not-found
  ignore-not-found = false
endif

.PHONY: install
install: kustomize ## Install CRDs into the K8s cluster specified in ~/.kube/config.
	$(KUSTOMIZE) build config/crd | kubectl apply -f -

.PHONY: uninstall
uninstall: kustomize ## Uninstall CRDs from the K8s cluster specified in ~/.kube/config.
	$(KUSTOMIZE) build config/crd | kubectl delete --ignore-not-found=$(ignore-not-found) -f -

.PHONY: deploy
deploy: kustomize ## Deploy controller to the K8s cluster specified in ~/.kube/config.
	cd config/manager && $(KUSTOMIZE) edit set image controller=$(IMG)
	$(KUSTOMIZE) build config/default | kubectl apply -f -

.PHONY: undeploy
undeploy: kustomize ## Undeploy controller from the K8s cluster specified in ~/.kube/config.
	$(KUSTOMIZE) build config/default | kubectl delete --ignore-not-found=$(ignore-not-found) -f -

##@ Bundle

.PHONY: bundle
bundle: kustomize operator-sdk yq ## Generate the bundle for VERSION into BUNDLE_DIR, then validate it.
	$(OPERATOR_SDK) generate kustomize manifests -q
	cd config/manager && $(KUSTOMIZE) edit set image controller=$(IMG)
	@# generate bundle does not delete manifests that are no longer rendered.
	rm -rf $(BUNDLE_DIR)/manifests $(BUNDLE_DIR)/metadata
	$(KUSTOMIZE) build config/manifests | $(OPERATOR_SDK) generate bundle $(BUNDLE_GEN_FLAGS) --output-dir $(BUNDLE_DIR)
	@# generate bundle writes ./bundle.Dockerfile with paths relative to the repo root;
	@# keep it inside the bundle directory so each version builds on its own.
	sed -e 's|$(BUNDLE_DIR)/||' bundle.Dockerfile > $(BUNDLE_DIR)/bundle.Dockerfile
	rm -f bundle.Dockerfile
	$(YQ) eval-all -i '. as $$item ireduce ({}; . * $$item )' $(BUNDLE_DIR)/metadata/annotations.yaml custom-annotations.yaml
	$(YQ) -r '.annotations | to_entries | .[] | "LABEL " + .key + "=" + .value' custom-annotations.yaml >> $(BUNDLE_DIR)/bundle.Dockerfile
	$(OPERATOR_SDK) bundle validate $(BUNDLE_DIR)

.PHONY: verify-manifests
verify-manifests: kustomize yq ## Check config/default, config/manifests, config/testing and BUNDLE_DIR (if generated) for known regressions.
	KUSTOMIZE=$(KUSTOMIZE) YQ=$(YQ) hack/verify-manifests.sh $(BUNDLE_DIR)

.PHONY: bundle-validate
bundle-validate: operator-sdk ## Validate BUNDLE_DIR with the optional operatorframework suite.
	$(OPERATOR_SDK) bundle validate $(BUNDLE_DIR) --select-optional suite=operatorframework

.PHONY: bundle-build
bundle-build: ## Build the bundle image from BUNDLE_DIR (run `make bundle` first).
	@test -f $(BUNDLE_DIR)/bundle.Dockerfile || { echo "$(BUNDLE_DIR)/bundle.Dockerfile not found: run 'make bundle' first"; exit 1; }
	$(CONTAINER_TOOL) build -f $(BUNDLE_DIR)/bundle.Dockerfile -t $(BUNDLE_IMG) $(BUNDLE_DIR)

.PHONY: bundle-push
bundle-push: ## Push the bundle image.
	$(MAKE) docker-push IMG=$(BUNDLE_IMG)

##@ Catalog

# The catalog is file-based (FBC). The source of truth is CATALOG_TEMPLATE, an
# opm "basic" template that lists every released bundle image and the upgrade
# edges of the channel. `make catalog-render` turns it into CATALOG_FILE, which is
# committed so the catalog can be validated and built without pulling images.
PACKAGE_NAME ?= openshift-node-upgrade-mutex-operator
CATALOG_CHANNEL ?= alpha
CATALOG_TEMPLATE ?= catalog-template.yaml
CATALOG_DIR ?= catalog
CATALOG_FILE ?= $(CATALOG_DIR)/$(PACKAGE_NAME)/catalog.yaml
CATALOG_MIGRATE_LEVEL ?= bundle-object-to-csv-metadata
CATALOG_IMG ?= $(IMAGE_TAG_BASE)-catalog:v$(VERSION)
# BUNDLE_REF is the bundle image recorded in the catalog by `make catalog-add`.
# Set it to a digest reference (<repo>@sha256:...) to pin the release by digest.
BUNDLE_REF ?= $(BUNDLE_IMG)
# CATALOG_SKIP_RANGE lets clusters on any older version upgrade straight to
# VERSION instead of walking every replaces edge. Set it empty to only add the
# replaces edge.
CATALOG_SKIP_RANGE ?= <$(VERSION)

.PHONY: catalog-add
catalog-add: yq ## Add BUNDLE_REF to CATALOG_TEMPLATE as the new head of CATALOG_CHANNEL.
	YQ=$(YQ) hack/catalog-add.sh $(CATALOG_TEMPLATE) $(PACKAGE_NAME) $(CATALOG_CHANNEL) $(VERSION) $(BUNDLE_REF) '$(CATALOG_SKIP_RANGE)'

.PHONY: catalog-render
catalog-render: opm ## Render CATALOG_TEMPLATE into CATALOG_FILE (pulls every bundle image), then validate.
	@mkdir -p $(dir $(CATALOG_FILE))
	$(OPM) alpha render-template basic $(CATALOG_TEMPLATE) -o yaml --migrate-level $(CATALOG_MIGRATE_LEVEL) > $(CATALOG_FILE).tmp \
		|| { rm -f $(CATALOG_FILE).tmp; exit 1; }
	mv $(CATALOG_FILE).tmp $(CATALOG_FILE)
	$(OPM) validate $(CATALOG_DIR)

.PHONY: catalog-validate
catalog-validate: opm yq ## Validate CATALOG_DIR and check it matches CATALOG_TEMPLATE (no image pulls).
	$(OPM) validate $(CATALOG_DIR)
	YQ=$(YQ) hack/verify-catalog.sh $(CATALOG_TEMPLATE) $(CATALOG_FILE)

.PHONY: catalog-build
catalog-build: catalog-validate ## Build the catalog image from CATALOG_DIR.
	$(CONTAINER_TOOL) build -f catalog.Dockerfile -t $(CATALOG_IMG) .

.PHONY: catalog-push
catalog-push: ## Push the catalog image.
	$(MAKE) docker-push IMG=$(CATALOG_IMG)

##@ Release

.PHONY: release-check
release-check: yq ## Refuse to release to the placeholder registry or a VERSION that is already in the catalog.
	@case "$(IMAGE_TAG_BASE)" in example.com/*) \
		echo "error: set IMAGE_TAG_BASE to a registry you can push to (see .envrc)"; exit 1;; esac
	@YQ=$(YQ) hack/catalog-add.sh --check $(CATALOG_TEMPLATE) $(PACKAGE_NAME) $(CATALOG_CHANNEL) $(VERSION) $(BUNDLE_REF)

# The steps run one after another (also under make -j). The operator image is
# pushed before `bundle` so USE_IMAGE_DIGESTS=true can resolve it.
.PHONY: release
release: release-check ## Build and push operator, bundle and catalog images for VERSION and update the catalog.
	$(MAKE) docker-build docker-push
	$(MAKE) bundle
	$(MAKE) bundle-build bundle-push
	$(MAKE) catalog-add
	$(MAKE) catalog-render
	$(MAKE) catalog-build catalog-push
	$(MAKE) latest
	@echo "Released $(VERSION). Commit $(CATALOG_TEMPLATE) and $(CATALOG_DIR)/, then run 'make increment'."

.PHONY: latest
latest: ## Tag and push the VERSION operator, bundle and catalog images as :latest.
	$(CONTAINER_TOOL) tag $(IMG) $(IMAGE_TAG_BASE):latest
	$(CONTAINER_TOOL) tag $(BUNDLE_IMG) $(IMAGE_TAG_BASE)-bundle:latest
	$(CONTAINER_TOOL) tag $(CATALOG_IMG) $(IMAGE_TAG_BASE)-catalog:latest
	$(MAKE) docker-push IMG=$(IMAGE_TAG_BASE):latest
	$(MAKE) docker-push IMG=$(IMAGE_TAG_BASE)-bundle:latest
	$(MAKE) docker-push IMG=$(IMAGE_TAG_BASE)-catalog:latest

.PHONY: increment
increment: ## Bump PATCH in .envrc (run `direnv allow` afterwards if you use direnv).
	@cur=$$(sed -n 's/^export PATCH=//p' .envrc); \
	next=$$((cur + 1)); \
	sed -e "s/^export PATCH=.*/export PATCH=$$next/" .envrc > .envrc.tmp && mv .envrc.tmp .envrc; \
	echo "PATCH $$cur -> $$next"

##@ Dependencies

## Location to install dependencies to
LOCALBIN ?= $(shell pwd)/bin
$(LOCALBIN):
	mkdir -p $(LOCALBIN)

OS := $(shell uname -s | tr '[:upper:]' '[:lower:]')
ARCH := $(shell uname -m | sed 's/x86_64/amd64/' | sed 's/aarch64/arm64/')

## Tool binaries
KUSTOMIZE ?= $(LOCALBIN)/kustomize-$(KUSTOMIZE_VERSION)
OPERATOR_SDK ?= $(LOCALBIN)/operator-sdk-$(OPERATOR_SDK_VERSION)
ANSIBLE_OPERATOR ?= $(LOCALBIN)/ansible-operator-$(ANSIBLE_OPERATOR_VERSION)
OPM ?= $(LOCALBIN)/opm-$(OPM_VERSION)
YQ ?= $(LOCALBIN)/yq-$(YQ_VERSION)

.PHONY: kustomize
kustomize: $(KUSTOMIZE) ## Download kustomize locally if necessary.
$(KUSTOMIZE): | $(LOCALBIN)
	@{ \
	set -e ;\
	tmp=$$(mktemp -d) ;\
	curl -sSLf https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/$(KUSTOMIZE_VERSION)/kustomize_$(KUSTOMIZE_VERSION)_$(OS)_$(ARCH).tar.gz | tar xzf - -C $$tmp kustomize ;\
	mv $$tmp/kustomize $@ ;\
	rmdir $$tmp ;\
	}

.PHONY: ansible-operator
ansible-operator: $(ANSIBLE_OPERATOR) ## Download ansible-operator locally if necessary.
$(ANSIBLE_OPERATOR): | $(LOCALBIN)
	curl -sSLfo $@ https://github.com/operator-framework/ansible-operator-plugins/releases/download/$(ANSIBLE_OPERATOR_VERSION)/ansible-operator_$(OS)_$(ARCH)
	chmod +x $@

.PHONY: operator-sdk
operator-sdk: $(OPERATOR_SDK) ## Download operator-sdk locally if necessary.
$(OPERATOR_SDK): | $(LOCALBIN)
	curl -sSLfo $@ https://github.com/operator-framework/operator-sdk/releases/download/$(OPERATOR_SDK_VERSION)/operator-sdk_$(OS)_$(ARCH)
	chmod +x $@

.PHONY: opm
opm: $(OPM) ## Download opm locally if necessary.
$(OPM): | $(LOCALBIN)
	curl -sSLfo $@ https://github.com/operator-framework/operator-registry/releases/download/$(OPM_VERSION)/$(OS)-$(ARCH)-opm
	chmod +x $@

.PHONY: yq
yq: $(YQ) ## Download yq (mikefarah, v4) locally if necessary.
$(YQ): | $(LOCALBIN)
	curl -sSLfo $@ https://github.com/mikefarah/yq/releases/download/$(YQ_VERSION)/yq_$(OS)_$(ARCH)
	chmod +x $@
