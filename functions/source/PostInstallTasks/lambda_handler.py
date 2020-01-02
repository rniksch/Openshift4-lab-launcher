from helper import shared_functions
import urllib.request
import urllib.error

def get_from_s3(s3_bucket,student_cluster_name,sub_folder):
    client = boto3.client('s3')
    s3_path = os.path.join(student_cluster_name, sub_folder)
    destination = os.path.join('/tmp',student_cluster_name)
    try:
        client.head_object(Bucket=s3_bucket, Key=s3_path)
        client.download_file(s3_bucket, s3_path, destination)
    except:
        print("File not found on S3! Skipping {}...".format(s3_path))

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

def generate_webtemplate(clusters_ready):
    print(clusters_ready)
    pass

def handler(event, context):
    try:
        s3_bucket = os.getenv('S3_BUCKET')
        cluster_name = os.getenv('ClusterName')
        number_of_students = int(os.getenv('NumStudents'))
        hosted_zone_name = os.getenv('HostedZoneName')
        openshift_client_base_mirror_url = os.getenv('OPENSHIFT_MIRROR_URL')
        openshift_version = os.getenv('OPENSHIFT_VERSION')
        openshift_install_binary = os.getenv('OPENSHIFT_INSTALL_BINARY')
        file_extension = '.tar.gz'
        if sys.platform == 'darwin':
            openshift_install_os = '-mac-'
        else:
            openshift_install_os = '-linux-'
        openshift_install_package = openshift_install_binary + openshift_install_os + openshift_version + file_extension
        openshift_client_mirror_url = openshift_client_base_mirror_url + openshift_version + "/"
        download_path = '/tmp/'
        
        log.info("Cluster name: " + os.getenv('ClusterName'))
        clusters_ready = []
        for i in range(number_of_students):
            student_cluster_name = cluster_name + '-' + 'student' + str(i)
            fqdn_student_cluster_name = cluster_name + '-' + 'student' + str(i) + "." + hosted_zone_name
            url="https://api." + fqdn_student_cluster_name + ":6443"
            if not check_cluster_availability(url=url):
                continue
            
            shared_functions.install_dependencies(openshift_client_mirror_url, openshift_install_package, openshift_install_binary, download_path)
            get_from_s3(s3_bucket,student_cluster_name,sub_folder="auth/kubeconfig")
            # At this point:
            #   * OC should be in /tmp/oc
            #   * Current kubeconfig should be /tmp/<student_cluster_name>            
            cmd = "./openshift-4-scale-replicas.sh {}".format(student_cluster_name)
            try:
                shared_functions.run_process(cmd)
                clusters_ready += i
            except Exception:
                print("Unhandled Exception")
            generate_webtemplate(clusters_ready, cluster_name)
        print("Complete")
    except Exception:
        logging.error('Unhandled exception', exc_info=True)