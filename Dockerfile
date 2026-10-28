# Keep this tag in step with the ansible-operator binary used by `make run`;
# the Makefile reads ANSIBLE_OPERATOR_VERSION from this line.
FROM quay.io/operator-framework/ansible-operator:v1.42.3

COPY requirements.yml ${HOME}/requirements.yml

# The base image ships python3.12 without pip. Bootstrap pip into the user
# site, install the python libraries the roles need (jmespath for
# community.general.json_query), then drop pip again. The chmod keeps the
# collections and python packages usable by OpenShift's arbitrary UID (GID 0).
RUN python3 -m ensurepip --user \
 && python3 -m pip install --user --no-cache-dir jmespath==1.1.0 \
 && python3 -m pip uninstall --yes pip \
 && ansible-galaxy collection install -r ${HOME}/requirements.yml \
 && chmod -R ug+rwx ${HOME}/.ansible ${HOME}/.local

COPY watches.yaml ${HOME}/watches.yaml
COPY roles/ ${HOME}/roles/
COPY playbooks/ ${HOME}/playbooks/
