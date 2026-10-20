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

import copy
import json
import logging
import requests
import http.client as http_client
import urllib3

from osmclient.common import http
from osmclient.common.exceptions import OsmHttpException, NotFound


urllib3.disable_warnings()


class Http(http.Http):
    CONNECT_TIMEOUT = 15

    def __init__(self, url, user="admin", password="admin", **kwargs):
        self._url = url
        self._user = user
        self._password = password
        self._http_header = None
        self._logger = logging.getLogger("osmclient")
        self._default_query_admin = None
        self._all_projects = None
        self._public = None
        if "all_projects" in kwargs:
            self._all_projects = kwargs["all_projects"]
        if "public" in kwargs:
            self._public = kwargs["public"]
        self._default_query_admin = self._complete_default_query_admin()

    def _complete_default_query_admin(self):
        query_string_list = []
        if self._all_projects:
            query_string_list.append("ADMIN")
        if self._public is not None:
            query_string_list.append("PUBLIC={}".format(self._public))
        return "&".join(query_string_list)

    def _complete_endpoint(self, endpoint):
        if self._default_query_admin:
            if "?" in endpoint:
                endpoint = "&".join([endpoint, self._default_query_admin])
            else:
                endpoint = "?".join([endpoint, self._default_query_admin])
        return endpoint

    def _get_requests_cmd(self, endpoint, skip_query_admin=False):
        self._logger.debug("")
        requests_cmd = requests.Request()
        if self._logger.getEffectiveLevel() == logging.DEBUG:
            http_client.HTTPConnection.debuglevel = 1
            requests_log = logging.getLogger("requests.packages.urllib3")
            requests_log.setLevel(logging.DEBUG)
            requests_log.propagate = True
        else:
            http_client.HTTPConnection.debuglevel = 0
            requests_log = logging.getLogger("requests.packages.urllib3")
            requests_log.setLevel(logging.NOTSET)
            requests_log.propagate = True

        if not skip_query_admin:
            endpoint = self._complete_endpoint(endpoint)
        requests_cmd.url = self._url + endpoint
        if self._http_header:
            requests_cmd.headers = self._http_header
        return requests_cmd

    def delete_cmd(self, endpoint, skip_query_admin=False):
        session_cmd = requests.Session()
        self._logger.debug("")
        requests_cmd = self._get_requests_cmd(endpoint, skip_query_admin)
        requests_cmd.method = "DELETE"
        self._logger.info(
            "Request METHOD: {} URL: {}".format("DELETE", self._url + endpoint)
        )
        requests_cmd = requests_cmd.prepare()
        resp = session_cmd.send(
            requests_cmd, verify=False, timeout=self.CONNECT_TIMEOUT
        )
        http_code = resp.status_code
        self._logger.info("Response HTTPCODE: {}".format(http_code))
        data = resp.content
        session_cmd.close()
        self.check_http_response(http_code, data)
        # TODO 202 accepted should be returned somehow
        if data:
            data_text = data.decode()
            self._logger.verbose("Response DATA: {}".format(data_text))
            return http_code, data_text
        return http_code, None

    def send_cmd(
        self,
        endpoint="",
        postfields_dict=None,
        postdata=None,
        formfile=None,
        filename=None,
        put_method=False,
        patch_method=False,
        skip_query_admin=False,
    ):
        session_cmd = requests.Session()
        self._logger.debug("")
        requests_cmd = self._get_requests_cmd(endpoint, skip_query_admin)
        if put_method:
            requests_cmd.method = "PUT"
        elif patch_method:
            requests_cmd.method = "PATCH"
        else:
            requests_cmd.method = "POST"

        if postfields_dict is not None:
            jsondata = json.dumps(postfields_dict)
            if "password" in postfields_dict:
                postfields_dict_copy = copy.deepcopy(postfields_dict)
                postfields_dict_copy["password"] = "******"
                jsondata_log = json.dumps(postfields_dict_copy)
            else:
                jsondata_log = jsondata
            requests_cmd.json = postfields_dict
            self._logger.verbose("Request POSTFIELDS: {}".format(jsondata_log))
        if postdata is not None:
            self._logger.verbose("Request DATA: {}".format(postdata))
            requests_cmd.data = postdata
        if formfile is not None:
            self._logger.verbose("Request FILES: {}".format(formfile))
            requests_cmd.files = formfile
        if filename is not None:
            with open(filename, "rb") as stream:
                filedata = stream.read()
            self._logger.verbose("Request POSTFIELDS: Binary content")
            requests_cmd.data = filedata

        if put_method:
            self._logger.info(
                "Request METHOD: {} URL: {}".format("PUT", self._url + endpoint)
            )
        elif patch_method:
            self._logger.info(
                "Request METHOD: {} URL: {}".format("PATCH", self._url + endpoint)
            )
        else:
            self._logger.info(
                "Request METHOD: {} URL: {}".format("POST", self._url + endpoint)
            )
        requests_cmd = requests_cmd.prepare()
        resp = session_cmd.send(
            requests_cmd, verify=False, timeout=self.CONNECT_TIMEOUT
        )
        http_code = resp.status_code
        self._logger.info("Response HTTPCODE: {}".format(http_code))
        data = resp.content
        self.check_http_response(http_code, data)
        session_cmd.close()
        if data:
            data_text = data.decode()
            self._logger.verbose("Response DATA: {}".format(data_text))
            return http_code, data_text
        return http_code, None

    def post_cmd(
        self,
        endpoint="",
        postfields_dict=None,
        postdata=None,
        formfile=None,
        filename=None,
        skip_query_admin=False,
    ):
        self._logger.debug("")
        return self.send_cmd(
            endpoint=endpoint,
            postfields_dict=postfields_dict,
            postdata=postdata,
            formfile=formfile,
            filename=filename,
            put_method=False,
            patch_method=False,
            skip_query_admin=skip_query_admin,
        )

    def put_cmd(
        self,
        endpoint="",
        postfields_dict=None,
        postdata=None,
        formfile=None,
        filename=None,
        skip_query_admin=False,
    ):
        self._logger.debug("")
        return self.send_cmd(
            endpoint=endpoint,
            postfields_dict=postfields_dict,
            postdata=postdata,
            formfile=formfile,
            filename=filename,
            put_method=True,
            patch_method=False,
            skip_query_admin=skip_query_admin,
        )

    def patch_cmd(
        self,
        endpoint="",
        postfields_dict=None,
        postdata=None,
        formfile=None,
        filename=None,
        skip_query_admin=False,
    ):
        self._logger.debug("")
        return self.send_cmd(
            endpoint=endpoint,
            postfields_dict=postfields_dict,
            postdata=postdata,
            formfile=formfile,
            filename=filename,
            put_method=False,
            patch_method=True,
            skip_query_admin=skip_query_admin,
        )

    def get2_cmd(self, endpoint, skip_query_admin=False):
        session_cmd = requests.Session()
        self._logger.debug("")
        requests_cmd = self._get_requests_cmd(endpoint, skip_query_admin)
        requests_cmd.method = "GET"
        self._logger.info(
            "Request METHOD: {} URL: {}".format("GET", self._url + endpoint)
        )
        requests_cmd = requests_cmd.prepare()
        resp = session_cmd.send(
            requests_cmd, verify=False, timeout=self.CONNECT_TIMEOUT
        )
        http_code = resp.status_code
        self._logger.info("Response HTTPCODE: {}".format(http_code))
        data = resp.content
        session_cmd.close()
        self.check_http_response(http_code, data)
        if data:
            data_text = data.decode()
            self._logger.verbose("Response DATA: {}".format(data_text))
            return http_code, data_text
        return http_code, None

    def check_http_response(self, http_code, data):
        self._logger.debug("")
        if http_code >= 300:
            resp = ""
            if data:
                data_text = data.decode()
                self._logger.verbose(
                    "Response {} DATA: {}".format(http_code, data_text)
                )
                resp = ": " + data_text
            else:
                self._logger.verbose("Response {}".format(http_code))
            if http_code == 404:
                raise NotFound("Error {}{}".format(http_code, resp))
            raise OsmHttpException("Error {}{}".format(http_code, resp))

    def set_query_admin(self, **kwargs):
        if "all_projects" in kwargs:
            self._all_projects = kwargs["all_projects"]
        if "public" in kwargs:
            self._public = kwargs["public"]
        self._default_query_admin = self._complete_default_query_admin()
