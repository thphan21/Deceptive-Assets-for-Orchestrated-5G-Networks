# Copyright 2019 Telefonica
#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
OSM API handling for the '--wait' option
"""

from osmclient.common.exceptions import ClientException, NotFound
import json
from time import sleep, time
from sys import stderr

# Declare a constant for each module, to allow customizing each timeout in the future
TIMEOUT_GENERIC_OPERATION = 600
TIMEOUT_NSI_OPERATION = TIMEOUT_GENERIC_OPERATION
TIMEOUT_SDNC_OPERATION = TIMEOUT_GENERIC_OPERATION
TIMEOUT_VIM_OPERATION = TIMEOUT_GENERIC_OPERATION
TIMEOUT_K8S_OPERATION = TIMEOUT_GENERIC_OPERATION
TIMEOUT_WIM_OPERATION = TIMEOUT_GENERIC_OPERATION
TIMEOUT_NS_OPERATION = 3600
POLLING_TIME_INTERVAL = 5
MAX_DELETE_ATTEMPTS = 3


def _show_detailed_status(old_detailed_status, new_detailed_status):
    if new_detailed_status is not None and new_detailed_status != old_detailed_status:
        stderr.write("detailed-status: {}\n".format(new_detailed_status))
        return new_detailed_status
    else:
        return old_detailed_status


def _get_finished_states(entity):
    """
    Member name is either:
    operationState' (NS, NSI)
    '_admin.'operationalState' (VIM, WIM, SDN)
    For NS and NSI, 'operationState' may be one of:
    PROCESSING, COMPLETED,PARTIALLY_COMPLETED, FAILED_TEMP,FAILED,ROLLING_BACK,ROLLED_BACK
    For VIM, WIM, SDN: '_admin.operationalState' may be one of:
    ENABLED, DISABLED, ERROR, PROCESSING

    :param entity: can be NS, NSI, or other
    :return: two tuples with status completed strings, status failed string
    """
    if entity == "NS" or entity == "NSI":
        return ("COMPLETED", "PARTIALLY_COMPLETED"), ("FAILED_TEMP", "FAILED")
    elif entity == "OPCANCEL":
        return ("FAILED_TEMP"), ("COMPLETED",)
    else:
        return ("ENABLED",), ("ERROR",)


def _get_operational_state(resp, entity):
    """
    The member name is either:
    'operationState' (NS)
    'operational-status' (NSI)
    '_admin.'operationalState' (other)
    :param resp: descriptor of the get response
    :param entity: can be NS, NSI, or other
    :return: status of the operation
    """
    if entity in ["NS", "NSI", "OPCANCEL"]:
        return resp.get("operationState")
    else:
        return resp.get("_admin", {}).get("operationalState")


def _op_has_finished(resp, entity):
    """
    Indicates if operation has finished ok or is processing
    :param resp: descriptor of the get response
    :param entity: can be NS, NSI, or other
    :return:
        True on success (operation has finished)
        False on pending (operation has not finished)
        raise Exception if unexpected response, or ended with error
    """
    finished_states_ok, finished_states_error = _get_finished_states(entity)
    if resp:
        op_state = _get_operational_state(resp, entity)
        if op_state:
            if op_state in finished_states_ok:
                return True
            elif op_state in finished_states_error:
                raise ClientException(
                    "Operation failed with status '{}'".format(op_state)
                )
            return False
    raise ClientException("Unexpected response from server: {} ".format(resp))


def _get_detailed_status(resp, entity):
    """
    For VIM, WIM, SDN, 'detailed-status' is either:
    - a leaf node to '_admin' (operations NOT supported)
    - a leaf node of the Nth element in the list '_admin.operations[]' (operations supported by LCM and NBI)
    :param resp: content of the get response
    :param entity: can be NS, NSI, or other
    :return:
    """
    if entity in ("NS", "NSI", "OPCANCEL"):
        # For NS and NSI, 'detailed-status' is a JSON "root" member:
        return resp.get("detailed-status")
    else:
        ops = resp.get("_admin", {}).get("operations")
        current_op = resp.get("_admin", {}).get("current_operation")
        if ops and current_op is not None:
            # Operations are supported, verify operation index
            if isinstance(ops, dict) and current_op in ops:
                return ops[current_op].get("detailed-status")
            elif (
                isinstance(ops, list)
                and isinstance(current_op, int)
                or current_op.isdigit()
            ):
                current_op = int(current_op)
                if (
                    current_op >= 0
                    and current_op < len(ops)
                    and ops[current_op]
                    and ops[current_op]["detailed-status"]
                ):
                    return ops[current_op]["detailed-status"]
            # operation index is either non-numeric or out-of-range
            return "Unexpected error when getting detailed-status!"
        else:
            # Operations are NOT supported
            return resp.get("_admin", {}).get("detailed-status")


def wait_for_status(
    entity_label, entity_id, timeout, apiUrlStatus, http_cmd, deleteFlag=False
):
    """
    Wait until operation ends, making polling every 5s. Prints detailed status when it changes
    :param entity_label: String describing the entities using '--wait': 'NS', 'NSI', 'SDNC', 'VIM', 'WIM'
    :param entity_id: The ID for an existing entity, the operation ID for an entity to create.
    :param timeout: Timeout in seconds
    :param apiUrlStatus: The endpoint to get the Response including 'detailed-status'
    :param http_cmd: callback to HTTP command. (Normally the get method)
    :param deleteFlag: If this is a delete operation
    :return: None, exception if operation fails or timeout
    """

    # Loop here until the operation finishes, or a timeout occurs.
    time_to_finish = time() + timeout
    detailed_status = None
    retries = 0
    max_retries = 1
    while True:
        try:
            http_code, resp_unicode = http_cmd("{}/{}".format(apiUrlStatus, entity_id))
            retries = 0
        except NotFound:
            if deleteFlag:
                _show_detailed_status(detailed_status, "Deleted")
                return
            raise
        except ClientException:
            if retries >= max_retries or time() < time_to_finish:
                raise
            retries += 1
            sleep(POLLING_TIME_INTERVAL)
            continue

        resp = ""
        if resp_unicode:
            resp = json.loads(resp_unicode)

        new_detailed_status = _get_detailed_status(resp, entity_label)
        # print('DETAILED-STATUS: {}'.format(new_detailed_status))
        if not new_detailed_status:
            new_detailed_status = "In progress"
        detailed_status = _show_detailed_status(detailed_status, new_detailed_status)

        # Get operation status
        if _op_has_finished(resp, entity_label):
            return

        if time() >= time_to_finish:
            # There was a timeout, so raise an exception
            raise ClientException("operation timeout after {} seconds".format(timeout))
        sleep(POLLING_TIME_INTERVAL)
