#######################################################################################
# Copyright ETSI Contributors and Others.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#######################################################################################

"""
OSM Cluster API handling
"""

from osmclient.sol005.osm_api_object import GenericOSMAPIObject
from osmclient.common.exceptions import ClientException, NotFound
import json
import yaml


class Cluster(GenericOSMAPIObject):
    def __init__(self, http=None, client=None):
        super().__init__(http, client)
        self._apiName = "/k8scluster"
        self._apiVersion = "/v1"
        self._apiResource = "/clusters"
        self._logObjectName = "cluster"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def update_profiles(self, cluster_id, profile_type, update_dict):
        """Updates the profiles in a cluster"""
        self._logger.debug("")
        self._client.get_token()
        profile_endpoint = {
            "infra-controller-profile": "infra_controller_profiles",
            "infra-config-profile": "infra_config_profiles",
            "app-profile": "app_profiles",
            "resource-profile": "resource_profiles",
        }
        http_code, resp = self._http.patch_cmd(
            endpoint="{}/{}/{}".format(
                self._apiBase, cluster_id, profile_endpoint[profile_type]
            ),
            postfields_dict=update_dict,
            skip_query_admin=True,
        )
        if http_code in (200, 201, 202):
            if resp:
                resp = json.loads(resp)
            if not resp or "id" not in resp:
                raise ClientException(f"unexpected response from server - {resp}")
            print(resp["id"])
        elif http_code == 204:
            print("Updated")

    def get_credentials(self, name):
        """
        Gets the kubeconfig file of a Kubernetes cluster
        """
        self._logger.debug("")
        item = self.get(name)
        resp = ""
        try:
            _, resp = self._http.get2_cmd(f"{self._apiBase}/{item['_id']}/get_creds")
            if resp:
                resp = json.loads(resp)
                op_id = resp["op_id"]
                # Wait loop to check if the operation completed
                result = self.wait_for_operation_status(item["_id"], 10, op_id)
                if result:
                    item = self.get(name)
                    print(
                        yaml.safe_dump(
                            item["credentials"], indent=2, default_flow_style=False
                        )
                    )
                else:
                    print("No credentials were found")
        except NotFound:
            raise NotFound(f"{self._logObjectName} '{name}' not found")
        except Exception as e:
            raise ClientException(f"{e}: unexpected response from server - {resp}")

    def register(self, name, cluster):
        """
        Registers a K8s cluster
        """
        self._logger.debug("")
        endpoint = f"{self._apiBase}/register"
        self.create(name, cluster, None, endpoint=endpoint)

    def deregister(self, name, force):
        """
        Deregisters a K8s cluster
        """
        self._logger.debug("")
        item = self.get(name)
        endpoint = f"{self._apiBase}/{item['_id']}/deregister"
        self.delete(name, force, endpoint=endpoint)

    def upgrade(self, name, cluster_changes):
        """
        Upgrades a K8s cluster
        """
        self._logger.debug("")
        item = self.get(name)
        endpoint_suffix = f"{item['_id']}/upgrade"
        self.generic_operation(cluster_changes, endpoint_suffix=endpoint_suffix)

    def scale(self, name, cluster_changes):
        """
        Scales a K8s cluster
        """
        self._logger.debug("")
        item = self.get(name)
        endpoint_suffix = f"{item['_id']}/scale"
        self.generic_operation(cluster_changes, endpoint_suffix=endpoint_suffix)

    def fullupdate(self, name, cluster_changes):
        """
        Updates a K8s cluster (version, node size or node count)
        """
        self._logger.debug("")
        item = self.get(name)
        endpoint_suffix = f"{item['_id']}/update"
        self.generic_operation(cluster_changes, endpoint_suffix=endpoint_suffix)

    def enhanced_list(self, filter=None):
        """List all clusters with additional resolution (VIM)"""
        self._logger.debug("")
        cluster_list = self.list(filter)
        vim_list = self._client.vim.list()
        self._logger.debug(f"VIM list: {vim_list}")
        if cluster_list and not vim_list:
            self._logger.warning(
                "Could not complete cluster info with VIM account info"
            )
        for item in cluster_list:
            vim_id = item["vim_account"]
            vim_name, vim_type = next(
                (
                    (vim_item["name"], vim_item["vim_type"])
                    for vim_item in vim_list
                    if vim_item["_id"] == vim_id or vim_item["name"] == vim_id
                ),
                (None, None),
            )
            item["vim_account"] = f"{vim_name} ({vim_type})"
        return cluster_list
