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
import click
import logging
import json
import yaml
from prettytable import PrettyTable

from jsonpath_ng.ext import parse


logger = logging.getLogger("osmclient")


def evaluate_output_format(ctx, param, value):
    logger.debug("")
    if value in ["table", "json", "yaml", "csv"]:
        return value
    elif value.startswith("jsonpath="):
        return value
    else:
        raise click.BadParameter(
            f"{value} is not one of 'table', 'json', 'yaml', 'csv', 'jsonpath'"
        )


output_option = click.option(
    "-o",
    "--output",
    default="table",
    is_eager=True,
    callback=evaluate_output_format,
    help="output format (table, json, yaml, csv, jsonpath=...) (default: table)",
)


literal_option = click.option(
    "--literal", is_flag=True, help="print literally, no pretty table"
)


def normalize_jsonpath(json_path_expression):
    """
    Normalizes JSONPath expressions from kubectl format to jsonpath_ng format.
    Example:
    - '{.name}' becomes 'name'
    - '{.items[0].metadata.name}' becomes 'items[0].metadata.name'
    """
    # Remove braces at the beginning and end
    if json_path_expression.startswith("{") and json_path_expression.endswith("}"):
        json_path_expression = json_path_expression[1:-1]
    # Remove the leading '.'
    if json_path_expression.startswith("."):
        json_path_expression = json_path_expression[1:]
    return json_path_expression


def print_output(format="table", headers=["field", "value"], rows=None, data=None):
    """
    Prints content in specified format.
    :param format: output format (table, yaml, json, csv, jsonpath=...). Default:
    :param headers: headers of the content
    :param rows: rows of the content
    :param data: dictionary or list with the content to be printed. Only applies to yaml, json or jsonpath format.
                 If specified, headers and rows are ignored, and json/yaml/jsonpath output is generated directly from data.
    """

    logger.debug("")
    if not rows:
        rows = []
    if format == "table":
        table = PrettyTable(headers)
        table.align = "l"
        for row in rows:
            table.add_row(row)
        print(table)
    elif format == "csv":
        table = PrettyTable(headers)
        for row in rows:
            table.add_row(row)
        print(table.get_csv_string())
    elif format == "json" or format == "yaml" or format.startswith("jsonpath="):
        if not data:
            data = []
            for row in rows:
                item = {}
                for i in range(len(row)):
                    item[headers[i]] = row[i]
                data.append(item)
        if format == "json":
            print(json.dumps(data, indent=4))
        elif format == "yaml":
            print(
                yaml.safe_dump(
                    data, indent=4, default_flow_style=False, sort_keys=False
                )
            )
        elif format.startswith("jsonpath="):
            # JSONPath expression
            json_path_expression = format.partition("=")[-1]
            logger.debug(f"Received jsonpath expression: {json_path_expression}")
            # Support kubectl format
            if json_path_expression.startswith("{") and json_path_expression.endswith(
                "}"
            ):
                logger.debug("Detected kubectl JSONPath format")
                json_path_expression = normalize_jsonpath(json_path_expression)
            logger.debug(f"Final jsonpath expression: {json_path_expression}")
            json_path = parse(json_path_expression)
            # Apply JSONPath expression on the JSON object
            results = [match.value for match in json_path.find(data)]
            for i in results:
                print(i)
