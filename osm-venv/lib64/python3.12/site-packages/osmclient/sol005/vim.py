# Copyright 2018 Telefonica
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
OSM vim API handling
"""

from osmclient.common import utils
from osmclient.common import wait as WaitForStatus
from osmclient.common.exceptions import ClientException
from osmclient.common.exceptions import NotFound
import yaml
import json
import logging


class Vim(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._apiName = "/admin"
        self._apiVersion = "/v1"
        self._apiResource = "/vim_accounts"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    # VIM '--wait' option
    def _wait(self, id, wait_time, deleteFlag=False):
        self._logger.debug("")
        self._client.get_token()
        # Endpoint to get operation status
        apiUrlStatus = "{}{}{}".format(self._apiName, self._apiVersion, "/vim_accounts")
        # Wait for status for VIM instance creation/deletion
        if isinstance(wait_time, bool):
            wait_time = WaitForStatus.TIMEOUT_VIM_OPERATION
        WaitForStatus.wait_for_status(
            "VIM",
            str(id),
            wait_time,
            apiUrlStatus,
            self._http.get2_cmd,
            deleteFlag=deleteFlag,
        )

    def _get_id_for_wait(self, name):
        """Returns id of name, or the id itself if given as argument"""
        self._logger.debug("")
        self._client.get_token()
        for vim in self.list():
            if name == vim["uuid"] or name == vim["name"]:
                return vim["uuid"]
        return ""

    def create(
        self,
        name,
        vim_access,
        config={},
        sdn_controller=None,
        sdn_port_mapping=None,
        wait=False,
    ):
        vca_id = None

        def get_vca_id(vca):
            vca = self._client.vca.get(vca)
            if vca is None:
                raise NotFound("cannot find vca '{}'".format(vca))
            return vca["_id"]

        self._logger.debug("")
        self._client.get_token()
        if "vca" in vim_access:
            vca_id = get_vca_id(vim_access["vca"])
        if "vim-type" not in vim_access:
            # 'openstack' not in vim_access['vim-type']):
            raise Exception("vim type not provided")
        vim_account = {}
        vim_account["name"] = name
        vim_account = self.update_vim_account_dict(vim_account, vim_access)
        if vca_id:
            vim_account["vca"] = vca_id
        vim_config = config
        if sdn_controller:
            sdnc = self._client.sdnc.get(sdn_controller)
            vim_config["sdn-controller"] = sdnc["_id"]
        if sdn_port_mapping:
            with open(sdn_port_mapping, "r") as f:
                vim_config["sdn-port-mapping"] = yaml.safe_load(f.read())
        if vim_config:
            vim_account["config"] = vim_config
            # vim_account['config'] = json.dumps(vim_config)

        http_code, resp = self._http.post_cmd(
            endpoint=self._apiBase, postfields_dict=vim_account
        )
        # print('HTTP CODE: {}'.format(http_code))
        # print('RESP: {}'.format(resp))
        # if http_code in (200, 201, 202, 204):
        if resp:
            resp = json.loads(resp)
        if not resp or "id" not in resp:
            raise ClientException("unexpected response from server - {}".format(resp))
        if wait:
            # Wait for status for VIM instance creation
            self._wait(resp.get("id"), wait)
        print(resp["id"])
        # else:
        #    msg = ""
        #    if resp:
        #        try:
        #            msg = json.loads(resp)
        #        except ValueError:
        #            msg = resp
        #    raise ClientException("failed to create vim {} - {}".format(name, msg))

    def update(
        self,
        vim_name,
        vim_account,
        config,
        sdn_controller,
        sdn_port_mapping,
        wait=False,
    ):
        self._logger.debug("")
        self._client.get_token()
        vim = self.get(vim_name)
        vim_id_for_wait = self._get_id_for_wait(vim_name)
        vim_config = {}
        if config is not None:
            if not config and (sdn_controller or sdn_port_mapping):
                # If config is empty (clearing config)
                raise ClientException(
                    "clearing config is incompatible with updating SDN info"
                )
            vim_config = config
        if sdn_controller == "":
            vim_config["sdn-controller"] = None
            vim_config["sdn-port-mapping"] = None
        else:
            if sdn_controller:
                sdnc = self._client.sdnc.get(sdn_controller)
                vim_config["sdn-controller"] = sdnc["_id"]
            if sdn_port_mapping:
                with open(sdn_port_mapping, "r") as f:
                    vim_config["sdn-port-mapping"] = yaml.safe_load(f.read())
        vim_account["config"] = vim_config
        # vim_account['config'] = json.dumps(vim_config)
        http_code, resp = self._http.patch_cmd(
            endpoint="{}/{}".format(self._apiBase, vim["_id"]),
            postfields_dict=vim_account,
        )
        # print('HTTP CODE: {}'.format(http_code))
        # print('RESP: {}'.format(resp))
        # if http_code in (200, 201, 202, 204):
        if wait:
            # In this case, 'resp' always returns None, so 'resp['id']' cannot be used.
            # Use the previously obtained id instead.
            wait_id = vim_id_for_wait
            # Wait for status for VI instance update
            self._wait(wait_id, wait)
        # else:
        #     pass
        # else:
        #    msg = ""
        #    if resp:
        #        try:
        #            msg = json.loads(resp)
        #        except ValueError:
        #            msg = resp
        #    raise ClientException("failed to update vim {} - {}".format(vim_name, msg))

    def update_vim_account_dict(self, vim_account, vim_access):
        self._logger.debug("")
        vim_account["vim_type"] = vim_access["vim-type"]
        vim_account["description"] = vim_access["description"]
        vim_account["vim_url"] = vim_access["vim-url"] or "null"
        vim_account["vim_user"] = vim_access["vim-username"] or "null"
        vim_account["vim_password"] = vim_access["vim-password"] or "null"
        vim_account["vim_tenant_name"] = vim_access["vim-tenant-name"] or "null"
        if "prometheus-config" in vim_access:
            vim_account["prometheus-config"] = vim_access["prometheus-config"]
        return vim_account

    def get_id(self, name):
        """Returns a VIM id from a VIM name"""
        self._logger.debug("")
        for vim in self.list():
            if name == vim["name"]:
                return vim["uuid"]
        raise NotFound("vim {} not found".format(name))

    def delete(self, vim_name, force=False, wait=False):
        self._logger.debug("")
        self._client.get_token()
        vim_id = vim_name
        if not utils.validate_uuid4(vim_name):
            vim_id = self.get_id(vim_name)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, vim_id, querystring)
        )
        # print('HTTP CODE: {}'.format(http_code))
        # print('RESP: {}'.format(resp))
        if http_code == 202:
            if wait:
                # When deleting an account, 'resp' may be None.
                # In such a case, the 'id' from 'resp' cannot be used, so use 'vim_id' instead
                wait_id = vim_id
                if resp:
                    resp = json.loads(resp)
                    wait_id = resp.get("id")
                # Wait for status for VIM account deletion
                self._wait(wait_id, wait, deleteFlag=True)
            else:
                print("Deletion in progress")
        elif http_code == 204:
            print("Deleted")
        else:
            msg = resp or ""
            # if resp:
            #     try:
            #         msg = json.loads(resp)
            #     except ValueError:
            #         msg = resp
            raise ClientException("failed to delete vim {} - {}".format(vim_name, msg))

    def list(self, filter=None):
        """Returns a list of VIM accounts"""
        self._logger.debug("")
        self._client.get_token()
        filter_string = ""
        if filter:
            filter_string = "?{}".format(filter)
        _, resp = self._http.get2_cmd("{}{}".format(self._apiBase, filter_string))
        if not resp:
            return list()
        vim_accounts = json.loads(resp)
        for datacenter in vim_accounts:
            datacenter["uuid"] = datacenter.get("_id")  # backward compatibility?
        return vim_accounts

    def get(self, name):
        """Returns a VIM account based on name or id"""
        self._logger.debug("")
        self._client.get_token()
        vim_id = name
        if not utils.validate_uuid4(name):
            vim_id = self.get_id(name)
        try:
            _, resp = self._http.get2_cmd("{}/{}".format(self._apiBase, vim_id))
            if resp:
                resp = json.loads(resp)
            if not resp or "_id" not in resp:
                raise ClientException("failed to get vim info: {}".format(resp))
            return resp
        except NotFound:
            raise NotFound("vim '{}' not found".format(name))
