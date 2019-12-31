import subprocess
import logging
import json
import yaml
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

def generate_ignition_files(openshift_install_binary, download_path, student_cluster_name, ssh_key, pull_secret):
    assets_directory = download_path + student_cluster_name
    install_config_file = 'install-config.yaml'
    log.info("Generating ignition files for {}...".format(student_cluster_name))
    log.debug("Creating OpenShift assets directory for {}...".format(student_cluster_name))
    if not os.path.exists(assets_directory):
        os.mkdir(assets_directory)
    log.info("Generating install-config file for {}...".format(student_cluster_name))
    openshift_install_config = yaml.load(open(install_config_file, 'r'), Loader=yaml.FullLoader)
    openshift_install_config['metadata']['name'] = student_cluster_name
    openshift_install_config['sshKey'] = ssh_key
    openshift_install_config['pullSecret'] = pull_secret
    cluster_install_config_file = os.path.join(assets_directory, install_config_file)
    # Using this to get around the ssh-key multiline issue in yaml
    yaml.dump(openshift_install_config, open(cluster_install_config_file, 'w'), explicit_start=True, default_style='\"', width=4096)
    log.info("Generating manifests for {}...".format(student_cluster_name))
    cmd = download_path + openshift_install_binary + " create manifests --dir {}".format(assets_directory)
    run_process(cmd)
    log.info("Tweak manifests for {}...".format(student_cluster_name))
    cluster_scheduler_manifest = os.path.join(assets_directory, 'manifests', 'cluster-scheduler-02-config.yml')
    manifest = yaml.load(open(cluster_scheduler_manifest), Loader=yaml.FullLoader)
    manifest['spec']['mastersSchedulable'] = False
    yaml.dump(manifest, open(cluster_scheduler_manifest, 'w'))
    log.info("Generate ignition files for {}...".format(student_cluster_name))
    cmd = download_path + openshift_install_binary + " create ignition-configs --dir {}".format(assets_directory)
    run_process(cmd)

def run_process(cmd):
    try:
        proc = subprocess.run([cmd], capture_output=True, shell=True)
        proc.check_returncode()
        log.info(proc.returncode)
        log.info(proc.stdout)
        log.info(proc.stderr)
    except subprocess.CalledProcessError as e:
        log.error(e.cmd)
        log.error(e.stderr)
        log.error(e.stdout)
        sys.exit(1)
    except OSError as e:
        log.error("OSError: {}".format(e.errno))
        log.error(e.strerror)
        log.error(e.filename)
        sys.exit(1)

def upload_to_s3(download_path, student_cluster_name, s3_bucket):
    client = boto3.client('s3')
    folder = download_path + student_cluster_name
    response = client.list_buckets()
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

def lambda_handler(event, context):
    s3_bucket = event['S3_BUCKET']
    pull_secret = event.get('PULL_SECRET', os.getenv('PULL_SECRET'))
    ssh_key = event.get('SSH_KEY', os.environ.get('SSH_KEY'))
    deployment_name = event['DEPLOYMENT_NAME']
    student_amount = event['STUDENT_AMOUNT']
    openshift_client_mirror_url = event['OPENSHIFT_MIRROR_URL']
    openshift_version = event['OPENSHIFT_VERSION']
    openshift_install_binary = event['OPENSHIFT_INSTALL_BINARY']
    file_extension = '.tar.gz'
    if sys.platform == 'darwin':
        openshift_install_os = '-mac-'
    else:
        openshift_install_os = '-linux-'
    openshift_install_package = openshift_install_binary + openshift_install_os + openshift_version + file_extension
    download_path = '/tmp/'

    log.info("Deployment name: " + event['DEPLOYMENT_NAME'])
    install_dependencies(openshift_client_mirror_url, openshift_install_package, openshift_install_binary, download_path)
    for i in range(student_amount):
        student_cluster_name = deployment_name + '-' + 'student-' + str(i)
        generate_ignition_files(openshift_install_binary, download_path, student_cluster_name, ssh_key, pull_secret)
        upload_to_s3(download_path, student_cluster_name, s3_bucket)
