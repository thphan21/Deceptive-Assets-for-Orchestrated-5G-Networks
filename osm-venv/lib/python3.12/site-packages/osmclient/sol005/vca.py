# Copyright 2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.

"""
OSM K8s cluster API handling
"""

from osmclient.common import utils
from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
import json
import logging


class VCA(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._apiName = "/admin"
        self._apiVersion = "/v1"
        self._apiResource = "/vca"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def create(self, name, vca):
        self._logger.debug("")
        self._client.get_token()
        http_code, resp = self._http.post_cmd(
            endpoint=self._apiBase, postfields_dict=vca
        )
        resp = json.loads(resp) if resp else {}
        if "id" not in resp:
            raise ClientException("unexpected response from server - {}".format(resp))
        print(resp["id"])

    def update(self, name, vca):
        self._logger.debug("")
        self._client.get_token()
        vca_id = self.get(name)["_id"]
        self._http.patch_cmd(
            endpoint="{}/{}".format(self._apiBase, vca_id),
            postfields_dict=vca,
        )

    def get_id(self, name):
        self._logger.debug("")
        """Returns a VCA id from a VCA name"""
        for vca in self.list():
            if name == vca["name"]:
                return vca["_id"]
        raise NotFound("VCA {} not found".format(name))

    def delete(self, name, force=False):
        self._logger.debug("")
        self._client.get_token()
        vca_id = name
        if not utils.validate_uuid4(name):
            vca_id = self.get_id(name)
        querystring = "?FORCE=True" if force else ""
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, vca_id, querystring)
        )
        if http_code == 202:
            print("Deletion in progress")
        elif http_code == 204:
            print("Deleted")
        else:
            msg = resp or ""
            raise ClientException("failed to delete VCA {} - {}".format(name, msg))

    def list(self, cmd_filter=None):
        """Returns a list of K8s clusters"""
        self._logger.debug("")
        self._client.get_token()
        filter_string = ""
        if cmd_filter:
            filter_string = "?{}".format(cmd_filter)
        _, resp = self._http.get2_cmd("{}{}".format(self._apiBase, filter_string))
        if resp:
            return json.loads(resp)
        return list()

    def get(self, name):
        """Returns a VCA based on name or id"""
        self._logger.debug("")
        self._client.get_token()
        vca_id = name
        if not utils.validate_uuid4(name):
            vca_id = self.get_id(name)
        try:
            _, resp = self._http.get2_cmd("{}/{}".format(self._apiBase, vca_id))
            resp = json.loads(resp) if resp else {}
            if "_id" not in resp:
                raise ClientException("failed to get VCA info: {}".format(resp))
            return resp
        except NotFound:
            raise NotFound("VCA {} not found".format(name))
