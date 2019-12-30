import subprocess
import logging
import json
import urllib.request
import urllib.error
import os
import tarfile
import boto3
import hashlib
import sys
log = logging.getLogger(__name__)

def install_dependencies(openshift_client_mirror_url, openshift_install_package, download_path):
    sha256sum_file = 'sha256sum.txt'
    retries = 1
    url = openshift_client_mirror_url + sha256sum_file
    log.info("Downloading sha256sum file...")
    url_retreive(url, download_path + sha256sum_file)
    log.debug("Getting SHA256 hash for file {}".format(download_path + sha256sum_file))
    sha256sum_dict = parse_sha256sum_file(download_path + sha256sum_file)
    sha256sum = sha256sum_dict[openshift_install_package]

    # Download the openshift install binary and retry if the sha256sum doesn't match
    i = 0
    log.info("Downloading OpenShift install client...")
    url = openshift_client_mirror_url + openshift_install_package
    while i <= retries:
        i += 1
        if os.path.exists(download_path + openshift_install_package):
            # Verify SHA256 hash
            if verify_sha256sum(download_path + openshift_install_package, sha256sum):
                log.info("OpenShift install client already exists in {}".format(download_path + openshift_install_package))
                break
        url_retreive(url, download_path + openshift_install_package)
        if verify_sha256sum(download_path + openshift_install_package, sha256sum):
            log.info("Successfuly downloaded OpenShift install client...")
            break
    log.info("Extrating the OpenShift install client...")
    tar = tarfile.open(download_path + openshift_install_package)
    tar.extractall(path=download_path)
    tar.close()

def url_retreive(url, download_path):
    log.debug("Downloading from URL: {} to {}".format(url, download_path))
    try:
        response = urllib.request.urlretrieve(url, download_path)
    except urllib.error.HTTPError as e:
        log.error("Failed to download {} to {}".format(url, download_path))
        log.error("Error code: {}".format(e))
    except urllib.error.URLError as e:
        log.error("Reason: {}".format(e))
        sys.exit(1)

def parse_sha256sum_file(filename):
    with open(filename, 'r') as file:
        str = file.read()
    str = str.rstrip()
    # Parse file into a dictionary, the file format is
    # shasum  filename\nshasum1  filename1\n...
    tmp_dict = dict(item.split("  ") for item in str.split("\n"))
    # Swap keys and values
    sha256sums = dict((v,k) for k,v in tmp_dict.items())
    return sha256sums

def verify_sha256sum(filename, sha256sum):
    sha256_hash = hashlib.sha256()
    with open(filename,"rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096),b""):
            sha256_hash.update(byte_block)
    if sha256_hash.hexdigest() == sha256sum:
        return True
    else:
        log.info("File {} SHA256 hash is {}".format(filename, sha256_hash.hexdigest()))
        log.info("Expecting {}".format(sha256sum))
        return False

def generate_ignition_files(openshift_install_binary, path):
    log.info("Generating ignition files...")
    output = subprocess.run([path + openshift_install_binary], capture_output=True)
    pass

def upload_to_s3():
    pass

def lambda_handler(event, context):
    client = boto3.client('s3')
    buckets = client.list_buckets()
    s3_bucket = event['S3_BUCKET']
    pull_secret = event['PULL_SECRET']
    deployment_name = event['DEPLOYMENT_NAME']
    student_amount = event['STUDENT_AMOUNT']
    openshift_client_mirror_url = event['OPENSHIFT_MIRROR_URL']
    openshift_version = event['OPENSHIFT_VERSION']
    openshift_install_binary = event['OPENSHIFT_INSTALL_BINARY']
    file_extension = '.tar.gz'
    openshift_install_os = '-linux-'
    openshift_install_package = openshift_install_binary + openshift_install_os + openshift_version + file_extension
    binary_path = '/tmp/'
    log.info("Deployment name: " + event['DEPLOYMENT_NAME'])
    install_dependencies(openshift_client_mirror_url, openshift_install_package, binary_path)
    #generate_ignition_files(openshift_install_binary, binary_path)
