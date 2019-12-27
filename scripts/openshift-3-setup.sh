#!/bin/bash

subscription-manager register --username=tmcvey@trace3.com --password=
subscription-manager list --available --matches '*OpenShift*'
subscription-manager attach --pool=8a85f99b6d889887016d96e624cf35be
subscription-manager repos --disable="*"
subscription-manager repos --enable="rhel-7-server-rpms" --enable="rhel-7-server-extras-rpms" --enable="rhel-7-server-ose-3.11-rpms" --enable="rhel-7-server-ansible-2.6-rpms"
yum -y update
$ yum -y install atomic-openshift-clients openshift-ansible

curl https://raw.githubusercontent.com/williamcaban/openshift-lab/master/inventory-host-aio-TEMPLATE.yaml > inventory_aio

# Replace the Domain entries in the file.
sed -i 's/ocp.example.com/t3-311.openshift.awsworkshop.io/g' inventory_aio
# Replace the Registrey Token in your account from: https://access.redhat.com/terms-based-registry/#/
sed -i 's/{{REGISTRY_TOKEN}}/eyJhbGciOiJSUzUxMiJ9.eyJzdWIiOiI0ZmZkOGU4ZmQwNWI0MWU2ODJmMWZmMzM4MGRlYjM4MSJ9.sl2UrAq87CCBCCpzdWZZKiQAwH6R-T5eeQjeKXufONSXvJHD7XMvDV6cqeh4Ej_QpjNHRJuOmsYXsCmOTIFGD0Xbv_-fPrNnL8aUEtQXXcQQ3shrG3bZ419J7zR_H2Pt9GtB24F1kDJxMGkPUUH_P_2-4nc08lA7bHm8NiSKm1Tj-WkDNh9-VXlvj-krAs-f9eHTuyNOXx2Nvirv4pjlqhvU0Fzqg9mf3JMSb6gidcXvY8UQAwEl3Tj_mma0NlUwzY3Sofr7ib6UdlSSXapcu1tLcMLAbPREKiP7e9tuZoxxSls7ORr6xBBr4W6YUSUQwnBlIMyLwxjqLUryJMx7dP4O2Tg41dSQAMMQgJXWw2gwGURdhGntfN9Jqb5zfDsPm7hQYRxgxwAuo9Q1AvC8HnK5IIr1OUYam9G9ENNTiCTrrmJbjpEjIuulgIb88rZDYzCoDXyjTcKJofGtg8OjA5UTA45HauWewGNBE9V4pqSH6FrORv47OfNgL3nBOPTkYfwBgQg3GgCKNklrrkYRkKvThlFXb_W5TOJP9jZahnLOppwAtfjV08wIc2u-hQBgGzCyOfUHqt0XzygLwHigLjbfHwNzQlQUef_u9rZ3HZUyEvENRWthIZzm0t4wXrfJcIVw8JKft0n4mLQcKpAOBQSwTm0_9AexVbkps4EnUVU/g' inventory_aio
sed -i 's/{{REGISTY_USER}}/"12322401|ocp-311"/g' inventory_aio

#Replace the version of 3.11 (Need to see if we can do major to make this simpler)
sed -i 's/3.11.98/3.11.157/g' inventory_aio

## I think we need to manually install iptables? This failed first time, succeeded second
#TASK [os_firewall : Start and enable firewalld service] ****************************************************************************************************************************
#skipping: [t3-311.openshift.awsworkshop.io]

#TASK [os_firewall : need to pause here, otherwise the firewalld service starting can sometimes cause ssh to fail] ******************************************************************
#skipping: [t3-311.openshift.awsworkshop.io]
##
reboot

# After reboot
ansible-playbook -i inventory_aio /usr/share/ansible/openshift-ansible/playbooks/prerequisites.yml
ansible-playbook -i inventory_aio /usr/share/ansible/openshift-ansible/playbooks/deploy_cluster.yml

# This ran until Logging configuration and failed. TODO: Is this all that is left? Why is it failing?