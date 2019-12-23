#!/bin/bash

# Make a new directory, copy the install-config, run the create manaifests
# Upadte a manifest and create the ignition files.
mkdir aio; cp install-config.yaml aio/; openshift-install create manifests --dir=aio/;python -c '
import yaml;
path = "aio/manifests/cluster-scheduler-02-config.yml"
data = yaml.load(open(path));
data["spec"]["mastersSchedulable"] = False'; openshift-install create ignition-configs --dir=aio/; 

# Upload to an S3 bucket and ensure the aws-ocp-student-env.template.yaml bucket matches where you
# Place this
#aws s3 