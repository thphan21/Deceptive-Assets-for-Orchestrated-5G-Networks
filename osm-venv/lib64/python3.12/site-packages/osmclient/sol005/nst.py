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
OSM NST (Network Slice Template) API handling
"""

from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
from osmclient.common import utils
import json
import magic
import logging
import os.path

# from os import stat
# from os.path import basename


class Nst(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._apiName = "/nst"
        self._apiVersion = "/v1"
        self._apiResource = "/netslice_templates"
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
        # print(yaml.safe_dump(resp))
        if resp:
            return json.loads(resp)
        return list()

    def get(self, name):
        self._logger.debug("")
        self._client.get_token()
        if utils.validate_uuid4(name):
            for nst in self.list():
                if name == nst["_id"]:
                    return nst
        else:
            for nst in self.list():
                if "name" in nst and name == nst["name"]:
                    return nst
        raise NotFound("nst {} not found".format(name))

    def get_individual(self, name):
        self._logger.debug("")
        nst = self.get(name)
        # It is redundant, since the previous one already gets the whole nstinfo
        # The only difference is that a different primitive is exercised
        try:
            _, resp = self._http.get2_cmd("{}/{}".format(self._apiBase, nst["_id"]))
            # print(yaml.safe_dump(resp))
            if resp:
                return json.loads(resp)
        except NotFound:
            raise NotFound("nst '{}' not found".format(name))
        raise NotFound("nst '{}' not found".format(name))

    def get_thing(self, name, thing, filename):
        self._logger.debug("")
        nst = self.get(name)
        headers = self._client._headers
        headers["Accept"] = "application/binary"
        try:
            http_code, resp = self._http.get2_cmd(
                "{}/{}/{}".format(self._apiBase, nst["_id"], thing)
            )
        except NotFound:
            raise NotFound("nst '{} 'not found".format(name))
        # print('HTTP CODE: {}'.format(http_code))
        # print('RESP: {}'.format(resp))
        # if http_code in (200, 201, 202, 204):
        if resp:
            # store in a file
            return json.loads(resp)
        # else:
        #    msg = ""
        #    if resp:
        #        try:
        #            msg = json.loads(resp)
        #        except ValueError:
        #            msg = resp
        #    raise ClientException("failed to get {} from {} - {}".format(thing, name, msg))

    def get_descriptor(self, name, filename):
        self._logger.debug("")
        self.get_thing(name, "nst", filename)

    def get_package(self, name, filename):
        self._logger.debug("")
        self.get_thing(name, "nst_content", filename)

    def get_artifact(self, name, artifact, filename):
        self._logger.debug("")
        self.get_thing(name, "artifacts/{}".format(artifact), filename)

    def delete(self, name, force=False):
        self._logger.debug("")
        nst = self.get(name)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, nst["_id"], querystring)
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
            #         resp = json.loads(resp)
            #     except ValueError:
            #         msg = resp
            raise ClientException("failed to delete nst {} - {}".format(name, msg))

    def create(self, filename, overwrite=None, update_endpoint=None):
        self._logger.debug("")
        if os.path.isdir(filename):
            charm_folder = filename.rstrip("/")
            for files in os.listdir(charm_folder):
                if "nst.yaml" in files:
                    results = self._client.package_tool.validate(
                        charm_folder, recursive=False
                    )
                    for result in results:
                        if result["valid"] != "OK":
                            raise ClientException(
                                "There was an error validating the file: {} "
                                "with error: {}".format(result["path"], result["error"])
                            )
            result = self._client.package_tool.build(charm_folder)
            if "Created" in result:
                filename = "{}.tar.gz".format(charm_folder)
            else:
                raise ClientException(
                    "Failed in {}tar.gz creation".format(charm_folder)
                )
            self.create(filename, overwrite, update_endpoint)
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
            if mime_type in ["application/yaml", "text/plain"]:
                headers["Content-Type"] = "application/yaml"
            elif mime_type in ["application/gzip", "application/x-gzip"]:
                headers["Content-Type"] = "application/gzip"
                # headers['Content-Type'] = 'application/binary'
                # Next three lines are to be removed in next version
                # headers['Content-Filename'] = basename(filename)
                # file_size = stat(filename).st_size
                # headers['Content-Range'] = 'bytes 0-{}/{}'.format(file_size - 1, file_size)
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
                self._apiResource = "/netslice_templates_content"
                self._apiBase = "{}{}{}".format(
                    self._apiName, self._apiVersion, self._apiResource
                )
                endpoint = "{}{}".format(self._apiBase, ow_string)
                http_code, resp = self._http.post_cmd(
                    endpoint=endpoint, filename=filename
                )
            # print('HTTP CODE: {}'.format(http_code))
            # print('RESP: {}'.format(resp))
            # if http_code in (200, 201, 202, 204):
            if resp:
                resp = json.loads(resp)
            if not resp or "id" not in resp:
                raise ClientException(
                    "unexpected response from server - {}".format(resp)
                )
            print(resp["id"])
            # else:
            #     msg = "Error {}".format(http_code)
            #     if resp:
            #         try:
            #             msg = "{} - {}".format(msg, json.loads(resp))
            #         except ValueError:
            #             msg = "{} - {}".format(msg, resp)
            #     raise ClientException("failed to create/update nst - {}".format(msg))

    def update(self, name, filename):
        self._logger.debug("")
        nst = self.get(name)
        endpoint = "{}/{}/nst_content".format(self._apiBase, nst["_id"])
        self.create(filename=filename, update_endpoint=endpoint)
