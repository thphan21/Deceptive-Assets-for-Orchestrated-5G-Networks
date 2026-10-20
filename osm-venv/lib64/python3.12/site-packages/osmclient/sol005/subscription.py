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
#

"""
OSM Subscription API handling
"""

from osmclient.common.exceptions import NotFound
from osmclient.common.exceptions import ClientException
import yaml
import json
import logging


class Subscription(object):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._apiName = "/nslcm"
        self._apiVersion = "/v1"
        self._apiResource = "/subscriptions"
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def _rebuild_apibase(self, event_type):
        self._logger.debug("")
        if event_type == "ns":
            self._apiName = "/nslcm"
        else:
            raise ClientException("unsupported event_type {}".format(event_type))
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def create(self, event_type, event):
        """
        Creates a subscription
        :param event_type: event type to be subscribed (only ns is supported)
        :param event: yaml string defining the event to be subscribed
        :return: None. Exception if fail
        """
        self._logger.debug("")
        self._client.get_token()
        self._rebuild_apibase(event_type)

        subscription_event = yaml.safe_load(event)

        http_code, resp = self._http.post_cmd(
            endpoint=self._apiBase, postfields_dict=subscription_event
        )
        if resp:
            resp = json.loads(resp)
        if not resp or "id" not in resp:
            raise ClientException("unexpected response from server - {}".format(resp))
        print(resp["id"])

    def delete(self, event_type, subscription_id, force=False):
        """
        Deletes a subscription
        :param event_type: event type to be subscribed (only ns is supported)
        :param subscription_id: identifier of the subscription
        :param force: forces deletion
        :return: None. Exception if fail
        """
        self._logger.debug("")
        self._client.get_token()
        self._rebuild_apibase(event_type)
        querystring = ""
        if force:
            querystring = "?FORCE=True"
        http_code, resp = self._http.delete_cmd(
            "{}/{}{}".format(self._apiBase, subscription_id, querystring)
        )
        if http_code == 202:
            print("Deletion in progress")
        elif http_code == 204:
            print("Deleted")
        else:
            msg = resp or ""
            raise ClientException(
                "failed to delete subscription {} - {}".format(subscription_id, msg)
            )

    def list(self, event_type, filter=None):
        """
        Returns a list of subscriptions
        :param event_type: event type to be subscribed (only ns is supported)
        :param filter
        :return: list of subscriptions
        """
        self._logger.debug("")
        self._client.get_token()
        self._rebuild_apibase(event_type)
        filter_string = ""
        if filter:
            filter_string = "?{}".format(filter)
        _, resp = self._http.get2_cmd("{}{}".format(self._apiBase, filter_string))
        if resp:
            return json.loads(resp)
        return list()

    def get(self, event_type, subscription_id):
        """
        Returns a subscription from a subscription id
        :param event_type: event type to be subscribed (only ns is supported)
        :param subscription_id: identifier of the subscription
        :return: dict with the subscription
        """
        self._logger.debug("")
        self._client.get_token()
        self._rebuild_apibase(event_type)
        try:
            _, resp = self._http.get2_cmd(
                "{}/{}".format(self._apiBase, subscription_id)
            )
            self._logger.debug(yaml.safe_dump(resp))
            if not resp or "id" not in resp:
                raise ClientException(
                    "failed to get subscription info: {}".format(resp)
                )
            return json.loads(resp)
        except NotFound:
            raise NotFound("subscription '{}' not found".format(subscription_id))
