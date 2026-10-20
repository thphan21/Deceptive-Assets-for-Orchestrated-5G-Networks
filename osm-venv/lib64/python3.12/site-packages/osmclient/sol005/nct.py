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
OSM nct API handling
"""

from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
from osmclient.common import utils
import yaml
import json
import logging


class Nct(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._apiName = "/nsd"
        self._apiVersion = "/v1"
        self._apiResource = "/ns_config_template"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def list(self, nsd=None):
        self._logger.debug("")
        self._client.get_token()
        filter_string = ""
        if nsd:
            filter_string = "?{}".format(nsd)
            _, resp = self._http.get2_cmd(
                "{}{}/ns_descriptors{}".format(
                    self._apiName, self._apiVersion, filter_string
                )
            )
            resp = json.loads(resp)
            for rep in resp:
                if nsd == rep.get("_id"):
                    resp_id = rep.get("_id")
                    return resp_id
                if nsd == rep.get("name"):
                    resp_id = rep.get("_id")
                    return resp_id
            raise NotFound("nsd {} not found".format(nsd))
        _, resp = self._http.get2_cmd("{}".format(self._apiBase))
        if resp:
            return json.loads(resp)
        return list()

    def get(self, name):
        self._logger.debug("")
        self._client.get_token()
        if utils.validate_uuid4(name):
            for nct in self.list():
                if name == nct["_id"]:
                    return nct
        else:
            for nct in self.list():
                if "name" in nct and name == nct["name"]:
                    return nct
        raise NotFound("ns config template {} not found".format(name))

    def delete(self, name, force=False):
        self._logger.debug("")
        nct = self.get(name)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, nct["_id"], querystring)
        )

        if http_code == 202:
            print("Deletion in progress")
        elif http_code == 204:
            print("Deleted")
        else:
            msg = resp or ""
            raise ClientException(
                "failed to delete ns config template {} - {}".format(name, msg)
            )

    def create(self, name, config, nsd):
        template = {}
        vim_account_id = {}
        config_param = yaml.safe_load(config)

        def get_vim_account_id(vim_account):
            self._logger.debug("")
            if vim_account_id.get(vim_account):
                return vim_account_id[vim_account]
            vim = self._client.vim.get(vim_account)
            if vim is None:
                raise NotFound("cannot find vim account '{}'".format(vim_account))
            vim_account_id[vim_account] = vim["_id"]
            return vim["_id"]

        if "vim-network-name" in config_param:
            config_param["vld"] = config_param.pop("vim-network-name")
        if "vld" in config_param:
            if not isinstance(config_param["vld"], list):
                raise ClientException(
                    "Error at --config 'vld' must be a list of dictionaries"
                )
            for vld in config_param["vld"]:
                if not isinstance(vld, dict):
                    raise ClientException(
                        "Error at --config 'vld' must be a list of dictionaries"
                    )
                if vld.get("vim-network-name"):
                    if isinstance(vld["vim-network-name"], dict):
                        vim_network_name_dict = {}
                        for vim_account, vim_net in vld["vim-network-name"].items():
                            vim_network_name_dict[get_vim_account_id(vim_account)] = (
                                vim_net
                            )
                        vld["vim-network-name"] = vim_network_name_dict
        if "vnf" in config_param:
            for vnf in config_param["vnf"]:
                if vnf.get("vim_account"):
                    vnf["vimAccountId"] = get_vim_account_id(vnf.pop("vim_account"))

        if "additionalParamsForNs" in config_param:
            if not isinstance(config_param["additionalParamsForNs"], dict):
                raise ClientException(
                    "Error at --config 'additionalParamsForNs' must be a dictionary"
                )
        if "additionalParamsForVnf" in config_param:
            if not isinstance(config_param["additionalParamsForVnf"], list):
                raise ClientException(
                    "Error at --config 'additionalParamsForVnf' must be a list"
                )
            for additional_param_vnf in config_param["additionalParamsForVnf"]:
                if not isinstance(additional_param_vnf, dict):
                    raise ClientException(
                        "Error at --config 'additionalParamsForVnf' items must be dictionaries"
                    )
                if not additional_param_vnf.get("member-vnf-index"):
                    raise ClientException(
                        "Error at --config 'additionalParamsForVnf' items must contain "
                        "'member-vnf-index'"
                    )
        template["name"] = name
        template["config"] = config_param
        template["nsdId"] = self.list(nsd)

        try:
            headers = self._client._headers
            headers["Content-Type"] = "application/json"
            self._http.set_http_header(headers)
            http_code, resp = self._http.post_cmd(
                endpoint=self._apiBase, postfields_dict=template
            )

            if resp:
                resp = json.loads(resp)
                print(resp.get("id"))
            if not resp or "id" not in resp:
                raise ClientException(
                    "unexpected response from server - {} ".format(resp)
                )
        except ClientException as exc:
            message = "failed to create ns config template: {}:\nerror:\n{}".format(
                name, str(exc)
            )
            raise ClientException(message)

    def update(self, name, newname=None, config=None):
        self._logger.debug("")
        template_edit = {}
        config_name = self.get(name)
        if newname:
            template_edit["name"] = newname
        if config:
            config_content = yaml.safe_load(config)
            template_edit["config"] = config_content
        http_code, resp = self._http.put_cmd(
            endpoint="{}/{}/template_content".format(self._apiBase, config_name["_id"]),
            postfields_dict=template_edit,
        )
        if http_code == 204:
            print("Updated")
