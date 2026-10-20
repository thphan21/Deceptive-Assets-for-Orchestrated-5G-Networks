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

import osmclient.common.utils as utils
import os

SOL004_TOSCA = "SOL004_TOSCA"
SOL004 = "SOL004"
SOL007_TOSCA = "SOL007_TOSCA"
SOL007 = "SOL007"
OSM_OLD = "OSM_OLD"


def get_package_type(package_folder):
    """
    Detects the package's structure and returns the type:
    SOL004
    SOL007
    OSM_OLD
    """

    package_files = os.listdir(package_folder)
    if "Definitions" in package_files and "TOSCA-Metadata" in package_files:
        descriptors = [
            definition
            for definition in os.listdir(package_folder + "/Definitions")
            if definition.endswith(".yaml") or definition.endswith(".yml")
        ]
        if len(descriptors) < 1:
            raise Exception(
                "No descriptor found on this package, OSM was expecting at least 1"
            )
        pkg_type = utils.get_key_val_from_pkg(descriptors[0])
        if pkg_type == "nsd":
            return SOL007_TOSCA
        else:
            return SOL004_TOSCA
    else:
        manifests = [afile for afile in package_files if afile.endswith(".mf")]
        if len(manifests) < 1:
            # No manifest found, probably old OSM package structure
            return OSM_OLD
        else:
            descriptors = [
                definition
                for definition in package_files
                if definition.endswith(".yaml") or definition.endswith(".yml")
            ]
            if len(descriptors) < 1:
                raise Exception(
                    "No descriptor found on this package, OSM was expecting at least 1"
                )
            with open(os.path.join(package_folder, descriptors[0])) as descriptor:
                pkg_type = utils.get_key_val_from_descriptor(descriptor)
                if pkg_type["type"] == "nsd":
                    return SOL007
                else:
                    return SOL004
