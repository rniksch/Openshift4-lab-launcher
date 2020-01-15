import cfnresponse
import logging
import boto3
import datetime
logger = logging.getLogger(__name__)

def stack_exists(cf_client, stack_name):
    stack_status_codes = [
                        'CREATE_COMPLETE',
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
        elif key == "ServiceToken":
            print("Skipping over ServiceToken")
        else:
            temp = {'ParameterKey': key, 'ParameterValue': value}
            print(temp)
            cf_params["Parameters"].append(temp)
    return cf_params

def loop_child_stacks(cf_client, cf_params, action, **kwargs):
    waiter_array = []
    numStacks = 1
    current_numStacks = 0
    found = False
    counter = 0
    if "KeyToUpdate" in cf_params:
        print("in key to Update")
        for param in cf_params["Parameters"]:
            print(param)
            if param["ParameterKey"] == cf_params["KeyToUpdate"]:
                found = True
                break
            counter += 1
        del cf_params["KeyToUpdate"]
    if action == "update":
        if "NumStacks" in cf_params and "NumStacks" in kwargs["old_params"]:
            print("current is {} and old is {}".format(cf_params["NumStacks"],kwargs["old_params"]["NumStacks"]))
            if cf_params["NumStacks"] > kwargs["old_params"]["NumStacks"]:
                numStacks = cf_params["NumStacks"]
                del cf_params["NumStacks"]
            else:
                print("Found old params higher")
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
            print("action is {} and x is {} and old_params Numstacks {}".format(action,x,kwargs["old_params"]["NumStacks"]))
        if action == "update":
            print(current_numStacks)
            if current_numStacks and (x+1) > current_numStacks:
                print("setting cur_action to delete")
                cur_action = "delete"
            else:
                cur_action = "create"
        if cur_action == "create" and stack == None:
            stack_result = cf_client.create_stack(**cf_params)
        
        elif cur_action == "delete" and stack:
            print("found and deleting stack")
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
        print(waiter.config)
        print('...waiting for stack to be ready...')
        try:
            waiter.wait(StackName=cur_waiter["stack_name"])
        except Exception as e:
            print("Caught exception in Waiter..{}".format(e))
        stack = stack_exists(cf_client=cf_client, stack_name=cur_waiter["stack_name"])

def handler(event,context):
    logger.debug(event)
    status = cfnresponse.SUCCESS
    try:
        cf_client = boto3.client('cloudformation')
        cf_params = parse_properties(event['ResourceProperties'])
        if event['RequestType'] == 'Delete':
            print("Inside delete")
            logger.info(event)
            loop_child_stacks(cf_client=cf_client, cf_params=cf_params, action="delete")
        elif event['RequestType'] == 'Update':
            old_params = parse_properties(event['OldResourceProperties'])
            print("Inside update and old_params is {}".format(old_params))
            loop_child_stacks(cf_client=cf_client, cf_params=cf_params, action="update", old_params=old_params)
        else:
            loop_child_stacks(cf_client=cf_client, cf_params=cf_params, action="create")
        print("Completed")
    except Exception:
        logging.error('Unhandled exception', exc_info=True)
        status = cfnresponse.FAILED
    finally:
        cfnresponse.send(event, context, status, {}, None)
