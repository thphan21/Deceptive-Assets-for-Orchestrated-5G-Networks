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
OSM nsd API handling
"""

from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
from osmclient.common import utils
import json
import magic
from os.path import basename
import logging
import os.path


class Nsd(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._apiName = "/nsd"
        self._apiVersion = "/v1"
        self._apiResource = "/ns_descriptors"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

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
            for nsd in self.list():
                if name == nsd["_id"]:
                    return nsd
        else:
            for nsd in self.list():
                if "name" in nsd and name == nsd["name"]:
                    return nsd
        raise NotFound("nsd {} not found".format(name))

    def get_individual(self, name):
        self._logger.debug("")
        # Call to get_token not required, because will be implicitly called by get.
        try:
            nsd = self.get(name)
            # It is redundant, since the previous one already gets the whole nsdinfo
            # The only difference is that a different primitive is exercised
            _, resp = self._http.get2_cmd("{}/{}".format(self._apiBase, nsd["_id"]))
            if resp:
                return json.loads(resp)
        except NotFound:
            raise NotFound("nsd '{}' not found".format(name))
        raise NotFound("nsd '{}' not found".format(name))

    def get_thing(self, name, thing, filename):
        self._logger.debug("")
        # Call to get_token not required, because will be implicitly called by get.
        nsd = self.get(name)
        headers = self._client._headers
        headers["Accept"] = "application/binary"
        http_code, resp = self._http.get2_cmd(
            "{}/{}/{}".format(self._apiBase, nsd["_id"], thing)
        )

        if resp:
            return json.loads(resp)
        else:
            msg = resp or ""
            raise ClientException(
                "failed to get {} from {} - {}".format(thing, name, msg)
            )

    def get_descriptor(self, name, filename):
        self._logger.debug("")
        self.get_thing(name, "nsd", filename)

    def get_package(self, name, filename):
        self._logger.debug("")
        self.get_thing(name, "package_content", filename)

    def get_artifact(self, name, artifact, filename):
        self._logger.debug("")
        self.get_thing(name, "artifacts/{}".format(artifact), filename)

    def delete(self, name, force=False):
        self._logger.debug("")
        nsd = self.get(name)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, nsd["_id"], querystring)
        )

        if http_code == 202:
            print("Deletion in progress")
        elif http_code == 204:
            print("Deleted")
        else:
            msg = resp or ""
            raise ClientException("failed to delete nsd {} - {}".format(name, msg))

    def create(
        self, filename, overwrite=None, update_endpoint=None, skip_charm_build=False
    ):
        self._logger.debug("")
        if os.path.isdir(filename):
            filename = filename.rstrip("/")
            filename = self._client.package_tool.build(
                filename, skip_validation=False, skip_charm_build=skip_charm_build
            )
            self.create(filename, overwrite=overwrite, update_endpoint=update_endpoint)
        else:
            self._client.get_token()
            mime_type = magic.from_file(filename, mime=True)
            if mime_type is None:
                raise ClientException(
                    "Unexpected MIME type for file {}: MIME type {}".format(
                        filename, mime_type
                    )
                )
            headers = self._client._headers
            headers["Content-Filename"] = basename(filename)
            if mime_type in ["application/yaml", "text/plain", "application/json"]:
                headers["Content-Type"] = "text/plain"
            elif mime_type in ["application/gzip", "application/x-gzip"]:
                headers["Content-Type"] = "application/gzip"
            elif mime_type in ["application/zip"]:
                headers["Content-Type"] = "application/zip"
            else:
                raise ClientException(
                    "Unexpected MIME type for file {}: MIME type {}".format(
                        filename, mime_type
                    )
                )
            headers["Content-File-MD5"] = utils.md5(filename)
            self._http.set_http_header(headers)
            if update_endpoint:
                http_code, resp = self._http.put_cmd(
                    endpoint=update_endpoint, filename=filename
                )
            else:
                ow_string = ""
                if overwrite:
                    ow_string = "?{}".format(overwrite)
                self._apiResource = "/ns_descriptors_content"
                self._apiBase = "{}{}{}".format(
                    self._apiName, self._apiVersion, self._apiResource
                )
                endpoint = "{}{}".format(self._apiBase, ow_string)
                http_code, resp = self._http.post_cmd(
                    endpoint=endpoint, filename=filename
                )

            if http_code in (200, 201, 202):
                if resp:
                    resp = json.loads(resp)
                if not resp or "id" not in resp:
                    raise ClientException(
                        "unexpected response from server - {}".format(resp)
                    )
                print(resp["id"])
            elif http_code == 204:
                print("Updated")

    def update(self, name, filename):
        self._logger.debug("")
        nsd = self.get(name)
        endpoint = "{}/{}/nsd_content".format(self._apiBase, nsd["_id"])
        self.create(filename=filename, update_endpoint=endpoint)
