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
OSM Kubernetes Application (OKA) API handling
"""

from osmclient.sol005.osm_api_object import GenericOSMAPIObject
from osmclient.common.exceptions import ClientException
import os
from jinja2 import Environment, PackageLoader, select_autoescape


class OKA(GenericOSMAPIObject):
    def __init__(self, http=None, client=None):
        super().__init__(http, client)
        self._apiName = "/oka"
        self._apiVersion = "/v1"
        self._apiResource = "/oka_packages"
        self._logObjectName = "oka_package"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def generate(self, name, base_directory, profile_type, oka_params):
        """Generate a folder structure of an OKA with manifests and templates"""
        self._logger.debug("")
        # if oka_params["manifest_dir"] and oka_params["helm-repo-name"]:
        #     raise ClientException("Options manifest_dir and helm-xxx are mutually exclusive")
        if not os.path.exists(base_directory):
            raise ClientException(f"The specified {base_directory} does not exist")
        try:
            self._logger.debug(f"oka_params: {oka_params}")
            self._logger.debug(f"base_dir: {base_directory}")
            oka_folder = os.path.join(base_directory, name)
            self._logger.debug(f"destination_folder: {oka_folder}")
            manifests_folder = os.path.join(oka_folder, "manifests")
            templates_folder = os.path.join(oka_folder, "templates")
            os.makedirs(manifests_folder)
            os.makedirs(templates_folder)

            # Load the Jinja template from file
            # loader = FileSystemLoader("osm_lcm/odu_libs/templates")
            loader = PackageLoader("osmclient", "templates/oka")
            self._logger.debug(f"Loader: {loader}")
            env = Environment(loader=loader, autoescape=select_autoescape())
            self._logger.debug(f"Env: {env}")

            template_list = env.list_templates()
            self._logger.debug(f"Template list: {template_list}")

            # Get required information from OKA to generate files
            helm_repo_name = oka_params["helm_repo_name"]
            helm_repo_url = oka_params["helm_repo_url"]
            if helm_repo_url.startswith("oci://"):
                oka_params["helm_repo_type"] = "oci"
            helm_release = name
            oka_params["helm_release"] = helm_release
            namespace = oka_params["namespace"]
            oka_params["kustomization_name"] = name
            profile_path_mapping = {
                "infra-controller-profile": "infra-controllers",
                "infra-config-profile": "infra-configs",
                "app-profile": "apps",
                "resource-profile": "cloud-resources",
            }
            profile_path = profile_path_mapping[profile_type]
            oka_params["manifest_folder"] = f"./{profile_path}/{name}/manifests"

            # Helm repo
            template = env.get_template("manifest-helmrepo.j2")
            output_file = os.path.join(manifests_folder, f"{helm_repo_name}-repo.yaml")
            with open(output_file, "w") as c_file:
                c_file.write(template.render(oka_params))

            # Helm release
            template = env.get_template("manifest-helmrelease.j2")
            output_file = os.path.join(manifests_folder, f"{helm_release}-hr.yaml")
            with open(output_file, "w") as c_file:
                c_file.write(template.render(oka_params))

            # Namespace
            template = env.get_template("template-namespace.j2")
            output_file = os.path.join(templates_folder, f"{namespace}-ns.yaml")
            with open(output_file, "w") as c_file:
                c_file.write(template.render(oka_params))

            # Kustomization
            template = env.get_template("template-kustomization.j2")
            output_file = os.path.join(templates_folder, f"{name}-ks.yaml")
            with open(output_file, "w") as c_file:
                c_file.write(template.render(oka_params))

            print(f"Folder created: {oka_folder}")
        except Exception as exc:
            raise ClientException(f"failure during generation of OKA folder: {exc}")
