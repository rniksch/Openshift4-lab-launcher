from helper import shared_functions
import urllib.request
import urllib.error
import os
import logging
import sys
import boto3
from botocore.exceptions import ClientError
import subprocess
import shlex
import jinja2
import time
import json

log = logging.getLogger(__name__)

def get_from_s3(s3_bucket,student_cluster_name,key,dest_file_name):
    client = boto3.client('s3')
    s3_path = os.path.join(student_cluster_name, key)
    destination = os.path.join('/tmp',dest_file_name)
    if check_file_s3(s3_bucket,key=s3_path):
        client.download_file(s3_bucket, s3_path, destination)
        
def add_file_to_s3(s3_bucket,body,key, content_type, acl):
    client = boto3.client('s3')
    client.put_object(Body=body, Bucket=s3_bucket, Key=key, 
                    ContentType=content_type, ACL=acl)
    
def check_file_s3(s3_bucket,key):
    client = boto3.client('s3')
    try:
        client.head_object(Bucket=s3_bucket, Key=key)
        print("File at location {} found".format(key))
        return True
    except Exception as e:
        print("File not found at {} and key {}".format(s3_bucket,key))
        return False
    
def check_cluster_availability(url):
    response = False
    try: 
        urllib.request.urlopen(url)
    except urllib.error.URLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in e.reason.strerror:
            response = True
    except:
        print("Unhandled exception, cluster must not be ready")
    return response

def reduce_cluster_size(cluster_name, number_of_students, hosted_zone_name, 
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
        shared_functions.install_dependencies(openshift_client_mirror_url, 
                                            openshift_client_package, 
                                            openshift_client_binary, 
                                            download_path)
        get_from_s3(s3_bucket,student_cluster_name,key="auth/kubeconfig",
                    dest_file_name=student_cluster_name)
        # At this point:
        #   * OC should be in /tmp/oc
        #   * Current kubeconfig should be /tmp/<student_cluster_name>            
        cmd = "/opt/bin/openshift-4-scale-replicas /tmp/{}".format(student_cluster_name)
        try:
            shared_functions.run_process(cmd)
            add_file_to_s3(s3_bucket=s3_bucket,body="completed",key=complete_key,
                            content_type="text/plain", acl="private")
        except Exception as e:
            print(e)
            print("Unhandled Exception")

def deactivate_event(cluster_name):
    print("Deactivating event")
    client = boto3.client('events')
    event_name = cluster_name + "-ValidateEvent"
    response = client.disable_rule(Name=event_name)
    print(response)

def build_stack(cf_client,rebuild_array):
    # This creates a new Student environment.
    waiting_to_build = len(rebuild_array)
    while waiting_to_build > 0:
        for params in rebuild_array:
            try: 
                stack_result = cf_client.create_stack(**params)
                waiting_to_build = waiting_to_build - 1
            except Exception as e:
                print("Exception {}".format(e))
                print("Previous stack not deleted yet.")
        if waiting_to_build == 0:
            break
        else:
            print("Sleeping 20 seconds.")
            time.sleep(20)
            
def rebuild_stacks(cluster_name, failed_clusters, qss3bucket,
                            qss3keyprefix, student_template, s3_bucket):
    rebuild_array = []
    for failed_student in failed_clusters:
        print("Attempting to rebuild student {} stack".format(failed_student))
        cf_client = boto3.client("cloudformation")
        stack_name = '{}-{}'.format(cluster_name,failed_student)
        student_cluster_name = cluster_name + '-' + 'student' + str(failed_student)
        print("Student cluster name is {}".format(student_cluster_name))
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
            print("Stack was previously deleted, due to this need to read rebuild file")
            dest = student_cluster_name + "-rebuild.json"
            get_from_s3(s3_bucket,student_cluster_name,key="rebuild", dest_file_name=dest)
            rebuild_array.append(json.load(open("/tmp/{}".format(dest))))
    build_stack(cf_client,rebuild_array)

def generate_webtemplate(s3_bucket, cluster_name, number_of_students, 
                        hosted_zone_name, openshift_version, qss3bucket,
                            qss3keyprefix, student_template):
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
            cluster_data["clusters_information"].append(temp_dict)
        else:
            # Just need to know which index of the Students that failed to rebuild.
            failed_clusters.append(i)
    if len(cluster_data["clusters_information"]) > 0:
        print(cluster_data)
        try:
            j2Env = jinja2.Environment(loader = jinja2.FileSystemLoader("./templates"))
            template = j2Env.get_template("clusters.j2")
            print(template)
            rendered_text = template.render(cluster_data)
            #print("{}".format(rendered_text))
            add_file_to_s3(s3_bucket=s3_bucket,body=rendered_text,
                            key="workshop.html", content_type="text/html", 
                            acl="public-read")
        except Exception as e:
            print("Exception caught {}".format(e))
    if len(cluster_data["clusters_information"]) == number_of_students:
        deactivate_event(cluster_name)
    else:
        rebuild_stacks(cluster_name,failed_clusters, qss3bucket,
                            qss3keyprefix, student_template, s3_bucket)

def handler(event, context):
    try:
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
        file_extension = '.tar.gz'
        if sys.platform == 'darwin':
            openshift_install_os = '-mac-'
        else:
            openshift_install_os = '-linux-'
        openshift_client_package = openshift_client_binary + openshift_install_os + openshift_version + file_extension
        openshift_client_mirror_url = openshift_client_base_mirror_url + openshift_version + "/"
        download_path = '/tmp/'
        log.info("Cluster name: " + os.getenv('ClusterName'))
        reduce_cluster_size(cluster_name, number_of_students, hosted_zone_name, 
                        s3_bucket, openshift_client_mirror_url, 
                        openshift_client_package, openshift_client_binary, 
                        download_path)
        # We Rebuild stacks inside generate_webtemplate because
        # we want to ensure the webpage is created before in case
        # Rebuilding takes more than 15 mins. and the lambda times out.
        generate_webtemplate(s3_bucket, cluster_name, number_of_students, 
                            hosted_zone_name, openshift_version, qss3bucket,
                            qss3keyprefix, student_template)
        print("Complete")
    except Exception:
        logging.error('Unhandled exception', exc_info=True)