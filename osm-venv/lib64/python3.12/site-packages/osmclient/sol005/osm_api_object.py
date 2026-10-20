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
OSM Generic OSM API Object
Abstract base class used by other objects
"""

from abc import ABC, abstractmethod
from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
from osmclient.common import utils
import json
import logging
import magic
import os
import shutil
import tempfile
from math import ceil
from time import sleep


class GenericOSMAPIObject(ABC):
    @abstractmethod
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._apiName = "/generic"
        self._apiVersion = "/v1"
        self._apiResource = "/objects"
        self._logObjectName = "object"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )
        self._logger = logging.getLogger("osmclient")

    def set_http_headers(self, filename, multipart=False):
        headers = self._client._headers
        if multipart:
            # requests library should know which Content-Type to set
            # headers["Content-Type"] = "multipart/form-data"
            headers.pop("Content-Type")
            return
        mime_type = magic.from_file(filename, mime=True)
        if mime_type is None:
            raise ClientException(
                "Unexpected MIME type for file {}: MIME type {}".format(
                    filename, mime_type
                )
            )
        headers["Content-Filename"] = os.path.basename(filename)
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

    def generate_package(self, name, path, basedir):
        """Generate a package (tar.gz) from path"""
        self._logger.debug("")
        if not os.path.exists(path):
            raise ClientException(f"The specified {path} does not exist")
        try:
            self._logger.debug(f"basename: {os.path.join(basedir, name)}")
            self._logger.debug(f"root_dir: {path}")
            zip_package = shutil.make_archive(
                base_name=os.path.join(basedir, name),
                format="gztar",
                root_dir=path,
            )
            self._logger.info(f"Package created: {zip_package}")
            return zip_package
        except Exception as exc:
            raise ClientException("failure during build of zip file: {}".format(exc))

    def list(self, filter=None):
        """List all Generic OSM API Object"""
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
        """
        Gets and shows an individual Generic OSM API Object
        from the list of all objects of the same kind
        """
        self._logger.debug("")
        self._client.get_token()
        if utils.validate_uuid4(name):
            for item in self.list():
                if name == item["_id"]:
                    return item
        else:
            for item in self.list():
                if "_id" in item and name == item["_id"]:
                    return item
                elif "name" in item and name == item["name"]:
                    return item
        raise NotFound(f"{self._logObjectName} {name} not found")

    def get_individual(self, name):
        """Gets and shows an individual Generic OSM API Object"""
        # It is redundant, since the method `get` already gets the whole item
        # The only difference is that a different primitive is exercised
        self._logger.debug("")
        item = self.get(name)
        try:
            _, resp = self._http.get2_cmd("{}/{}".format(self._apiBase, item["_id"]))
            if resp:
                return json.loads(resp)
        except NotFound:
            raise NotFound(f"{self._logObjectName} '{name}' not found")
        raise NotFound(f"{self._logObjectName} '{name}' not found")

    def delete(self, name, force=False, endpoint=None):
        """Delete the Generic OSM API Object specified by name"""
        self._logger.debug("")
        self._client.get_token()
        item = self.get(name)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        if not endpoint:
            endpoint = f"{self._apiBase}/{item['_id']}"
        http_code, resp = self._http.delete_cmd(f"{endpoint}{querystring}")

        if http_code == 202:
            print("Deletion in progress")
        elif http_code == 204:
            print("Deleted")
        else:
            msg = resp or ""
            raise ClientException(
                f"failed to delete {self._logObjectName} {name} - {msg}"
            )

    def generic_post(self, endpoint, content):
        return self._http.post_cmd(
            endpoint=endpoint,
            postfields_dict=content,
            skip_query_admin=True,
        )

    def generic_operation(self, content, endpoint_suffix):
        """
        Send a POST message for a generic operation over a Generic OSM API Object
        :param: content: the content of the message
        :param: endpoint_suffix: the suffix to be added to the endpoint
        :return: op_id, the operation identifier provided by OSM
        """
        self._logger.debug("")
        self._client.get_token()
        endpoint = f"{self._apiBase}/{endpoint_suffix}"
        http_code, resp = self.generic_post(endpoint=endpoint, content=content)
        if http_code in (200, 201, 202):
            if not resp:
                raise ClientException(f"unexpected response from server - {resp}")
            resp = json.loads(resp)
            output = resp["op_id"]
            print(output)
        elif http_code == 204:
            print("Received")

    def multi_create_update(self, content, endpoint_suffix=None):
        """Create or update a bundle of Generic OSM API Object specified by content"""
        self._logger.debug("")
        self._client.get_token()
        if endpoint_suffix:
            endpoint = f"{self._apiBase}/{endpoint_suffix}"
        else:
            endpoint = f"{self._apiBase}"
        http_code, resp = self.generic_post(endpoint=endpoint, content=content)
        if http_code in (200, 201, 202):
            if not resp:
                raise ClientException(f"unexpected response from server - {resp}")
            resp = json.loads(resp)
            # print(resp)
            output = ",".join(resp["id"])
            print(output)
        elif http_code == 204:
            print("Received")

    def multi_delete(self, name_list, prefix="", force=False):
        """Delete the list of Generic OSM API Object specified by name_list"""
        self._logger.debug("")
        self._client.get_token()

        # Get the id for each element
        item_list = []
        for name in name_list:
            item = self.get(name)
            item_list.append(item["_id"])

        # Prepare delete_content
        if not prefix:
            delete_content = item_list
        else:
            delete_content = {prefix: []}
            for i in item_list:
                delete_content[prefix].append({"_id": i})

        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self.generic_post(
            endpoint=f"{self._apiBase}/delete{querystring}", content=delete_content
        )
        if http_code in (201, 202):
            print("Deletion in progress")
        elif http_code in (200, 204):
            print("Deleted")
        else:
            msg = resp or ""
            raise ClientException(
                f"failed to create {self._logObjectName}. Http code: {http_code}. Message: {msg}"
            )

    def create(self, name, content_dict=None, filename=None, endpoint=None):
        """Creates a new Generic OSM API Object"""
        self._logger.debug(f"Creating Generic OSM API Object {name}")
        self._client.get_token()
        if not endpoint:
            endpoint = self._apiBase
        # If filename is dir, generate a tar.gz file
        tempdir = None
        if filename:
            if os.path.isdir(filename):
                tempdir = tempfile.TemporaryDirectory()
                basedir = tempdir.name
                filename = filename.rstrip("/")
                filename = self.generate_package(name, filename, basedir)
        if content_dict and not filename:
            # Typical case. Only a dict
            self._logger.debug("Sending only a dict")
            _, resp = self._http.post_cmd(
                endpoint=endpoint,
                postfields_dict=content_dict,
                skip_query_admin=True,
            )
        elif not content_dict and not filename:
            # No content at all. Raise error
            raise ClientException(
                f"failed to create {self._logObjectName} {name} - No content to be sent"
            )
        elif content_dict and filename:
            self._logger.debug("Sending a multipart file: a dict and a file")
            # It's a form and data
            formfile = {
                "package": (
                    os.path.basename(filename),
                    open(filename, "rb"),
                    "application/gzip",
                ),
            }
            self._logger.debug(f"formfile: {formfile}")
            self.set_http_headers(filename, multipart=True)
            _, resp = self._http.post_cmd(
                endpoint=endpoint, postdata=content_dict, formfile=formfile
            )
        elif not content_dict and filename:
            self._logger.debug("Sending only a file")
            # Only a file to be sent
            self.set_http_headers(filename)
            _, resp = self._http.post_cmd(endpoint=endpoint, filename=filename)
        if resp:
            resp = json.loads(resp)
            self._logger.debug(f"Resp: {resp}")
        if not resp or ("_id" not in resp and "id" not in resp):
            raise ClientException("Unexpected response from server - {}".format(resp))
        if "id" in resp:
            print(resp["id"])
        else:
            print(resp["_id"])
        if tempdir:
            tempdir.cleanup()

    def update(self, name, changes_dict=None, filename=None, force_multipart=False):
        """Updates a Generic OSM API Object"""
        self._logger.debug("")
        self._client.get_token()
        item = self.get(name)

        formfile = None
        tempdir = None
        if filename:
            # If filename is dir, generate a tar.gz file
            if os.path.isdir(filename):
                tempdir = tempfile.TemporaryDirectory()
                basedir = tempdir.name
                filename = filename.rstrip("/")
                filename = self.generate_package(name, filename, basedir)
            self._logger.debug("Sending a multipart file: a dict and a file")
            # It's a form and data
            formfile = {
                "package": (filename, open(filename, "rb"), "application/gzip"),
            }
            self.set_http_headers(filename, multipart=True)

        if not filename and force_multipart:
            self.set_http_headers(filename, multipart=True)

        http_code, resp = self._http.patch_cmd(
            endpoint="{}/{}".format(self._apiBase, item["_id"]),
            postfields_dict=changes_dict,
            formfile=formfile,
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

    def update_content(self, name, filename):
        """Updates the content of a Generic OSM API Object"""
        self._logger.debug("")
        self._client.get_token()
        item = self.get(name)

        tempdir = None
        if filename:
            if os.path.isdir(filename):
                tempdir = tempfile.TemporaryDirectory()
                basedir = tempdir.name
                filename = filename.rstrip("/")
                filename = self.generate_package(name, filename, basedir)
        self._logger.debug("Sending only a file")
        # Only a file to be sent
        self.set_http_headers(filename)
        http_code, resp = self._http.put_cmd(
            endpoint="{}/{}".format(self._apiBase, item["_id"]),
            filename=filename,
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
        if tempdir:
            tempdir.cleanup()

    def wait_for_operation_status(self, id, timeout, operation_id):
        """
        Wait until operation ends, making polling every 5s. Prints detailed status when it changes
        :param id: ID of the entity to be checked.
        :param timeout: Timeout in seconds
        :param operation_id: ID of the operation to be checked
        :return: True if operation completes successfully, False otherwise
        """
        # Loop here until the operation finishes, or a timeout occurs.
        self._logger.debug("")
        POLLING_TIME_INTERVAL = 5
        tries = 0
        max_tries = ceil(timeout / POLLING_TIME_INTERVAL)
        while tries < max_tries:
            self._logger.info(f"Wait for operation to complete. Try {tries+1}")
            item = self.get(id)
            for op in item.get("operationHistory", []):
                if op["op_id"] == operation_id:
                    if op["result"]:
                        return True
                    break
            sleep(POLLING_TIME_INTERVAL)
            tries += 1
        return False
