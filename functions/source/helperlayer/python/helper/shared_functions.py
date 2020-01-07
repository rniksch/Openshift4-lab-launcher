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

def install_dependencies(openshift_client_mirror_url, openshift_install_package, openshift_install_binary, download_path):
    sha256sum_file = 'sha256sum.txt'
    retries = 1
    url = openshift_client_mirror_url + sha256sum_file
    log.info("Downloading sha256sum file...")
    url_retreive(url, download_path + sha256sum_file)
    log.debug("Getting SHA256 hash for file {}".format(download_path + sha256sum_file))
    sha256sum_dict = parse_sha256sum_file(download_path + sha256sum_file)
    sha256sum = sha256sum_dict[openshift_install_package]

    # Download the openshift install binary only if it doesn't exist and retry download if the sha256sum doesn't match
    i = 0
    url = openshift_client_mirror_url + openshift_install_package
    while i <= retries:
        i += 1
        if os.path.exists(download_path + openshift_install_package):
            # Verify SHA256 hash
            if verify_sha256sum(download_path + openshift_install_package, sha256sum):
                log.info("OpenShift install client already exists in {}".format(download_path + openshift_install_package))
                break
        log.info("Downloading OpenShift install client...")
        url_retreive(url, download_path + openshift_install_package)
        if verify_sha256sum(download_path + openshift_install_package, sha256sum):
            log.info("Successfuly downloaded OpenShift install client...")
            break
    if not os.path.exists(download_path + openshift_install_binary):
        log.info("Extracting the OpenShift install client...")
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
        string = file.read()
    string = string.rstrip()
    # Parse file into a dictionary, the file format is
    # shasum  filename\nshasum1  filename1\n...
    tmp_dict = dict(item.split("  ") for item in string.split("\n"))
    # Swap keys and values
    sha256sums = dict((v,k) for k,v in tmp_dict.items())
    return sha256sums

def verify_sha256sum(filename, sha256sum):
    sha256_hash = hashlib.sha256()
    with open(filename,"rb") as file:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: file.read(4096),b""):
            sha256_hash.update(byte_block)
    if sha256_hash.hexdigest() == sha256sum:
        return True
    else:
        log.info("File {} SHA256 hash is {}".format(filename, sha256_hash.hexdigest()))
        log.info("Expecting {}".format(sha256sum))
        return False

def run_process(cmd):
    try:
        proc = subprocess.run([cmd], capture_output=True, shell=True)
        proc.check_returncode()
        log.info(proc.returncode)
        log.info(proc.stdout)
        log.info(proc.stderr)
    except subprocess.CalledProcessError as e:
        print("Error Detected on cmd {} with error {}".format(e.cmd, e.stderr))
        log.error(e.cmd)
        log.error(e.stderr)
        log.error(e.stdout)
        raise
    except OSError as e:
        print("Error Detected on cmd {} with error {}".format(e.cmd, e.stderr))
        log.error("OSError: {}".format(e.errno))
        log.error(e.strerror)
        log.error(e.filename)
        raise 

def upload_to_s3(download_path, student_cluster_name, s3_bucket):
    client = boto3.client('s3')
    folder = download_path + student_cluster_name
    log.info("Uploading {} to s3 bucket {}...".format(folder, s3_bucket))
    for subdir, dirs, files in os.walk(folder):
        for file in files:
            local_path = os.path.join(subdir, file)
            relative_path = os.path.relpath(local_path, folder)
            s3_path = os.path.join(student_cluster_name, relative_path)
            try:
                client.head_object(Bucket=s3_bucket, Key=s3_path)
                log.debug("File found on S3! Skipping {}...".format(s3_path))
            except:
                client.upload_file(local_path, s3_bucket, s3_path)

def delete_contents_s3(s3_bucket):
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(s3_bucket)
    bucket.objects.all().delete()


