FROM quay.io/operator-framework/ansible-operator:v1.34.3

COPY requirements.yml ${HOME}/requirements.yml

RUN pip3.9 install jmespath kubernetes-validate --user \
 && ansible-galaxy collection install -r ${HOME}/requirements.yml \
 && chmod -R ug+rwx ${HOME}/.ansible \
 && chmod -R ug+rwx ${HOME}/.local

COPY watches.yaml ${HOME}/watches.yaml
COPY roles/ ${HOME}/roles/
COPY playbooks/ ${HOME}/playbooks/
