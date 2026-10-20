#######################################################################################
# Copyright ETSI Contributors and Others.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#######################################################################################
import logging
import json
from osmclient.cli_commands import utils
from osmclient.common import print_output
from osmclient.common.exceptions import ClientException


logger = logging.getLogger("osmclient")


def iterator_split(iterator, separators):
    """
    Splits a tuple or list into several lists whenever a separator is found
    For instance, the following tuple will be separated with the separator "--vnf" as follows.
    From:
        ("--vnf", "A", "--cause", "cause_A", "--vdu", "vdu_A1", "--vnf", "B", "--cause", "cause_B", ...
        "--vdu", "vdu_B1", "--count_index", "1", "--run-day1", "--vdu", "vdu_B1", "--count_index", "2")
    To:
        [
            ("--vnf", "A", "--cause", "cause_A", "--vdu", "vdu_A1"),
            ("--vnf", "B", "--cause", "cause_B", "--vdu", "vdu_B1", "--count_index", "1", "--run-day1", ...
             "--vdu", "vdu_B1", "--count_index", "2")
        ]

    Returns as many lists as separators are found
    """
    logger.debug("")
    if iterator[0] not in separators:
        raise ClientException(f"Expected one of {separators}. Received: {iterator[0]}.")
    list_of_lists = []
    first = 0
    for i in range(len(iterator)):
        if iterator[i] in separators:
            if i == first:
                continue
            if i - first < 2:
                raise ClientException(
                    f"Expected at least one argument after separator (possible separators: {separators})."
                )
            list_of_lists.append(list(iterator[first:i]))
            first = i
    if (len(iterator) - first) < 2:
        raise ClientException(
            f"Expected at least one argument after separator (possible separators: {separators})."
        )
    else:
        list_of_lists.append(list(iterator[first : len(iterator)]))
    # logger.debug(f"List of lists: {list_of_lists}")
    return list_of_lists


def generic_update(newname, description, extras):
    changes_dict = {k: v for k, v in extras.items() if v is not None}
    if newname:
        changes_dict["name"] = newname
    if description:
        changes_dict["description"] = description
    return changes_dict


def generic_show(callback, name, format="table"):
    logger.debug("")
    resp = callback(name)
    headers = ["field", "value"]
    rows = []
    if format == "table" or format == "csv":
        if resp:
            for k, v in list(resp.items()):
                rows.append(
                    [
                        utils.wrap_text(k, 30),
                        utils.wrap_text(text=json.dumps(v, indent=2)),
                    ]
                )
    print_output.print_output(format, headers, rows, resp)


def generic_list(callback, filter, format="table", extras=None):
    if not extras:
        extras = []
    logger.debug("")
    if filter:
        filter = "&".join(filter)
    resp = callback(filter)
    headers = ["Name", "Id", "Git State", "Resource State", "Operating State"]
    headers.extend([item["header"] for item in extras])
    rows = []
    if format == "table" or format == "csv":
        for item in resp:
            row_item = [
                item["name"],
                item["_id"],
                item["state"],
                item["resourceState"],
                item["operatingState"],
            ]
            for extra_item in extras:
                item1 = item.get(extra_item["item"], "-")
                if item1 == "true":
                    item1 = "YES"
                elif item1 == "false":
                    item1 = "NO"
                row_item.append(item1)
            rows.append(row_item)
    print_output.print_output(format, headers, rows, resp)
