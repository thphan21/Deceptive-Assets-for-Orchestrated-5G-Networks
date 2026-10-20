# Copyright 2017 Sandvine
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

import requests
import urllib3
from requests.auth import HTTPBasicAuth
import json
import logging

urllib3.disable_warnings()


class Http(object):
    def __init__(self, url, user="admin", password="admin"):
        self._url = url
        self._user = user
        self._password = password
        self._http_header = None
        self._logger = logging.getLogger("osmclient")

    def set_http_header(self, header):
        self._http_header = header

    def _get_requests_cmd(self, endpoint):
        requests_cmd = requests.Request()
        requests_cmd.url = self._url + endpoint
        requests_cmd.auth = HTTPBasicAuth(self._user, self._password)
        if self._http_header:
            requests_cmd.headers = self._http_header
        return requests_cmd

    def get_cmd(self, endpoint):
        session_cmd = requests.Session()
        requests_cmd = self._get_requests_cmd(endpoint)
        requests_cmd.method = "GET"
        self._logger.info(
            "Request METHOD: {} URL: {}".format("GET", self._url + endpoint)
        )
        requests_cmd = requests_cmd.prepare()
        resp = session_cmd.send(requests_cmd, verify=False)
        http_code = resp.status_code
        self._logger.info("Response HTTPCODE: {}".format(http_code))
        data = resp.content
        session_cmd.close()
        if data:
            self._logger.debug("Response DATA: {}".format(json.loads(data.decode())))
            return json.loads(data.decode())
        return None

    def delete_cmd(self, endpoint):
        session_cmd = requests.Session()
        requests_cmd = self._get_requests_cmd(endpoint)
        requests_cmd.method = "DELETE"
        self._logger.info(
            "Request METHOD: {} URL: {}".format("DELETE", self._url + endpoint)
        )
        requests_cmd = requests_cmd.prepare()
        resp = session_cmd.send(requests_cmd, verify=False)
        http_code = resp.status_code
        self._logger.info("Response HTTPCODE: {}".format(http_code))
        data = resp.content
        session_cmd.close()
        if data:
            self._logger.debug("Response DATA: {}".format(json.loads(data.decode())))
            return json.loads(data.decode())
        return None

    def post_cmd(
        self,
        endpoint="",
        postfields_dict=None,
        formfile=None,
    ):
        session_cmd = requests.Session()
        requests_cmd = self._get_requests_cmd(endpoint)
        requests_cmd.method = "POST"

        if postfields_dict is not None:
            requests_cmd.json = json.dumps(postfields_dict)

        if formfile is not None:
            requests_cmd.files = {formfile[0]: formfile[1]}

        self._logger.info(
            "Request METHOD: {} URL: {}".format("POST", self._url + endpoint)
        )
        requests_cmd = requests_cmd.prepare()
        resp = session_cmd.send(requests_cmd, verify=False)
        http_code = resp.status_code
        self._logger.info("Response HTTPCODE: {}".format(http_code))
        data = resp.content
        session_cmd.close()
        if data:
            self._logger.debug("Response DATA: {}".format(json.loads(data.decode())))
            return json.loads(data.decode())
        return None
