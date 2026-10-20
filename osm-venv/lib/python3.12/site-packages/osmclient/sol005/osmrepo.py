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
OSM Repo API handling
"""
import glob
import logging
from os import listdir, mkdir, getcwd, remove
from os.path import isfile, isdir, join, abspath
from shutil import copyfile, rmtree
import tarfile
import tempfile
import time

from osm_im.validation import Validation as validation_im
from osmclient.common.exceptions import ClientException
from osmclient.common.package_tool import PackageTool
from osmclient.sol005.repo import Repo
from osmclient.common import utils
from packaging import version as versioning
import requests
import yaml


class OSMRepo(Repo):
    def __init__(self, http=None, client=None):
        self._http = http
        self._client = client
        self._apiName = "/admin"
        self._apiVersion = "/v1"
        self._apiResource = "/osmrepos"
        self._logger = logging.getLogger("osmclient")
        self._apiBase = "{}{}{}".format(
            self._apiName, self._apiVersion, self._apiResource
        )

    def pkg_list(self, pkgtype, filter=None, repo=None):
        """
        Returns a repo based on name or id
        """
        self._logger.debug("")
        self._client.get_token()
        # Get OSM registered repository list
        repositories = self.list()
        if repo:
            repositories = [r for r in repositories if r["name"] == repo]
        if not repositories:
            raise ClientException("Not repository found")

        vnf_repos = []
        for repository in repositories:
            try:
                r = requests.get(f"{repository.get('url')}/index.yaml", timeout=10)

                if r.status_code == 200:
                    repo_list = yaml.safe_load(r.text)
                    vnf_packages = repo_list.get("{}_packages".format(pkgtype))
                    for repo in vnf_packages:
                        versions = vnf_packages.get(repo)
                        latest = versions.get("latest")
                        del versions["latest"]
                        for version in versions:
                            latest_version = False
                            if version == latest:
                                latest_version = True
                            vnf_repos.append(
                                {
                                    "vendor": versions[version].get("vendor"),
                                    "name": versions[version].get("name"),
                                    "version": version,
                                    "description": versions[version].get("description"),
                                    "location": versions[version].get("path"),
                                    "repository": repository.get("name"),
                                    "repourl": repository.get("url"),
                                    "latest": latest_version,
                                }
                            )
                else:
                    raise Exception(
                        "repository in url {} unreachable".format(repository.get("url"))
                    )
            except Exception as e:
                self._logger.error(
                    "Error cannot read from repository {} '{}': {}".format(
                        repository["name"], repository["url"], e
                    ),
                    exc_info=True,
                )
                continue

        vnf_repos_filtered = []
        if filter:
            for vnf_repo in vnf_repos:
                for k, v in vnf_repo.items():
                    if v:
                        kf, vf = filter.split("=")
                        if k == kf and vf in v:
                            vnf_repos_filtered.append(vnf_repo)
                            break
            vnf_repos = vnf_repos_filtered
        return vnf_repos

    def get_pkg(self, pkgtype, name, repo, filter, version):
        """
        Returns the filename of the PKG downloaded to disk
        """
        self._logger.debug("")
        self._client.get_token()
        f = None
        f_name = None
        # Get OSM registered repository list
        pkgs = self.pkg_list(pkgtype, filter, repo)
        for pkg in pkgs:
            if pkg.get("repository") == repo and pkg.get("name") == name:
                if "latest" in version:
                    if not pkg.get("latest"):
                        continue
                    else:
                        version = pkg.get("version")
                if pkg.get("version") == version:
                    r = requests.get(
                        "{}{}".format(pkg.get("repourl"), pkg.get("location")),
                        stream=True,
                        timeout=10,  # Prevents uncontrolled consumption of socket descriptors
                    )
                    if r.status_code != 200:
                        raise ClientException("Package not found")

                    with tempfile.NamedTemporaryFile(delete=False) as f:
                        f.write(r.raw.read())
                        f_name = f.name
                    if not f_name:
                        raise ClientException(
                            "{} {} not found at repo {}".format(pkgtype, name, repo)
                        )
        return f_name

    def pkg_get(self, pkgtype, name, repo, version, filter):
        pkg_name = self.get_pkg(pkgtype, name, repo, filter, version)
        if not pkg_name:
            raise ClientException("Package not found")
        folder, descriptor = self.zip_extraction(pkg_name)
        with open(descriptor) as pkg:
            pkg_descriptor = yaml.safe_load(pkg)
        rmtree(folder, ignore_errors=False)
        if (
            pkgtype == "vnf"
            and (pkg_descriptor.get("vnfd") or pkg_descriptor.get("vnfd:vnfd_catalog"))
        ) or (
            pkgtype == "ns"
            and (pkg_descriptor.get("nsd") or pkg_descriptor.get("nsd:nsd_catalog"))
        ):
            raise ClientException("Wrong Package type")
        return pkg_descriptor

    def repo_index(self, origin=".", destination="."):
        """
        Repo Index main function
        :param origin: origin directory for getting all the artifacts
        :param destination: destination folder for create and index the valid artifacts
        """
        self._logger.debug("Starting index composition")
        if destination == ".":
            if origin == destination:
                destination = "repository"

        destination = abspath(destination)
        origin = abspath(origin)
        self._logger.debug(f"Paths {destination}, {origin}")
        if origin[0] != "/":
            origin = join(getcwd(), origin)
        if destination[0] != "/":
            destination = join(getcwd(), destination)

        self.init_directory(destination)
        artifacts = []
        directories = []
        for f in listdir(origin):
            self._logger.debug(f"Element: {join(origin,f)}")
            if isfile(join(origin, f)) and f.endswith(".tar.gz"):
                artifacts.append(f)
            elif (
                isdir(join(origin, f))
                and f != destination.split("/")[-1]
                and not f.startswith(".")
            ):
                directories.append(
                    f
                )  # TODO: Document that nested directories are not supported
            else:
                self._logger.debug(f"Ignoring {f}")
        self._logger.debug(f"Artifacts: {artifacts}")
        for package in artifacts:
            self.register_package_in_repository(
                join(origin, package), origin, destination, kind="artifact"
            )
        self._logger.debug(f"Directories: {directories}")
        for package in directories:
            self.register_package_in_repository(
                join(origin, package), origin, destination, kind="directory"
            )
        self._logger.info("\nFinal Results: ")
        self._logger.info(
            "VNF Packages Indexed: "
            + str(len(glob.glob(destination + "/vnf/*/*/metadata.yaml")))
        )
        self._logger.info(
            "NS Packages Indexed: "
            + str(len(glob.glob(destination + "/ns/*/*/metadata.yaml")))
        )

        self._logger.info(
            "NST Packages Indexed: "
            + str(len(glob.glob(destination + "/nst/*/*/metadata.yaml")))
        )

    def fields_building(self, descriptor_dict, file, package_type):
        """
        From an artifact descriptor, obtain the fields required for indexing
        :param descriptor_dict: artifact description
        :param file: artifact package
        :param package_type: type of artifact (vnf, ns, nst)
        :return: fields
        """
        self._logger.debug("")

        fields = {}
        base_path = "/{}/".format(package_type)
        aux_dict = {}
        if package_type == "vnf":
            if descriptor_dict.get("vnfd-catalog", False):
                aux_dict = descriptor_dict.get("vnfd-catalog", {}).get("vnfd", [{}])[0]
            elif descriptor_dict.get("vnfd:vnfd-catalog"):
                aux_dict = descriptor_dict.get("vnfd:vnfd-catalog", {}).get(
                    "vnfd", [{}]
                )[0]
            elif descriptor_dict.get("vnfd"):
                aux_dict = descriptor_dict["vnfd"]
                if aux_dict.get("vnfd"):
                    aux_dict = aux_dict["vnfd"][0]
            else:
                msg = f"Unexpected descriptor format {descriptor_dict}"
                self._logger.error(msg)
                raise ValueError(msg)
            self._logger.debug(
                f"Extracted descriptor info for {package_type}: {aux_dict}"
            )
            images = []
            for vdu in aux_dict.get("vdu", aux_dict.get("kdu", ())):
                images.append(vdu.get("image", vdu.get("name")))
            fields["images"] = images
        elif package_type == "ns":
            if descriptor_dict.get("nsd-catalog", False):
                aux_dict = descriptor_dict.get("nsd-catalog", {}).get("nsd", [{}])[0]
            elif descriptor_dict.get("nsd:nsd-catalog"):
                aux_dict = descriptor_dict.get("nsd:nsd-catalog", {}).get("nsd", [{}])[
                    0
                ]
            elif descriptor_dict.get("nsd"):
                aux_dict = descriptor_dict["nsd"]
                if aux_dict.get("nsd"):
                    aux_dict = descriptor_dict["nsd"]["nsd"][0]
            else:
                msg = f"Unexpected descriptor format {descriptor_dict}"
                self._logger.error(msg)
                raise ValueError(msg)
            vnfs = []
            if aux_dict.get("constituent-vnfd"):
                for vnf in aux_dict.get("constituent-vnfd", ()):
                    vnfs.append(vnf.get("vnfd-id-ref"))
            else:
                vnfs = aux_dict.get("vnfd-id")
            self._logger.debug("Used VNFS in the NSD: " + str(vnfs))
            fields["vnfd-id-ref"] = vnfs
        elif package_type == "nst":
            if descriptor_dict.get("nst-catalog", False):
                aux_dict = descriptor_dict.get("nst-catalog", {}).get("nst", [{}])[0]
            elif descriptor_dict.get("nst:nst-catalog"):
                aux_dict = descriptor_dict.get("nst:nst-catalog", {}).get("nst", [{}])[
                    0
                ]
            elif descriptor_dict.get("nst"):
                aux_dict = descriptor_dict["nst"]
                if aux_dict.get("nst"):
                    aux_dict = descriptor_dict["nst"]["nst"][0]
            nsds = []
            for nsd in aux_dict.get("netslice-subnet", ()):
                nsds.append(nsd.get("nsd-ref"))
            self._logger.debug("Used NSDs in the NST: " + str(nsds))
            if not nsds:
                msg = f"Unexpected descriptor format {descriptor_dict}"
                self._logger.error(msg)
                raise ValueError(msg)
            fields["nsd-id-ref"] = nsds
        else:
            msg = f"Unexpected descriptor format {descriptor_dict}"
            self._logger.error(msg)
            raise ValueError(msg)
        # Repo search is based on 'name' entry in index.yaml. It is mandatory then
        fields["name"] = aux_dict.get("name", aux_dict.get("product-name"))
        fields["id"] = aux_dict.get("id")
        fields["description"] = aux_dict.get("description")
        fields["vendor"] = aux_dict.get("vendor")
        fields["version"] = str(aux_dict.get("version", "1.0"))
        fields["path"] = "{}{}/{}/{}-{}.tar.gz".format(
            base_path,
            fields["id"],
            fields["version"],
            fields.get("id"),
            fields.get("version"),
        )
        return fields

    def zip_extraction(self, file_name):
        """
        Validation of artifact.
        :param file: file path
        :return: status details, status, fields, package_type
        """
        self._logger.debug("Decompressing package file")
        temp_file = "/tmp/{}".format(file_name.split("/")[-1])
        if file_name != temp_file:
            copyfile(file_name, temp_file)
        with tarfile.open(temp_file, "r:gz") as tar:
            folder = tar.getnames()[0].split("/")[0]
            tar.extractall()

        remove(temp_file)
        descriptor_file = glob.glob("{}/*.y*ml".format(folder))[0]
        return folder, descriptor_file

    def validate_artifact(self, path, origin, kind):
        """
        Validation of artifact.
        :param path: file path
        :param origin: folder where the package is located
        :param kind: flag to select the correct file type (directory or artifact)
        :return: status details, status, fields, package_type
        """
        self._logger.debug(f"Validating {path} {kind}")
        package_type = ""
        folder = ""
        try:
            if kind == "directory":
                descriptor_file = glob.glob("{}/*.y*ml".format(path))[0]
            else:
                folder, descriptor_file = self.zip_extraction(path)
                folder = join(origin, folder)
                self._logger.debug(
                    f"Kind is an artifact (tar.gz). Folder: {folder}. Descriptor_file: {descriptor_file}"
                )

            self._logger.debug("Opening descriptor file: {}".format(descriptor_file))

            with open(descriptor_file, "r") as f:
                descriptor_data = f.read()
            self._logger.debug(f"Descriptor data: {descriptor_data}")
            validation = validation_im()
            desc_type, descriptor_dict = validation.yaml_validation(descriptor_data)
            self._logger.debug(f"Descriptor type: {desc_type}")
            self._logger.debug(f"Descriptor dict: {descriptor_dict}")
            try:
                validation_im.pyangbind_validation(self, desc_type, descriptor_dict)
            except Exception as e:
                self._logger.error(e, exc_info=True)
                raise e
            descriptor_type_ref = list(descriptor_dict.keys())[0].lower()
            self._logger.debug(f"Descriptor type ref: {descriptor_type_ref}")
            if "vnf" in descriptor_type_ref:
                package_type = "vnf"
            elif "nst" in descriptor_type_ref:
                package_type = "nst"
            elif "ns" in descriptor_type_ref:
                package_type = "ns"
            else:
                msg = f"Unknown package type {descriptor_type_ref}"
                self._logger.error(msg)
                raise ValueError(msg)
            self._logger.debug("Descriptor: {}".format(descriptor_dict))
            self._logger.debug("Path: {}".format(path))
            self._logger.debug("Package type: {}".format(package_type))
            fields = self.fields_building(descriptor_dict, path, package_type)
            self._logger.debug(f"Descriptor successfully validated {fields}")
            return (
                {
                    "detail": "{}D successfully validated".format(package_type.upper()),
                    "code": "OK",
                },
                True,
                fields,
                package_type,
            )
        except Exception as e:
            # Delete the folder we just created
            return {"detail": str(e)}, False, {}, package_type
        finally:
            if folder:
                rmtree(folder, ignore_errors=True)

    def register_package_in_repository(self, path, origin, destination, kind):
        """
        Registration of one artifact in a repository
        :param path: absolute path of the VNF/NS package
        :param origin: folder where the package is located
        :param destination: path for index creation
        :param kind: artifact (tar.gz) or directory
        """
        self._logger.debug("")
        pt = PackageTool()
        compressed = False
        try:
            fields = {}
            _, valid, fields, package_type = self.validate_artifact(path, origin, kind)
            if not valid:
                raise Exception(
                    "{} {} Not well configured.".format(package_type.upper(), str(path))
                )
            else:
                if kind == "directory":
                    path = pt.build(path)
                    self._logger.debug(f"Directory path {path}")
                    compressed = True
                fields["checksum"] = utils.md5(path)
                self.indexation(destination, path, package_type, fields)

        except Exception as e:
            self._logger.exception(
                "Error registering package in Repository: {}".format(e)
            )
            raise ClientException(e)

        finally:
            if kind == "directory" and compressed:
                remove(path)

    def indexation(self, destination, path, package_type, fields):
        """
        Process for index packages
        :param destination: index repository path
        :param path: path of the package
        :param package_type: package type (vnf, ns, nst)
        :param fields: dict with the required values
        """
        self._logger.debug(f"Processing {destination} {path} {package_type} {fields}")

        data_ind = {
            "name": fields.get("name"),
            "description": fields.get("description"),
            "vendor": fields.get("vendor"),
            "path": fields.get("path"),
        }
        self._logger.debug(data_ind)
        final_path = join(
            destination, package_type, fields.get("id"), fields.get("version")
        )
        if isdir(join(destination, package_type, fields.get("id"))):
            if isdir(final_path):
                self._logger.warning(
                    "{} {} already exists".format(package_type.upper(), str(path))
                )
            else:
                mkdir(final_path)
                copyfile(
                    path,
                    final_path
                    + "/"
                    + fields.get("id")
                    + "-"
                    + fields.get("version")
                    + ".tar.gz",
                )
                yaml.safe_dump(
                    fields,
                    open(final_path + "/" + "metadata.yaml", "w"),
                    default_flow_style=False,
                    width=80,
                    indent=4,
                )
                index = yaml.safe_load(open(destination + "/index.yaml"))

                index["{}_packages".format(package_type)][fields.get("id")][
                    fields.get("version")
                ] = data_ind
                if versioning.parse(
                    index["{}_packages".format(package_type)][fields.get("id")][
                        "latest"
                    ]
                ) < versioning.parse(fields.get("version")):
                    index["{}_packages".format(package_type)][fields.get("id")][
                        "latest"
                    ] = fields.get("version")
                yaml.safe_dump(
                    index,
                    open(destination + "/index.yaml", "w"),
                    default_flow_style=False,
                    width=80,
                    indent=4,
                )
                self._logger.info(
                    "{} {} added in the repository".format(
                        package_type.upper(), str(path)
                    )
                )
        else:
            mkdir(destination + "/{}/".format(package_type) + fields.get("id"))
            mkdir(final_path)
            copyfile(
                path,
                final_path
                + "/"
                + fields.get("id")
                + "-"
                + fields.get("version")
                + ".tar.gz",
            )
            yaml.safe_dump(
                fields,
                open(join(final_path, "metadata.yaml"), "w"),
                default_flow_style=False,
                width=80,
                indent=4,
            )
            index = yaml.safe_load(open(destination + "/index.yaml"))

            index["{}_packages".format(package_type)][fields.get("id")] = {
                fields.get("version"): data_ind
            }
            index["{}_packages".format(package_type)][fields.get("id")]["latest"] = (
                fields.get("version")
            )
            yaml.safe_dump(
                index,
                open(join(destination, "index.yaml"), "w"),
                default_flow_style=False,
                width=80,
                indent=4,
            )
            self._logger.info(
                "{} {} added in the repository".format(package_type.upper(), str(path))
            )

    def current_datetime(self):
        """
        Datetime Generator
        :return: Datetime as string with the following structure "2020-04-29T08:41:07.681653Z"
        """
        self._logger.debug("")
        return time.strftime("%Y-%m-%dT%H:%M:%S.%sZ")

    def init_directory(self, destination):
        """
        Initialize the index directory. Creation of index.yaml, and the directories for vnf and ns
        :param destination:
        :return:
        """
        self._logger.debug("")
        if not isdir(destination):
            mkdir(destination)
        if not isfile(join(destination, "index.yaml")):
            mkdir(join(destination, "vnf"))
            mkdir(join(destination, "ns"))
            mkdir(join(destination, "nst"))
            index_data = {
                "apiVersion": "v1",
                "generated": self.current_datetime(),
                "vnf_packages": {},
                "ns_packages": {},
                "nst_packages": {},
            }
            with open(join(destination, "index.yaml"), "w") as outfile:
                yaml.safe_dump(
                    index_data, outfile, default_flow_style=False, width=80, indent=4
                )
