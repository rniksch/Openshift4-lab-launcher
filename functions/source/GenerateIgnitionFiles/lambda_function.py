import subprocess
import logging
import json
import urllib.request
import os
import tarfile
import boto3
log = logging.getLogger(__name__)

def install_dependencies(openshift_client_mirror_url, openshift_install_package, path):
    url = openshift_client_mirror_url + openshift_install_package
    log.info("Downloading OpenShift install client...")
    log.debug("Using URL: {}".format(url))
    urllib.request.urlretrieve(url, path + openshift_install_package)
    tar = tarfile.open(path + openshift_install_package)
    tar.extractall(path=path)
    tar.close()
    pass

def generate_ignition_files(openshift_install_binary, path):
    log.info("Generating ignition files...")
    output = subprocess.run([path + openshift_install_binary], capture_output=True)
    pass

def upload_to_s3():
    pass

def lambda_handler(event, context):
    client = boto3.client('s3')
    buckets = client.list_buckets()
    openshift_client_mirror_url = "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/"
    openshift_version = '4.2.12'
    file_extension = '.tar.gz'
    openshift_install_binary = 'openshift-install'
    openshift_install_os = '-linux-'
    openshift_install_package = openshift_install_binary + openshift_install_os + openshift_version + file_extension
    path = '/tmp/'

    install_dependencies(openshift_client_mirror_url, openshift_client_binary, path)
    generate_ignition_files(openshift_install_binary, path)
