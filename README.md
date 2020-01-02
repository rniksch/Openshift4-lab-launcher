# aws-ocp

## Overview

The solution within this repository is setup like a quickstart to make the code as re-usable and familiar as possible. It follows the same code structure and is capable of being tested with taskcat.

## Testing with TaskCat

### Pre-Reqs

To install [taskcat](#https://aws-quickstart.github.io/install-taskcat.html)

run make `make submodules`

If you do not have make configured, please download the submodules:

    git submodule init
    git submodule update

#### venv

    python3 -m venv ~/cloudformationvenv
    source ~/cloudformationvenv/bin/activate
    pip install awscli taskcat

#### Docker

Use the following Curl|Bash script (Feel free to look inside first) to "install" taskcat via Docker. I then moved `taskcat.docker` to `/usr/local/bin/taskcat`

    curl -s https://raw.githubusercontent.com/aws-quickstart/taskcat/master/installer/docker-installer.sh | sh
    mv taskcat.docker /usr/local/bin

### Testing

In order to test from taskcat you need an override file in your home .aws directory: `~/.aws/taskcat_global_override.json`

    [  
        {
            "ParameterKey": "KeyPairName",
            "ParameterValue": "<REPLACE_ME>"
        }
    ]

Please also verify the [.taskcat.yml](.taskcat.yml) is updated with the region you wish to deploy to. The rest of the parameters should be answered in the `.taskcat_overrides.yml` and not committed to code.

NOTE: We have seen issues running taskcat under the following conditions, please verify:
    * Your Environment variables for AWS are what you want as they override your `~/.aws/credentials` and `~/.aws/config`
    * You have initialized and updated the git submodules
    * You Account has the correct IAM Permissions to execute in the region.
    * Your default region and test region match.

Then you need to be above the repository directory and execute, with make: `make test`. Without make:
`taskcat -c aws-ocp/ci/config.yml`. Notice it is outside the actual repository.

When running a lot of tests, the S3 buckets can begin to add up. To clean up all Taskcat buckets you can run the following:
`aws s3 ls | grep taskcat | cut -d ' ' -f 3 | xargs -I {} aws s3 rb s3://{} --force`

## Debugging Ignition Lambda

To debug ignition lambda run

```bash
export PULL_SECRET=<YOUR PULL SECRET>
export SSH_KEY=<YOUR PUBLIC SSH_KEY>
make run_lambda
```

## OCP 3.x

## OCP 4.x

### OCP 4.1 Hardware Requirements

4 CPU, 8GB RAM, 35GB storage
