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

"""Python module for interacting with ETSI GS NFV-SOL007 compliant packages.

This module provides a SOL007Package class for validating and interacting with
ETSI SOL007 packages. A valid SOL007 package may have its files arranged according
to one of the following two structures:

SOL007 with metadata directory    SOL007 without metadata directory

native_charm_vnf/                 native_charm_vnf/
├── TOSCA-Metadata                ├── native_charm_nsd.mf
│   └── TOSCA.meta                ├── native_charm_nsd.yaml
├── manifest.mf                   ├── ChangeLog.txt
├── Definitions                   ├── Licenses
│   └── native_charm_nsd.yaml     │   └── license.lic
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


class SOL007PackageException(Exception):
    pass


class SOL007Package(SOLPackage):
    _MANIFEST_NSD_INVARIANT_ID = "nsd_invariant_id"
    _MANIFEST_NSD_NAME = "nsd_name"
    _MANIFEST_NSD_DESIGNER = "nsd_designer"
    _MANIFEST_NSD_FILE_STRUCTURE_VERSION = "nsd_file_structure_version"
    _MANIFEST_NSD_RELEASE_DATE_TIME = "nsd_release_date_time"
    _MANIFEST_NSD_COMPATIBLE_SPECIFICATION_VERSIONS = (
        "compatible_specification_versions"
    )

    _MANIFEST_ALL_FIELDS = [
        _MANIFEST_NSD_INVARIANT_ID,
        _MANIFEST_NSD_NAME,
        _MANIFEST_NSD_DESIGNER,
        _MANIFEST_NSD_FILE_STRUCTURE_VERSION,
        _MANIFEST_NSD_RELEASE_DATE_TIME,
        _MANIFEST_NSD_COMPATIBLE_SPECIFICATION_VERSIONS,
    ]

    def __init__(self, package_path=""):
        super().__init__(package_path)

    def generate_manifest_data_from_descriptor(self):
        descriptor_path = os.path.join(
            self._package_path, self.get_descriptor_location()
        )
        with open(descriptor_path, "r") as descriptor:
            try:
                nsd_data = yaml.safe_load(descriptor)["nsd"]
            except yaml.YAMLError as e:
                print("Error reading descriptor {}: {}".format(descriptor_path, e))
                return

            self._manifest_metadata = {}
            self._manifest_metadata[self._MANIFEST_NSD_INVARIANT_ID] = nsd_data.get(
                "id", "default-id"
            )
            self._manifest_metadata[self._MANIFEST_NSD_NAME] = nsd_data.get(
                "name", "default-name"
            )
            self._manifest_metadata[self._MANIFEST_NSD_DESIGNER] = nsd_data.get(
                "designer", "OSM"
            )
            self._manifest_metadata[self._MANIFEST_NSD_FILE_STRUCTURE_VERSION] = (
                nsd_data.get("version", "1.0")
            )
            self._manifest_metadata[self._MANIFEST_NSD_RELEASE_DATE_TIME] = (
                datetime.datetime.now().astimezone().isoformat()
            )
            self._manifest_metadata[
                self._MANIFEST_NSD_COMPATIBLE_SPECIFICATION_VERSIONS
            ] = "2.7.1"
