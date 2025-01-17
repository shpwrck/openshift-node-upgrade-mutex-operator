FROM registry.redhat.io/openshift4/ose-cli-artifacts:v4.13.0-202411300029.p0.gd192e90.assembly.stream.el8 as ose-cli-artifacts

FROM quay.io/operator-framework/ansible-operator:v1.34.3

COPY requirements.yml ${HOME}/requirements.yml

RUN pip3.9 install jmespath kubernetes-validate --user \
 && ansible-galaxy collection install -r ${HOME}/requirements.yml \
 && chmod -R ug+rwx ${HOME}/.ansible \
 && chmod -R ug+rwx ${HOME}/.local

COPY --from=ose-cli-artifacts /usr/bin/oc /usr/bin/oc

COPY watches.yaml ${HOME}/watches.yaml
COPY roles/ ${HOME}/roles/
COPY playbooks/ ${HOME}/playbooks/
