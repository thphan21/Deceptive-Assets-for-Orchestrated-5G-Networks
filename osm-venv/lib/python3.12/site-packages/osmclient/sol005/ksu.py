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
OSM KSU API handling
"""

from osmclient.sol005.osm_api_object import GenericOSMAPIObject


class KSU(GenericOSMAPIObject):
    def __init__(self, http=None, client=None):
        super().__init__(http, client)
        self._apiName = "/ksu"
        self._apiVersion = "/v1"
        self._apiResource = "/ksus"
        self._logObjectName = "ksu"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )
