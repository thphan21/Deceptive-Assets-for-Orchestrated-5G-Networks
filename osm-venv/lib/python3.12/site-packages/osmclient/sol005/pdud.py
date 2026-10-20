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
OSM pdud API handling
"""

from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
from osmclient.common import utils
import json
import logging


class Pdu(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._apiName = "/pdu"
        self._apiVersion = "/v1"
        self._apiResource = "/pdu_descriptors"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def _get_vim_account(self, vim_account):
        vim = self._client.vim.get(vim_account)
        if vim is None:
            raise NotFound("cannot find vim account '{}'".format(vim_account))
        return vim

    def list(self, filter=None):
        self._logger.debug("")
        self._client.get_token()
        filter_string = ""
        if filter:
            filter_string = "?{}".format(filter)
        _, resp = self._http.get2_cmd("{}{}".format(self._apiBase, filter_string))
        if resp:
            return json.loads(resp)
        return list()

    def get(self, name):
        self._logger.debug("")
        self._client.get_token()
        if utils.validate_uuid4(name):
            for pdud in self.list():
                if name == pdud["_id"]:
                    return pdud
        else:
            for pdud in self.list():
                if "name" in pdud and name == pdud["name"]:
                    return pdud
        raise NotFound("pdud {} not found".format(name))

    def get_individual(self, name):
        self._logger.debug("")
        pdud = self.get(name)
        # It is redundant, since the previous one already gets the whole pdudInfo
        # The only difference is that a different primitive is exercised
        try:
            _, resp = self._http.get2_cmd("{}/{}".format(self._apiBase, pdud["_id"]))
        except NotFound:
            raise NotFound("pdu '{}' not found".format(name))
        # print(yaml.safe_dump(resp))
        if resp:
            return json.loads(resp)
        raise NotFound("pdu '{}' not found".format(name))

    def delete(self, name, force=False):
        self._logger.debug("")
        pdud = self.get(name)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, pdud["_id"], querystring)
        )
        # print('HTTP CODE: {}'.format(http_code))
        # print('RESP: {}'.format(resp))
        if http_code == 202:
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
            raise ClientException("failed to delete pdu {} - {}".format(name, msg))

    def create(self, pdu, update_endpoint=None):
        self._logger.debug("")

        if pdu["vim_accounts"]:
            vim_account_list = []
            for vim_account in pdu["vim_accounts"]:
                vim = self._get_vim_account(vim_account)
                vim_account_list.append(vim["_id"])
            pdu["vim_accounts"] = vim_account_list

        self._client.get_token()
        headers = self._client._headers
        headers["Content-Type"] = "application/yaml"
        self._http.set_http_header(headers)
        if update_endpoint:
            http_code, resp = self._http.patch_cmd(
                endpoint=update_endpoint, postfields_dict=pdu
            )
        else:
            endpoint = self._apiBase
            # endpoint = '{}{}'.format(self._apiBase,ow_string)
            http_code, resp = self._http.post_cmd(
                endpoint=endpoint, postfields_dict=pdu
            )
        if http_code in (200, 201, 202):
            if resp:
                resp = json.loads(resp)
            if not resp or "id" not in resp:
                raise ClientException(
                    "unexpected response from server: {}".format(resp)
                )
            print(resp["id"])
        elif http_code == 204:
            print("Updated")

    def update(self, name, pdu):
        self._logger.debug("")
        pdud = self.get(name)
        endpoint = "{}/{}".format(self._apiBase, pdud["_id"])
        self.create(pdu=pdu, update_endpoint=endpoint)
