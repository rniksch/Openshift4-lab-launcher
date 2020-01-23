import urllib.request
import urllib.error
from ruamel import yaml
import cfnresponse
import os
import logging
import sys
import hashlib
import tarfile
import boto3
from botocore.exceptions import ClientError
import subprocess
import jinja2
import time
import json

log = logging.getLogger(__name__)

##############################################
# Deploy CF Code
##############################################

def stack_exists(cf_client, stack_name):
    stack_status_codes = ['CREATE_COMPLETE',
                          'CREATE_IN_PROGRESS',
                          'UPDATE_COMPLETE',
                          'UPDATE_ROLLBACK_COMPLETE',
                          'ROLLBACK_COMPLETE',
                          'CREATE_FAILED',
                          'DELETE_IN_PROGRESS',
                          'DELETE_FAILED']
    for s in stacks_by_status(cf_client, stack_status_codes):
        if s.get('StackName', '') == stack_name:
            return s
    return None

def stacks_by_status(cf_client, status_include_filter):
    """
    ``status_include_filter`` should be a list ...
    """
    pages = cf_client.get_paginator('list_stacks').paginate(
        StackStatusFilter=status_include_filter)
    for page in pages:
        for s in page.get('StackSummaries', []):
            yield s

def parse_properties(properties):
    cf_params = {'Capabilities': ['CAPABILITY_IAM',
                                  'CAPABILITY_AUTO_EXPAND',
                                  'CAPABILITY_NAMED_IAM'],
                'DisableRollback': True
    }
    cf_params["Parameters"] = []
    for key, value in properties.items():
        if key == "StackName":
            cf_params["StackName"] = value
        elif key == "TemplateURL":
            cf_params["TemplateURL"] = value
        elif key == "NumStacks":
            cf_params["NumStacks"] = int(value)
        elif key == "KeyToUpdate":
            cf_params["KeyToUpdate"] = value
        elif key == "ServiceToken" or key == "Function":
            log.debug("Skipping over unneeded keys")
        else:
            temp = {'ParameterKey': key, 'ParameterValue': value}
            log.debug(temp)
            cf_params["Parameters"].append(temp)
    return cf_params

def set_cloud9_password(event, cf_params, student_number, s3_bucket):
    if event["ResourceProperties"]["CreateCloud9Instance"] and not event["ResourceProperties"]["Cloud9UserPassword"]:
        # Get kubeadmin password and set Cloud9UserPassword
        for param in cf_params["Parameters"]:
            if param["ParameterKey"] == "Cloud9UserPassword":
                student_cluster_name = event["ResourceProperties"]["ClusterName"] + '-' + 'student' + str(student_number)
                param["ParameterValue"] = get_kubeadmin_pass(s3_bucket, student_cluster_name)

def get_kubeadmin_pass(s3_bucket, student_cluster_name):
    dest = student_cluster_name + "-admin"
    get_from_s3(s3_bucket, student_cluster_name, key="auth/kubeadmin-password", dest_file_name=dest)
    cur_file = open("/tmp/{}".format(dest), "r")
    return cur_file.read()

def loop_child_stacks(cf_client, cf_params, action, event, **kwargs):
    waiter_array = []
    numStacks = 1
    current_numStacks = 0
    found = False
    counter = 0
    if "KeyToUpdate" in cf_params:
        for param in cf_params["Parameters"]:
            log.debug(param)
            if param["ParameterKey"] == cf_params["KeyToUpdate"]:
                found = True
                break
            counter += 1
        del cf_params["KeyToUpdate"]
    if action == "update":
        if "NumStacks" in cf_params and "NumStacks" in kwargs["old_params"]:
            log.debug("current is {} and old is {}".format(cf_params["NumStacks"],kwargs["old_params"]["NumStacks"]))
            if cf_params["NumStacks"] > kwargs["old_params"]["NumStacks"]:
                numStacks = cf_params["NumStacks"]
                del cf_params["NumStacks"]
            else:
                log.debug("Found old params higher")
                numStacks = kwargs["old_params"]["NumStacks"]
                current_numStacks = cf_params["NumStacks"]
                del cf_params["NumStacks"]
    elif "NumStacks" in cf_params:
        numStacks = cf_params["NumStacks"]
        del cf_params["NumStacks"]
    stack_state = 'stack_create_complete'
    for x in range(numStacks):
        if found:
            cf_params["Parameters"][counter]["ParameterValue"] = str(x)
        original_name = cf_params["StackName"]
        cf_params["StackName"] = "{}-{}".format(cf_params["StackName"],x)
        stack = stack_exists(cf_client=cf_client, stack_name=cf_params["StackName"])
        cur_action = action
        if 'kwargs["old_params"]' in vars():
            log.debug("action is {} and x is {} and old_params Numstacks {}".format(action,x,kwargs["old_params"]["NumStacks"]))
        if action == "update":
            log.debug(current_numStacks)
            if current_numStacks and (x+1) > current_numStacks:
                log.debug("setting cur_action to delete")
                cur_action = "delete"
            else:
                cur_action = "create"
        if cur_action == "create" and stack == None:
            set_cloud9_password(event, cf_params, x, kwargs["s3_bucket"])
            log.debug("CF PARAMS: {}".format(cf_params))
            stack_result = cf_client.create_stack(**cf_params)

        elif cur_action == "delete" and stack:
            log.debug("found and deleting stack")
            stack_result = cf_client.delete_stack(StackName=cf_params["StackName"])
            stack_state = 'stack_delete_complete'

        waiter_array.append({
            "stack_name": cf_params["StackName"],
            "stack_state": stack_state})

        cf_params["StackName"] = original_name

    wait_to_complete(cf_client, waiter_array)

def wait_to_complete(cf_client, waiter_array):
    while( len(waiter_array) > 0 ):
        cur_waiter = waiter_array.pop()
        waiter = cf_client.get_waiter(cur_waiter["stack_state"])
        log.info('...waiting for stack to be ready...')
        try:
            waiter.wait(StackName=cur_waiter["stack_name"])
        except Exception as e:
            log.error("Caught exception in Waiter..{}".format(e))
        stack = stack_exists(cf_client=cf_client, stack_name=cur_waiter["stack_name"])

##############################################
# END Deploy CF Code
##############################################

def install_dependencies(openshift_client_mirror_url, openshift_install_package, openshift_install_binary, download_path):
    sha256sum_file = 'sha256sum.txt'
    retries = 1
    url = openshift_client_mirror_url + sha256sum_file
    log.info("Downloading sha256sum file for OpenShift install client...")
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

def update_cidr(student_num,multiplicitive,cidr,octect):
    # If we have 10.30.0.0/16 and we need to update .30 we need to split and grab the second octect
    # But computers start at 0 so it would be '1'
    ip = cidr.split('.')
    ip[octect] = int(ip[octect]) + (student_num*multiplicitive)
    return '.'.join(map(str, ip))

def generate_ignition_files(openshift_install_binary, download_path, student_cluster_name, ssh_key, pull_secret, hosted_zone_name, student_num):
    assets_directory = download_path + student_cluster_name
    install_config_file = 'install-config.yaml'
    log.debug("Creating OpenShift assets directory for {}...".format(student_cluster_name))
    if not os.path.exists(assets_directory):
        os.mkdir(assets_directory)
    log.info("Generating install-config file for {}...".format(student_cluster_name))
    openshift_install_config = yaml.safe_load(open(install_config_file, 'r'))
    openshift_install_config['metadata']['name'] = student_cluster_name
    openshift_install_config['sshKey'] = ssh_key
    openshift_install_config['pullSecret'] = pull_secret
    openshift_install_config['baseDomain'] = hosted_zone_name

    # Network updates
    orig_cluster_network = openshift_install_config['networking']['clusterNetwork'][0]['cidr']
    # We need to update the cluster networks 10.30.0.0/16 to 10.31.0.0/16 or +1 in second octect for each student
    openshift_install_config['networking']['clusterNetwork'][0]['cidr'] = update_cidr(student_num,1,orig_cluster_network,1)
    orig_service_network = openshift_install_config['networking']['serviceNetwork'][0]
    openshift_install_config['networking']['serviceNetwork'][0] = update_cidr(student_num,1,orig_service_network,1)

    cluster_install_config_file = os.path.join(assets_directory, install_config_file)
    # Using this to get around the ssh-key multiline issue in yaml
    yaml.dump(openshift_install_config,
              open(cluster_install_config_file, 'w'),
              explicit_start=True, default_style='\"',
              width=4096)
    log.info("Generating manifests for {}...".format(student_cluster_name))
    cmd = download_path + openshift_install_binary + " create manifests --dir {}".format(assets_directory)
    run_process(cmd)
    #log.info("Tweak manifests for {}...".format(student_cluster_name))
    #cluster_scheduler_manifest = os.path.join(assets_directory, 'manifests', 'cluster-scheduler-02-config.yml')
    #manifest = yaml.safe_load(open(cluster_scheduler_manifest))
    #manifest['spec']['mastersSchedulable'] = False
    #yaml.dump(manifest, open(cluster_scheduler_manifest, 'w'))
    log.info("Generating ignition files for {}...".format(student_cluster_name))
    cmd = download_path + openshift_install_binary + " create ignition-configs --dir {}".format(assets_directory)
    run_process(cmd)

def run_process(cmd):
    try:
        proc = subprocess.run([cmd], capture_output=True, shell=True)
        proc.check_returncode()
        log.debug(proc.returncode)
        log.debug(proc.stdout)
        log.debug(proc.stderr)
    except subprocess.CalledProcessError as e:
        log.error("Error Detected on cmd {} with error {}".format(e.cmd, e.stderr))
        log.error(e.cmd)
        log.error(e.stderr)
        log.error(e.stdout)
        raise
    except OSError as e:
        log.error("Error Detected on cmd {} with error {}".format(e.cmd, e.stderr))
        log.error("OSError: {}".format(e.errno))
        log.error(e.strerror)
        log.error(e.filename)
        raise

def upload_file_to_s3(s3_path, local_path, s3_bucket):
    client = boto3.client('s3')
    log.info("Uploading {} to s3 bucket {}...".format(local_path, os.path.join(s3_bucket, s3_path)))
    try:
        client.head_object(Bucket=s3_bucket, Key=s3_path)
        log.debug("File found on S3! Skipping {}...".format(s3_path))
    except:
        client.upload_file(local_path, s3_bucket, s3_path)

def upload_ignition_files_to_s3(local_student_folder, s3_bucket):
    files_to_upload = ['auth/kubeconfig', 'auth/kubeadmin-password', 'master.ign', 'bootstrap.ign'] 
    for file in files_to_upload:
        s3_path = os.path.join(os.path.basename(local_student_folder), file)
        local_path = os.path.join(local_student_folder, file)
        upload_file_to_s3(s3_path, local_path, s3_bucket)

def delete_contents_s3(s3_bucket):
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(s3_bucket)
    bucket.objects.all().delete()

def get_from_s3(s3_bucket,student_cluster_name,key,dest_file_name):
    client = boto3.client('s3')
    s3_path = os.path.join(student_cluster_name, key)
    destination = os.path.join('/tmp',dest_file_name)
    if check_file_s3(s3_bucket,key=s3_path):
        client.download_file(s3_bucket, s3_path, destination)

def add_file_to_s3(s3_bucket, body, key, content_type, acl):
    client = boto3.client('s3')
    client.put_object(Body=body, Bucket=s3_bucket, Key=key,
                    ContentType=content_type, ACL=acl)

def check_file_s3(s3_bucket,key):
    client = boto3.client('s3')
    try:
        client.head_object(Bucket=s3_bucket, Key=key)
        log.debug("File at location {} found".format(key))
        return True
    except Exception as e:
        log.debug("File not found at {} and key {}".format(s3_bucket,key))
        return False

def check_cluster_availability(url):
    response = False
    try:
        urllib.request.urlopen(url)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in e.reason.strerror:
            response = True
            log.debug("Cluster is reachable at {}".format(url))
    except:
        log.error("Unhandled exception, cluster must not be ready")
    return response

def scale_ocp_replicas(cluster_name, number_of_students, hosted_zone_name,
                        s3_bucket, openshift_client_mirror_url,
                        openshift_client_package, openshift_client_binary,
                        download_path):
    for i in range(number_of_students):
        student_cluster_name = cluster_name + '-' + 'student' + str(i)
        fqdn_student_cluster_name = cluster_name + '-' + 'student' + str(i) + "." + hosted_zone_name
        complete_key = os.path.join(student_cluster_name, "completed")
        url="https://api." + fqdn_student_cluster_name + ":6443"
        if not check_cluster_availability(url=url):
            continue
        if check_file_s3(s3_bucket=s3_bucket,key=complete_key):
           continue
        install_dependencies(openshift_client_mirror_url,
                                            openshift_client_package,
                                            openshift_client_binary,
                                            download_path)
        get_from_s3(s3_bucket,student_cluster_name,key="auth/kubeconfig",
                    dest_file_name=student_cluster_name)
        # At this point:
        #   * OC should be in /tmp/oc
        #   * Current kubeconfig should be /tmp/<student_cluster_name>
        cmd = "./bin/openshift-4-scale-replicas /tmp/{}".format(student_cluster_name)
        try:
            run_process(cmd)
            add_file_to_s3(s3_bucket=s3_bucket,body="completed",key=complete_key,
                            content_type="text/plain", acl="private")
        except Exception as e:
            log.error(e)
            log.error("Unhandled Exception")

def deactivate_event(cluster_name):
    log.info("Deactivating event")
    client = boto3.client('events')
    event_name = cluster_name + "-ValidateEvent"
    response = client.disable_rule(Name=event_name)
    log.debug(response)

def build_stack(cf_client,rebuild_array):
    # This creates a new Student environment.
    waiting_to_build = len(rebuild_array)
    while waiting_to_build > 0:
        for params in rebuild_array:
            try:
                stack_result = cf_client.create_stack(**params)
                waiting_to_build = waiting_to_build - 1
            except Exception as e:
                log.error("Exception {}".format(e))
                log.error("Previous stack not deleted yet.")
        if waiting_to_build == 0:
            break
        else:
            log.info("Sleeping 20 seconds.")
            time.sleep(20)

def rebuild_stacks(cluster_name, failed_clusters, qss3bucket,
                   qss3keyprefix, student_template, s3_bucket):
    rebuild_array = []
    for failed_student in failed_clusters:
        cf_client = boto3.client("cloudformation")
        stack_name = '{}-{}'.format(cluster_name,failed_student)
        log.info("Attempting to rebuild {} stack".format(stack_name))
        student_cluster_name = cluster_name + '-' + 'student' + str(failed_student)
        log.debug("Student cluster name is {}".format(student_cluster_name))
        rebuild_key = os.path.join(student_cluster_name, "rebuild")
        try:
            stack = cf_client.describe_stacks(StackName=stack_name)
            response = cf_client.delete_stack(StackName=stack_name)
            if response["ResponseMetadata"]["HTTPStatusCode"] == 200:
                new_dict = {"StackName": stack["Stacks"][0]["StackName"] }
                new_dict["Capabilities"] = stack["Stacks"][0]["Capabilities"]
                new_dict["Parameters"] = stack["Stacks"][0]["Parameters"]
                # Template URL can be built based on parameters in it with
                # replacing QSS3BucketName and QSS3KeyPrefix and StudentTemplate
                # Below is already converted
                new_dict["TemplateURL"] = "https://{}.s3.amazonaws.com/{}templates/{}".format(qss3bucket,
                        qss3keyprefix, student_template)
                add_file_to_s3(s3_bucket=s3_bucket,body=json.dumps(new_dict),key=rebuild_key,
                            content_type="text/json", acl="private")
                rebuild_array.append(new_dict)
        except ClientError as e:
            log.debug("Stack was previously deleted, due to this need to read rebuild file")
            dest = student_cluster_name + "-rebuild.json"
            get_from_s3(s3_bucket,student_cluster_name,key="rebuild", dest_file_name=dest)
            rebuild_array.append(json.load(open("/tmp/{}".format(dest))))
    build_stack(cf_client,rebuild_array)

def generate_webtemplate(s3_bucket, cluster_name, number_of_students,
                         hosted_zone_name, openshift_version, qss3bucket,
                         qss3keyprefix, student_template, create_cloud9_instance):
    cluster_data = {"cluster_name": cluster_name,
                    "openshift_version": openshift_version,
                    "clusters_information": [] }
    failed_clusters = []
    for i in range(number_of_students):
        student_cluster_name = cluster_name + '-' + 'student' + str(i)
        complete_key = os.path.join(student_cluster_name, "completed")
        if check_file_s3(s3_bucket=s3_bucket,key=complete_key):
            dest = student_cluster_name + "-admin"
            get_from_s3(s3_bucket,student_cluster_name,key="auth/kubeadmin-password", dest_file_name=dest)
            cur_file = open("/tmp/{}".format(dest), "r")
            temp_dict = {"cluster_name": student_cluster_name,
                         "number": i,
                         "kubeadmin-password": cur_file.read(),
                         "console-url": "https://console-openshift-console.apps.{}.{}".format(student_cluster_name, hosted_zone_name),
                         "ssh-url": "ssh.{}.{}".format(student_cluster_name, hosted_zone_name)
            }
            if create_cloud9_instance:
                temp_dict["cloud_9_url"] = "https://console.aws.amazon.com/cloud9"
            cluster_data["clusters_information"].append(temp_dict)
        else:
            # Just need to know which index of the Students that failed to rebuild.
            failed_clusters.append(i)
    if len(cluster_data["clusters_information"]) > 0:
        log.debug(cluster_data)
        try:
            j2Env = jinja2.Environment(loader = jinja2.FileSystemLoader("./templates"))
            template = j2Env.get_template("clusters.j2")
            rendered_text = template.render(cluster_data)
            add_file_to_s3(s3_bucket=s3_bucket,body=rendered_text,
                            key="workshop.html", content_type="text/html",
                            acl="public-read")
        except Exception as e:
            log.error("Exception caught {}".format(e))
    if len(cluster_data["clusters_information"]) == number_of_students:
        deactivate_event(cluster_name)
    else:
        rebuild_stacks(cluster_name, failed_clusters, qss3bucket,
                            qss3keyprefix, student_template, s3_bucket)

def handler(event, context):
    status = cfnresponse.SUCCESS
    level = logging.getLevelName(os.getenv('LogLevel'))
    log.setLevel(level)
    log.debug(event)
    s3_bucket = os.getenv('AuthBucket')
    cluster_name = os.getenv('ClusterName')
    number_of_students = int(os.getenv('NumStudents'))
    hosted_zone_name = os.getenv('HostedZoneName')
    openshift_client_base_mirror_url = os.getenv('OpenShiftMirrorURL')
    openshift_version = os.getenv('OpenShiftVersion')
    openshift_client_binary = os.getenv('OpenShiftClientBinary')
    student_template = os.getenv("StudentTemplate")
    qss3bucket = os.getenv("QSS3BucketName")
    qss3keyprefix = os.getenv("QSS3KeyPrefix")
    create_cloud9_instance = os.getenv("CreateCloud9Instance")
    file_extension = '.tar.gz'
    if sys.platform == 'darwin':
        openshift_install_os = '-mac-'
    else:
        openshift_install_os = '-linux-'
    openshift_client_package = openshift_client_binary + openshift_install_os + openshift_version + file_extension
    openshift_client_mirror_url = openshift_client_base_mirror_url + openshift_version + "/"
    download_path = '/tmp/'
    log.info("Cluster name: " + os.getenv('ClusterName'))
    # Run generate ignition files functions
    if 'RequestType' in event.keys() and event['ResourceProperties']['Function'] == 'GenerateIgnition':
        try:
            if event['RequestType'] == 'Delete':
                log.info("Delete request found, initiating..")
                delete_contents_s3(s3_bucket=s3_bucket)
            elif event['RequestType'] == 'Update':
                log.info("Update sent, however, this is unsupported at this time.")
                pass
            else:
                log.info("Delete and Update not detected, proceeding with Create")
                pull_secret = event['ResourceProperties'].get('PullSecret', os.getenv('PULL_SECRET'))
                ssh_key = event['ResourceProperties'].get('SSHKey', os.environ.get('SSH_KEY'))
                openshift_install_binary = event['ResourceProperties']['OpenShiftInstallBinary']
                openshift_install_package = openshift_install_binary + openshift_install_os + openshift_version + file_extension

                log.info("Generating OCP installation files for cluster " + cluster_name)
                install_dependencies(openshift_client_mirror_url, openshift_install_package, openshift_install_binary, download_path)
                for i in range(number_of_students):
                    student_cluster_name = cluster_name + '-' + 'student' + str(i)
                    generate_ignition_files(openshift_install_binary, download_path,
                                            student_cluster_name, ssh_key, pull_secret,
                                            hosted_zone_name, student_num=i)
                    local_student_folder = download_path + student_cluster_name
                    upload_ignition_files_to_s3(local_student_folder, s3_bucket)
                    building_key = os.path.join(student_cluster_name, "building")
                    add_file_to_s3(s3_bucket=s3_bucket,body="building",key=building_key,
                                    content_type="text/plain", acl="private")
            log.info("Complete")
        except Exception:
            logging.error('Unhandled exception', exc_info=True)
            status = cfnresponse.FAILED
        finally:
            cfnresponse.send(event, context, status, {}, None)
    elif 'RequestType' in event.keys() and event['ResourceProperties']['Function'] == 'DeployCF':
        try:
            cf_client = boto3.client('cloudformation')
            cf_params = parse_properties(event['ResourceProperties'])
            log.debug(cf_params)
            if event['RequestType'] == 'Delete':
                log.debug("Inside delete")
                log.info(event)
                loop_child_stacks(cf_client=cf_client, cf_params=cf_params, action="delete", event=event)
            elif event['RequestType'] == 'Update':
                old_params = parse_properties(event['OldResourceProperties'])
                log.debug("Inside update and old_params is {}".format(old_params))
                loop_child_stacks(cf_client=cf_client, cf_params=cf_params, action="update", event=event, old_params=old_params)
            else:
                loop_child_stacks(cf_client=cf_client, cf_params=cf_params, action="create", event=event, s3_bucket=s3_bucket)
            log.info("Completed")
        except Exception:
            logging.error('Unhandled exception', exc_info=True)
            status = cfnresponse.FAILED
        finally:
            cfnresponse.send(event, context, status, {}, None)
    else:
        try:
            scale_ocp_replicas(cluster_name, number_of_students, hosted_zone_name,
                               s3_bucket, openshift_client_mirror_url,
                               openshift_client_package, openshift_client_binary,
                               download_path)
            # We Rebuild stacks inside generate_webtemplate because
            # we want to ensure the webpage is created before in case
            # Rebuilding takes more than 15 mins. and the lambda times out.
            generate_webtemplate(s3_bucket, cluster_name, number_of_students,
                                 hosted_zone_name, openshift_version, qss3bucket,
                                 qss3keyprefix, student_template, create_cloud9_instance)
            log.info("Complete")
        except Exception:
            logging.error('Unhandled exception', exc_info=True)
