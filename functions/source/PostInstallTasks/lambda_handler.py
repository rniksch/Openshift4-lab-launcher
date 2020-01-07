from helper import shared_functions
import urllib.request
import urllib.error
import os
import logging
import sys
import boto3
import subprocess
import shlex
import jinja2
import time
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
        print("File not found")
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
        # ON our first found cluster that is ready let's sleep 5 minutes before executing.
        sleep = True
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
            if sleep:
                print("Sleeping")
                time.sleep(300)
                sleep = False
            
            shared_functions.run_process(cmd)
            add_file_to_s3(s3_bucket=s3_bucket,body="completed",key=complete_key,
                            content_type="text/plain", acl="private")
        except Exception as e:
            print(e)
            print("adding file even though it failed.")
            #add_file_to_s3(s3_bucket=s3_bucket,body="completed",key=complete_key,
            #                content_type="text/plain", acl="private")
            print("Unhandled Exception")

def deactivate_event(cluster_name):
    print("Deactivating event")
    client = boto3.client('events')
    event_name = cluster_name + "-ValidateEvent"
    response = client.disable_rule(Name=event_name)
    print(response)
            
def generate_webtemplate(s3_bucket, cluster_name, number_of_students, 
                        hosted_zone_name, openshift_version):
    cluster_data = {"cluster_name": cluster_name, 
                    "openshift_version": openshift_version,
                    "clusters_information": [] }
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

def handler(event, context):
    try:
        s3_bucket = os.getenv('AuthBucket')
        cluster_name = os.getenv('ClusterName')
        number_of_students = int(os.getenv('NumStudents'))
        hosted_zone_name = os.getenv('HostedZoneName')
        openshift_client_base_mirror_url = os.getenv('OpenShiftMirrorURL')
        openshift_version = os.getenv('OpenShiftVersion')
        openshift_client_binary = os.getenv('OpenShiftClientBinary')
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
        generate_webtemplate(s3_bucket, cluster_name, number_of_students, 
                            hosted_zone_name, openshift_version)
        print("Complete")
    except Exception:
        logging.error('Unhandled exception', exc_info=True)