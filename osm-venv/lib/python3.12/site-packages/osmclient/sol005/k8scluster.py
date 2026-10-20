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
#

"""
OSM K8s cluster API handling
"""

from osmclient.common import utils
from osmclient.common import wait as WaitForStatus
from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
import json
import logging


class K8scluster(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient.k8scluster")
        self._apiName = "/admin"
        self._apiVersion = "/v1"
        self._apiResource = "/k8sclusters"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def _get_vim_account(self, vim_account):
        vim = self._client.vim.get(vim_account)
        if vim is None:
            raise NotFound("cannot find vim account '{}'".format(vim_account))
        return vim

    # K8S '--wait' option
    def _wait(self, id, wait_time, deleteFlag=False):
        self._logger.debug("")
        self._client.get_token()
        # Endpoint to get operation status
        apiUrlStatus = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )
        # Wait for status for VIM instance creation/deletion
        if isinstance(wait_time, bool):
            wait_time = WaitForStatus.TIMEOUT_VIM_OPERATION
        WaitForStatus.wait_for_status(
            "K8S",
            str(id),
            wait_time,
            apiUrlStatus,
            self._http.get2_cmd,
            deleteFlag=deleteFlag,
        )

    def add(self, name, k8s_cluster, wait=False):
        self._client.get_token()
        vim_account = self._get_vim_account(k8s_cluster["vim_account"])
        k8s_cluster["vim_account"] = vim_account["_id"]
        if "vca" in vim_account:
            k8s_cluster["vca_id"] = vim_account["vca"]
        http_code, resp = self._http.post_cmd(
            endpoint=self._apiBase, postfields_dict=k8s_cluster
        )

        self._logger.debug("HTTP CODE: {}".format(http_code))
        self._logger.debug("RESP: {}".format(resp))

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
        #    raise ClientException("failed to add K8s cluster {} - {}".format(name, msg))

    def update(self, name, k8s_cluster, wait=False):
        self._client.get_token()
        cluster = self.get(name)
        if "vim_account" in k8s_cluster:
            vim_account = self._get_vim_account(k8s_cluster["vim_account"])
            k8s_cluster["vim_account"] = vim_account["_id"]
            if "vca" in vim_account:
                k8s_cluster["vca_id"] = vim_account["vca"]
        http_code, resp = self._http.patch_cmd(
            endpoint="{}/{}".format(self._apiBase, cluster["_id"]),
            postfields_dict=k8s_cluster,
        )

        if wait:
            wait_id = cluster["_id"]
            self._wait(wait_id, wait)

        self._logger.debug("HTTP CODE: {}".format(http_code))
        self._logger.debug("RESP: {}".format(resp))

        if http_code in (200, 201, 202, 204):
            print("Updated")
        else:
            msg = ""
            if resp:
                try:
                    msg = json.loads(resp)
                except ValueError:
                    msg = resp
            raise ClientException(
                "failed to update K8s cluster {} - {}".format(name, msg)
            )

    def get_id(self, name):
        """Returns a K8s cluster id from a K8s cluster name"""
        for cluster in self.list():
            if name == cluster["name"]:
                return cluster["_id"]
        raise NotFound("K8s cluster {} not found".format(name))

    def remove(self, name, force=False, wait=False):
        self._client.get_token()
        cluster_id = name
        if not utils.validate_uuid4(name):
            cluster_id = self.get_id(name)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, cluster_id, querystring)
        )

        self._logger.debug("HTTP CODE: {}".format(http_code))
        self._logger.debug("RESP: {}".format(resp))

        if http_code == 202:
            if wait:
                wait_id = cluster_id

                if resp:
                    resp = json.loads(resp)
                    wait_id = resp.get("id")

                self._wait(wait_id, wait, deleteFlag=True)
            else:
                print("Deletion in progress")
        elif http_code == 204:
            print("Deleted")
        else:
            msg = resp or ""
            #     if resp:
            #         try:
            #             msg = json.loads(resp)
            #         except ValueError:
            #             msg = resp
            raise ClientException(
                "failed to delete K8s cluster {} - {}".format(name, msg)
            )

    def list(self, filter=None):
        """Returns a list of K8s clusters"""
        self._client.get_token()
        filter_string = ""
        if filter:
            filter_string = "?{}".format(filter)
        _, resp = self._http.get2_cmd("{}{}".format(self._apiBase, filter_string))
        if resp:
            return json.loads(resp)
        return list()

    def get(self, name):
        """Returns a K8s cluster based on name or id"""
        self._client.get_token()
        cluster_id = name
        if not utils.validate_uuid4(name):
            cluster_id = self.get_id(name)
        try:
            _, resp = self._http.get2_cmd("{}/{}".format(self._apiBase, cluster_id))
            if resp:
                resp = json.loads(resp)
            if not resp or "_id" not in resp:
                raise ClientException("failed to get K8s cluster info: {}".format(resp))
            return resp
        except NotFound:
            raise NotFound("K8s cluster {} not found".format(name))
