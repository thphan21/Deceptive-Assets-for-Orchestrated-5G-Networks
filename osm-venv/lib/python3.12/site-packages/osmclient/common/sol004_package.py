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

"""Python module for interacting with ETSI GS NFV-SOL004 compliant packages.

This module provides a SOL004Package class for validating and interacting with
ETSI SOL004 packages. A valid SOL004 package may have its files arranged according
to one of the following two structures:

SOL004 with metadata directory    SOL004 without metadata directory

native_charm_vnf/                 native_charm_vnf/
├── TOSCA-Metadata                ├── native_charm_vnfd.mf
│   └── TOSCA.meta                ├── native_charm_vnfd.yaml
├── manifest.mf                   ├── ChangeLog.txt
├── Definitions                   ├── Licenses
│   └── native_charm_vnfd.yaml    │   └── license.lic
├── Files                         ├── Files
│   ├── icons                     │   └── icons
│   │   └── osm.png               │       └── osm.png
│   ├── Licenses                  └── Scripts
│   │   └── license.lic               ├── cloud_init
│   └── changelog.txt                 │   └── cloud-config.txt
└── Scripts                           └── charms
    ├── cloud_init                        └── simple
    │   └── cloud-config.txt                  ├── config.yaml
    └── charms                                ├── hooks
        └── simple                            │   ├── install
            ├── config.yaml                  ...
            ├── hooks                         │
            │   ├── install                   └── src
           ...                                    └── charm.py
            └── src
                └── charm.py
"""

import yaml
import datetime
import os
from .sol_package import SOLPackage


class SOL004PackageException(Exception):
    pass


class SOL004Package(SOLPackage):
    _MANIFEST_VNFD_ID = "vnfd_id"
    _MANIFEST_VNFD_PRODUCT_NAME = "vnfd_product_name"
    _MANIFEST_VNFD_PROVIDER_ID = "vnfd_provider_id"
    _MANIFEST_VNFD_SOFTWARE_VERSION = "vnfd_software_version"
    _MANIFEST_VNFD_PACKAGE_VERSION = "vnfd_package_version"
    _MANIFEST_VNFD_RELEASE_DATE_TIME = "vnfd_release_date_time"
    _MANIFEST_VNFD_COMPATIBLE_SPECIFICATION_VERSIONS = (
        "compatible_specification_versions"
    )
    _MANIFEST_VNFM_INFO = "vnfm_info"

    _MANIFEST_ALL_FIELDS = [
        _MANIFEST_VNFD_ID,
        _MANIFEST_VNFD_PRODUCT_NAME,
        _MANIFEST_VNFD_PROVIDER_ID,
        _MANIFEST_VNFD_SOFTWARE_VERSION,
        _MANIFEST_VNFD_PACKAGE_VERSION,
        _MANIFEST_VNFD_RELEASE_DATE_TIME,
        _MANIFEST_VNFD_COMPATIBLE_SPECIFICATION_VERSIONS,
        _MANIFEST_VNFM_INFO,
    ]

    def __init__(self, package_path=""):
        super().__init__(package_path)

    def generate_manifest_data_from_descriptor(self):
        descriptor_path = os.path.join(
            self._package_path, self.get_descriptor_location()
        )
        with open(descriptor_path, "r") as descriptor:
            try:
                vnfd_data = yaml.safe_load(descriptor)["vnfd"]
            except yaml.YAMLError as e:
                print("Error reading descriptor {}: {}".format(descriptor_path, e))
                return

            self._manifest_metadata = {}
            self._manifest_metadata[self._MANIFEST_VNFD_ID] = vnfd_data.get(
                "id", "default-id"
            )
            self._manifest_metadata[self._MANIFEST_VNFD_PRODUCT_NAME] = vnfd_data.get(
                "product-name", "default-product-name"
            )
            self._manifest_metadata[self._MANIFEST_VNFD_PROVIDER_ID] = vnfd_data.get(
                "provider", "OSM"
            )
            self._manifest_metadata[self._MANIFEST_VNFD_SOFTWARE_VERSION] = (
                vnfd_data.get("version", "1.0")
            )
            self._manifest_metadata[self._MANIFEST_VNFD_PACKAGE_VERSION] = "1.0.0"
            self._manifest_metadata[self._MANIFEST_VNFD_RELEASE_DATE_TIME] = (
                datetime.datetime.now().astimezone().isoformat()
            )
            self._manifest_metadata[
                self._MANIFEST_VNFD_COMPATIBLE_SPECIFICATION_VERSIONS
            ] = "2.7.1"
            self._manifest_metadata[self._MANIFEST_VNFM_INFO] = "OSM"
