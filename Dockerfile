# Keep this tag in step with the ansible-operator binary used by `make run`;
# the Makefile reads ANSIBLE_OPERATOR_VERSION from this line.
FROM quay.io/operator-framework/ansible-operator:v1.42.3

# The license of this repository. /licenses is where Red Hat's preflight check
# HasLicense looks for it; hack/image-smoke-test.sh checks both.
LABEL org.opencontainers.image.licenses="Apache-2.0"
COPY LICENSE /licenses/LICENSE

COPY requirements.yml ${HOME}/requirements.yml

# The python libraries the roles need (kubernetes, PyYAML, jinja2) ship in the
# base image, so only the collections are added. The chmod keeps them usable
# by OpenShift's arbitrary UID (GID 0).
RUN ansible-galaxy collection install -r ${HOME}/requirements.yml \
 && chmod -R ug+rwx ${HOME}/.ansible

COPY watches.yaml ${HOME}/watches.yaml
COPY roles/ ${HOME}/roles/
COPY playbooks/ ${HOME}/playbooks/
