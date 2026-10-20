# Copyright 2017-2018 Sandvine
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
OSM client entry point
"""

from osmclient.sol005 import client as sol005client
import logging
import verboselogs

# pylint: disable=E1101
verboselogs.install()


def Client(version=1, host=None, *args, **kwargs):
    log_format_simple = "%(levelname)s %(message)s"
    log_format_complete = "%(asctime)s %(levelname)s %(name)s %(filename)s:%(lineno)s %(funcName)s(): %(message)s"
    log_formatter_simple = logging.Formatter(
        log_format_simple, datefmt="%Y-%m-%dT%H:%M:%S"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(log_formatter_simple)
    logger = logging.getLogger("osmclient")
    logger.setLevel(level=logging.WARNING)
    logger.addHandler(handler)
    verbose = kwargs.get("verbose", 0)
    if verbose > 0:
        log_formatter = logging.Formatter(
            log_format_complete, datefmt="%Y-%m-%dT%H:%M:%S"
        )
        # handler = logging.StreamHandler()
        handler.setFormatter(log_formatter)
        # logger.addHandler(handler)
        if verbose == 1:
            logger.setLevel(level=logging.INFO)
        elif verbose == 2:
            logger.setLevel(level=logging.VERBOSE)
        elif verbose > 2:
            logger.setLevel(level=logging.DEBUG)
    if version == 1:
        return sol005client.Client(host, *args, **kwargs)
    else:
        raise Exception("Unsupported client version")
