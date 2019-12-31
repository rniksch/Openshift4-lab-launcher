#!/bin/bash
CLUSTERNAME=trace3
NUM_STUDENTS=2
S3_BUCKET=s3://ignition-bucket
# Make a new directory, copy the install-config, run the create manaifests
# Upadte a manifest and create the ignition files.
for ((i=0 ; i < ${NUM_STUDENTS}; i++)); do
  STUDENT_CLUSTER_NAME=${CLUSTERNAME}-student${i}
  mkdir ${STUDENT_CLUSTER_NAME};
  sed "s|trace3-student|${STUDENT_CLUSTER_NAME}|g" install-config.yaml > ${STUDENT_CLUSTER_NAME}/install-config.yaml;
  openshift-install create manifests --dir=${STUDENT_CLUSTER_NAME}/;
  cd ${STUDENT_CLUSTER_NAME}/;
  python -c '
import yaml;
path = "manifests/cluster-scheduler-02-config.yml"
data = yaml.load(open(path));
data["spec"]["mastersSchedulable"] = False'
  cd ..;
  openshift-install create ignition-configs --dir=${STUDENT_CLUSTER_NAME}/;
  # Upload to an S3 bucket and ensure the aws-ocp-student-env.template.yaml bucket matches where you
  aws s3 cp --recursive ${STUDENT_CLUSTER_NAME}/ ${S3_BUCKET}/${STUDENT_CLUSTER_NAME}/
done 

 
