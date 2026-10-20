# /bin/env python3
# Copyright 2019 ATOS
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

import glob
import logging
import os
import shutil
import subprocess
import tarfile
import time
from jinja2 import Environment, PackageLoader
from osm_im.validation import Validation as validation_im
from osm_im.validation import ValidationException
from osm_im import im_translation
from osmclient.common import package_handling as package_handling
from osmclient.common.exceptions import ClientException
from osmclient.common import utils
from .sol004_package import SOL004Package
from .sol007_package import SOL007Package
import yaml


class PackageTool(object):
    def __init__(self, client=None):
        self._client = client
        self._logger = logging.getLogger("osmclient")
        self._validator = validation_im()

    def create(
        self,
        package_type,
        base_directory,
        package_name,
        override,
        image,
        vdus,
        vcpu,
        memory,
        storage,
        interfaces,
        vendor,
        detailed,
        netslice_subnets,
        netslice_vlds,
        old,
    ):
        """
        **Create a package descriptor**

        :params:
            - package_type: [vnf, ns, nst]
            - base directory: path of destination folder
            - package_name: is the name of the package to be created
            - image: specify the image of the vdu
            - vcpu: number of virtual cpus of the vdu
            - memory: amount of memory in MB pf the vdu
            - storage: amount of storage in GB of the vdu
            - interfaces: number of interfaces besides management interface
            - vendor: vendor name of the vnf/ns
            - detailed: include all possible values for NSD, VNFD, NST
            - netslice_subnets: number of netslice_subnets for the NST
            - netslice_vlds: number of virtual link descriptors for the NST
            - old: flag to create a descriptor using the previous OSM format (pre SOL006, OSM<9)

        :return: status
        """
        self._logger.debug("")
        # print("location: {}".format(osmclient.__path__))
        file_loader = PackageLoader("osmclient")
        env = Environment(loader=file_loader, autoescape=True)
        if package_type == "ns":
            template = env.get_template("nsd.yaml.j2" if not old else "nsd_old.yaml.j2")
            content = {
                "name": package_name,
                "vendor": vendor,
                "vdus": vdus,
                "clean": False,
                "interfaces": interfaces,
                "detailed": detailed,
            }
        elif package_type == "vnf":
            template = env.get_template(
                "vnfd.yaml.j2" if not old else "vnfd_old.yaml.j2"
            )
            content = {
                "name": package_name,
                "vendor": vendor,
                "vdus": vdus,
                "clean": False,
                "interfaces": interfaces,
                "image": image,
                "vcpu": vcpu,
                "memory": memory,
                "storage": storage,
                "detailed": detailed,
            }
        elif package_type == "nst":
            # TODO: repo-index did not support nst in OSM<9, no changes in template
            template = env.get_template("nst.yaml.j2")
            content = {
                "name": package_name,
                "vendor": vendor,
                "interfaces": interfaces,
                "netslice_subnets": netslice_subnets,
                "netslice_vlds": netslice_vlds,
                "detailed": detailed,
            }
        else:
            raise ClientException(
                "Wrong descriptor type {}. Options: ns, vnf, nst".format(package_type)
            )

        self._logger.debug("To be rendered: {}".format(content))
        output = template.render(content)
        self._logger.debug(output)

        structure = self.discover_folder_structure(
            base_directory, package_name, override
        )
        if structure.get("folders"):
            self.create_folders(structure["folders"], package_type)
        if structure.get("files"):
            self.create_files(structure["files"], output, package_type)
        return "Created"

    def validate(self, base_directory, recursive=True, old_format=False):
        """
        **Validate OSM Descriptors given a path**

        :params:
            - base_directory is the root path for all descriptors

        :return: List of dict of validated descriptors. keys: type, path, valid, error
        """
        self._logger.debug("")
        table = []
        if recursive:
            descriptors_paths = [
                f for f in glob.glob(base_directory + "/**/*.yaml", recursive=recursive)
            ]
        else:
            descriptors_paths = [
                f for f in glob.glob(base_directory + "/*.yaml", recursive=recursive)
            ]
        self._logger.info("Base directory: {}".format(base_directory))
        self._logger.info(
            "{} Descriptors found to validate".format(len(descriptors_paths))
        )
        for desc_path in descriptors_paths:
            with open(desc_path) as descriptor_file:
                descriptor_data = descriptor_file.read()
            desc_type = "-"
            try:
                # TODO: refactor validation_im.yaml_validation to @staticmethod
                desc_type, descriptor_data = validation_im.yaml_validation(
                    self, descriptor_data
                )
                self._logger.debug(f"Validate {desc_type} {descriptor_data}")
                if not old_format:
                    if desc_type == "vnfd" or desc_type == "nsd":
                        self._logger.error(
                            "OSM descriptor '{}' written in an unsupported format. Please update to ETSI SOL006 format".format(
                                desc_path
                            )
                        )
                        self._logger.warning(
                            "Package validation skipped. It can still be done with 'osm package-validate --old'"
                        )
                        self._logger.warning(
                            "Package build can still be done with 'osm package-build --skip-validation'"
                        )
                        raise Exception("Not SOL006 format")
                validation_im.pyangbind_validation(self, desc_type, descriptor_data)
                table.append(
                    {"type": desc_type, "path": desc_path, "valid": "OK", "error": "-"}
                )
            except Exception as e:
                self._logger.error(f"Validation error: {e}", exc_info=True)
                table.append(
                    {
                        "type": desc_type,
                        "path": desc_path,
                        "valid": "ERROR",
                        "error": str(e),
                    }
                )
            self._logger.debug(table[-1])
        return table

    def translate(self, base_directory, recursive=True, dryrun=False):
        """
        **Translate OSM Packages given a path**

        :params:
            - base_directory is the root path for all packages

        :return: List of dict of translated packages. keys: current type, new type, path, valid, translated, error
        """
        self._logger.debug("")
        table = []
        if recursive:
            descriptors_paths = [
                f for f in glob.glob(base_directory + "/**/*.yaml", recursive=recursive)
            ]
        else:
            descriptors_paths = [
                f for f in glob.glob(base_directory + "/*.yaml", recursive=recursive)
            ]
        print("Base directory: {}".format(base_directory))
        print("{} Descriptors found to validate".format(len(descriptors_paths)))
        for desc_path in descriptors_paths:
            with open(desc_path) as descriptor_file:
                descriptor_data = descriptor_file.read()
            desc_type = "-"
            try:
                desc_type, descriptor_data = validation_im.yaml_validation(
                    self, descriptor_data
                )
                self._logger.debug("desc_type: {}".format(desc_type))
                self._logger.debug("descriptor_data:\n{}".format(descriptor_data))
                self._validator.pyangbind_validation(desc_type, descriptor_data)
                if not (desc_type == "vnfd" or desc_type == "nsd"):
                    table.append(
                        {
                            "current type": desc_type,
                            "new type": desc_type,
                            "path": desc_path,
                            "valid": "OK",
                            "translated": "N/A",
                            "error": "-",
                        }
                    )
                else:
                    new_desc_type = desc_type
                    try:
                        sol006_model = yaml.safe_dump(
                            im_translation.translate_im_model_to_sol006(
                                descriptor_data
                            ),
                            indent=4,
                            default_flow_style=False,
                        )
                        (
                            new_desc_type,
                            new_descriptor_data,
                        ) = self._validator.yaml_validation(sol006_model)
                        self._validator.pyangbind_validation(
                            new_desc_type, new_descriptor_data
                        )
                        if not dryrun:
                            with open(desc_path, "w") as descriptor_file:
                                descriptor_file.write(sol006_model)
                        table.append(
                            {
                                "current type": desc_type,
                                "new type": new_desc_type,
                                "path": desc_path,
                                "valid": "OK",
                                "translated": "OK",
                                "error": "-",
                            }
                        )
                    except ValidationException as ve2:
                        table.append(
                            {
                                "current type": desc_type,
                                "new type": new_desc_type,
                                "path": desc_path,
                                "valid": "OK",
                                "translated": "ERROR",
                                "error": "Error in the post-validation: {}".format(
                                    str(ve2)
                                ),
                            }
                        )
                    except Exception as e2:
                        table.append(
                            {
                                "current type": desc_type,
                                "new type": new_desc_type,
                                "path": desc_path,
                                "valid": "OK",
                                "translated": "ERROR",
                                "error": "Error in the translation: {}".format(str(e2)),
                            }
                        )
            except ValidationException as ve:
                table.append(
                    {
                        "current type": desc_type,
                        "new type": "N/A",
                        "path": desc_path,
                        "valid": "ERROR",
                        "translated": "N/A",
                        "error": "Error in the pre-validation: {}".format(str(ve)),
                    }
                )
            except Exception as e:
                table.append(
                    {
                        "current type": desc_type,
                        "new type": "N/A",
                        "path": desc_path,
                        "valid": "ERROR",
                        "translated": "N/A",
                        "error": str(e),
                    }
                )
        return table

    def descriptor_translate(self, descriptor_file):
        """
        **Translate input descriptor file from Rel EIGHT OSM to SOL006**

        :params:
            - base_directory is the root path for all packages

        :return: YAML descriptor in the new format
        """
        self._logger.debug("")
        with open(descriptor_file, "r") as df:
            im_model = yaml.safe_load(df.read())
        sol006_model = im_translation.translate_im_model_to_sol006(im_model)
        return yaml.safe_dump(sol006_model, indent=4, default_flow_style=False)

    def build(self, package_folder, skip_validation=False, skip_charm_build=False):
        """
        **Creates a .tar.gz file given a package_folder**

        :params:
            - package_folder: is the name of the folder to be packaged
            - skip_validation: is the flag to validate or not the descriptors on the folder before build

        :returns: message result for the build process
        """
        self._logger.debug("")
        package_folder = package_folder.rstrip("/")
        if not os.path.exists("{}".format(package_folder)):
            return "Fail, package is not in the specified path"
        if not skip_validation:
            print("Validating package {}".format(package_folder))
            results = self.validate(package_folder, recursive=False)
            if results:
                for result in results:
                    if result["valid"] != "OK":
                        raise ClientException(
                            "There was an error validating the file {} with error: {}".format(
                                result["path"], result["error"]
                            )
                        )
                print("Validation OK")
            else:
                raise ClientException(
                    "No descriptor file found in: {}".format(package_folder)
                )

        is_sol004_007 = (
            package_handling.get_package_type(package_folder)
            != package_handling.OSM_OLD
        )

        charm_list = self.build_all_charms(
            package_folder, skip_charm_build, is_sol004_007
        )
        return self.build_compressed_file(package_folder, charm_list, is_sol004_007)

    def calculate_checksum(self, package_folder):
        """
        **Function to calculate the checksum given a folder**

        :params:
            - package_folder: is the folder where we have the files to calculate the checksum
        :returns: None
        """
        self._logger.debug("")
        files = [
            f
            for f in glob.glob(package_folder + "/**/*.*", recursive=True)
            if os.path.isfile(f)
        ]
        with open("{}/checksums.txt".format(package_folder), "w+") as checksum:
            for file_item in files:
                if "checksums.txt" in file_item:
                    continue
                checksum.write("{}\t{}\n".format(utils.md5(file_item), file_item))

    def create_folders(self, folders, package_type):
        """
        **Create folder given a list of folders**

        :params:
            - folders: [List] list of folders paths to be created
            - package_type: is the type of package to be created
        :return: None
        """
        self._logger.debug("")
        for folder in folders:
            try:
                # print("Folder {} == package_type {}".format(folder[1], package_type))
                if folder[1] == package_type:
                    print("Creating folder:\t{}".format(folder[0]))
                    os.makedirs(folder[0])
            except FileExistsError:
                pass

    def save_file(self, file_name, file_body):
        """
        **Create a file given a name and the content**

        :params:
            - file_name: is the name of the file with the relative route
            - file_body: is the content of the file
        :return: None
        """
        self._logger.debug("")
        print("Creating file:  \t{}".format(file_name))
        try:
            with open(file_name, "w+") as f:
                f.write(file_body)
        except Exception as e:
            raise ClientException(e)

    def generate_readme(self):
        """
        **Creates the README content**

        :returns: readme content
        """
        self._logger.debug("")
        return """# Descriptor created by OSM descriptor package generated\n\n**Created on {} **""".format(
            time.strftime("%m/%d/%Y, %H:%M:%S", time.localtime())
        )

    def generate_cloud_init(self):
        """
        **Creates the cloud-init content**

        :returns: cloud-init content
        """
        self._logger.debug("")
        return "---\n#cloud-config"

    def create_files(self, files, file_content, package_type):
        """
        **Creates the files given the file list and type**

        :params:
            - files: is the list of files structure
            - file_content: is the content of the descriptor rendered by the template
            - package_type: is the type of package to filter the creation structure

        :return: None
        """
        self._logger.debug("")
        for file_item, file_package, file_type in files:
            if package_type == file_package:
                if file_type == "descriptor":
                    self.save_file(file_item, file_content)
                elif file_type == "readme":
                    self.save_file(file_item, self.generate_readme())
                elif file_type == "cloud_init":
                    self.save_file(file_item, self.generate_cloud_init())

    def check_files_folders(self, path_list, override):
        """
        **Find files and folders missing given a directory structure {"folders": [], "files": []}**

        :params:
            - path_list: is the list of files and folders to be created
            - override: is the flag used to indicate the creation of the list even if the file exist to override it

        :return: Missing paths Dict
        """
        self._logger.debug("")
        missing_paths = {}
        folders = []
        files = []
        for folder in path_list.get("folders"):
            if not os.path.exists(folder[0]):
                folders.append(folder)
        missing_paths["folders"] = folders

        for file_item in path_list.get("files"):
            if not os.path.exists(file_item[0]) or override is True:
                files.append(file_item)
        missing_paths["files"] = files

        return missing_paths

    def build_all_charms(self, package_folder, skip_charm_build, sol004_007=True):
        """
        **Read the descriptor file, check that the charms referenced are in the folder and compiles them**

        :params:
            - packet_folder: is the location of the package
        :return: Files and Folders not found. In case of override, it will return all file list
        """
        self._logger.debug("")
        charms_set = set()
        descriptor_file = False
        package_type = package_handling.get_package_type(package_folder)
        if sol004_007 and package_type.find("TOSCA") >= 0:
            descriptors_paths = [
                f for f in glob.glob(package_folder + "/Definitions/*.yaml")
            ]
        else:
            descriptors_paths = [f for f in glob.glob(package_folder + "/*.yaml")]
        for file in descriptors_paths:
            if file.endswith("nfd.yaml"):
                descriptor_file = True
                charms_set = self.charms_search(file, "vnf")
            if file.endswith("nsd.yaml"):
                descriptor_file = True
                charms_set = self.charms_search(file, "ns")
        print("List of charms in the descriptor: {}".format(charms_set))
        if not descriptor_file:
            raise ClientException(
                'Descriptor filename is not correct in: {}. It should end with "nfd.yaml" or "nsd.yaml"'.format(
                    package_folder
                )
            )
        if charms_set and not skip_charm_build:
            for charmName in charms_set:
                if os.path.isdir(
                    "{}/{}charms/layers/{}".format(
                        package_folder, "Scripts/" if sol004_007 else "", charmName
                    )
                ):
                    print(
                        "Building charm {}/{}charms/layers/{}".format(
                            package_folder, "Scripts/" if sol004_007 else "", charmName
                        )
                    )
                    self.charm_build(package_folder, charmName, sol004_007)
                    print("Charm built: {}".format(charmName))
                elif os.path.isdir(
                    "{}/{}charms/ops/{}".format(
                        package_folder, "Scripts/" if sol004_007 else "", charmName
                    )
                ):
                    self.charmcraft_build(package_folder, charmName)
                else:
                    if not os.path.isdir(
                        "{}/{}charms/{}".format(
                            package_folder, "Scripts/" if sol004_007 else "", charmName
                        )
                    ) and not os.path.isfile(
                        "{}/{}charms/{}".format(
                            package_folder, "Scripts/" if sol004_007 else "", charmName
                        )
                    ):
                        raise ClientException(
                            "The charm: {} referenced in the descriptor file "
                            "is not present either in {}/charms or in {}/charms/layers".format(
                                charmName, package_folder, package_folder
                            )
                        )
        self._logger.debug("Return list of charms: {}".format(charms_set))
        return charms_set

    def discover_folder_structure(self, base_directory, name, override):
        """
        **Discover files and folders structure for SOL004/SOL007 descriptors given a base_directory and name**

        :params:
            - base_directory: is the location of the package to be created
            - name: is the name of the package
            - override: is the flag used to indicate the creation of the list even if the file exist to override it
        :return: Files and Folders not found. In case of override, it will return all file list
        """
        self._logger.debug("")
        prefix = "{}/{}".format(base_directory, name)
        files_folders = {
            "folders": [
                ("{}_ns".format(prefix), "ns"),
                ("{}_ns/Licenses".format(prefix), "ns"),
                ("{}_ns/Files/icons".format(prefix), "ns"),
                ("{}_ns/Scripts/charms".format(prefix), "ns"),
                ("{}_vnf".format(name), "vnf"),
                ("{}_vnf/Licenses".format(prefix), "vnf"),
                ("{}_vnf/Scripts/charms".format(prefix), "vnf"),
                ("{}_vnf/Scripts/cloud_init".format(prefix), "vnf"),
                ("{}_vnf/Files/images".format(prefix), "vnf"),
                ("{}_vnf/Files/icons".format(prefix), "vnf"),
                ("{}_vnf/Scripts/scripts".format(prefix), "vnf"),
                ("{}_nst".format(prefix), "nst"),
                ("{}_nst/icons".format(prefix), "nst"),
            ],
            "files": [
                ("{}_ns/{}_nsd.yaml".format(prefix, name), "ns", "descriptor"),
                ("{}_ns/README.md".format(prefix), "ns", "readme"),
                ("{}_vnf/{}_vnfd.yaml".format(prefix, name), "vnf", "descriptor"),
                (
                    "{}_vnf/Scripts/cloud_init/cloud-config.txt".format(prefix),
                    "vnf",
                    "cloud_init",
                ),
                ("{}_vnf/README.md".format(prefix), "vnf", "readme"),
                ("{}_nst/{}_nst.yaml".format(prefix, name), "nst", "descriptor"),
                ("{}_nst/README.md".format(prefix), "nst", "readme"),
            ],
        }
        missing_files_folders = self.check_files_folders(files_folders, override)
        # print("Missing files and folders: {}".format(missing_files_folders))
        return missing_files_folders

    def charm_build(self, charms_folder, build_name, sol004_007=True):
        """
        Build the charms inside the package.
        params: package_folder is the name of the folder where is the charms to compile.
                build_name is the name of the layer or interface
        """
        self._logger.debug("")

        if sol004_007:
            os.environ["JUJU_REPOSITORY"] = "{}/Scripts/charms".format(charms_folder)
        else:
            os.environ["JUJU_REPOSITORY"] = "{}/charms".format(charms_folder)

        os.environ["CHARM_LAYERS_DIR"] = "{}/layers".format(
            os.environ["JUJU_REPOSITORY"]
        )
        os.environ["CHARM_INTERFACES_DIR"] = "{}/interfaces".format(
            os.environ["JUJU_REPOSITORY"]
        )

        if sol004_007:
            os.environ["CHARM_BUILD_DIR"] = "{}/Scripts/charms/builds".format(
                charms_folder
            )
        else:
            os.environ["CHARM_BUILD_DIR"] = "{}/charms/builds".format(charms_folder)

        if not os.path.exists(os.environ["CHARM_BUILD_DIR"]):
            os.makedirs(os.environ["CHARM_BUILD_DIR"])
        src_folder = "{}/{}".format(os.environ["CHARM_LAYERS_DIR"], build_name)
        result = subprocess.run(["charm", "build", "{}".format(src_folder)])
        if result.returncode == 1:
            raise ClientException("failed to build the charm: {}".format(src_folder))
        self._logger.verbose("charm {} built".format(src_folder))

    def charmcraft_build(self, package_folder, charm_name):
        """
        Build the charms inside the package (new operator framework charms)
        params: package_folder is the name of the folder where is the charms to compile.
                build_name is the name of the layer or interface
        """
        self._logger.debug("Building charm {}".format(charm_name))
        src_folder = f"{package_folder}/Scripts/charms/ops/{charm_name}"
        current_directory = os.getcwd()
        os.chdir(src_folder)
        try:
            result = subprocess.run(["charmcraft", "build"])
            if result.returncode == 1:
                raise ClientException(
                    "failed to build the charm: {}".format(src_folder)
                )
            subprocess.run(["rm", "-rf", f"../../{charm_name}"])
            subprocess.run(["mv", "build", f"../../{charm_name}"])
            self._logger.verbose("charm {} built".format(src_folder))
        finally:
            os.chdir(current_directory)

    def build_compressed_file(self, package_folder, charm_list=None, sol004_007=True):
        if sol004_007:
            return self.build_zipfile(package_folder, charm_list)
        else:
            return self.build_tarfile(package_folder, charm_list)

    def build_zipfile(self, package_folder, charm_list=None):
        """
        Creates a zip file given a package_folder
        params: package_folder is the name of the folder to be packaged
        returns: .zip name
        """
        self._logger.debug("")
        cwd = None
        try:
            directory_name, package_name = self.create_temp_dir_sol004_007(
                package_folder, charm_list
            )
            cwd = os.getcwd()
            os.chdir(directory_name)
            package_type = package_handling.get_package_type(package_folder)
            print(package_type)

            if (
                package_handling.SOL007 == package_type
                or package_handling.SOL007_TOSCA == package_type
            ):
                the_package = SOL007Package(package_folder)
            elif (
                package_handling.SOL004 == package_type
                or package_handling.SOL004_TOSCA == package_type
            ):
                the_package = SOL004Package(package_folder)
            else:
                raise ClientException(f"Unknown package type: {package_type}")

            the_package.create_or_update_metadata_file()

            the_zip_package = shutil.make_archive(
                os.path.join(cwd, package_name),
                "zip",
                os.path.join(directory_name, package_name),
            )

            print("Package created: {}".format(the_zip_package))

            return the_zip_package

        except Exception as exc:
            raise ClientException(
                "failure during build of zip file (create temp dir, calculate checksum, "
                "zip file): {}".format(exc)
            )
        finally:
            if cwd:
                os.chdir(cwd)
            shutil.rmtree(os.path.join(package_folder, "tmp"))

    def build_tarfile(self, package_folder, charm_list=None):
        """
        Creates a .tar.gz file given a package_folder
        params: package_folder is the name of the folder to be packaged
        returns: .tar.gz name
        """
        self._logger.debug("")
        cwd = None
        try:
            directory_name, package_name = self.create_temp_dir(
                package_folder, charm_list
            )
            cwd = os.getcwd()
            os.chdir(directory_name)
            self.calculate_checksum(package_name)
            with tarfile.open("{}.tar.gz".format(package_name), mode="w:gz") as archive:
                print("Adding File: {}".format(package_name))
                archive.add("{}".format(package_name), recursive=True)
            # return "Created {}.tar.gz".format(package_folder)
            # self.build("{}".format(os.path.basename(package_folder)))
            os.chdir(cwd)
            cwd = None
            created_package = "{}/{}.tar.gz".format(
                os.path.dirname(package_folder) or ".", package_name
            )
            os.rename(
                "{}/{}.tar.gz".format(directory_name, package_name), created_package
            )
            os.rename(
                "{}/{}/checksums.txt".format(directory_name, package_name),
                "{}/checksums.txt".format(package_folder),
            )
            print("Package created: {}".format(created_package))
            return created_package
        except Exception as exc:
            raise ClientException(
                "failure during build of targz file (create temp dir, calculate checksum, "
                "tar.gz file): {}".format(exc)
            )
        finally:
            if cwd:
                os.chdir(cwd)
            shutil.rmtree(os.path.join(package_folder, "tmp"))

    def create_temp_dir(self, package_folder, charm_list=None):
        """
        Method to create a temporary folder where we can move the files in package_folder
        """
        self._logger.debug("")
        ignore_patterns = ".gitignore"
        ignore = shutil.ignore_patterns(ignore_patterns)
        directory_name = os.path.abspath(package_folder)
        package_name = os.path.basename(directory_name)
        directory_name += "/tmp"
        os.makedirs("{}/{}".format(directory_name, package_name), exist_ok=True)
        self._logger.debug("Makedirs DONE: {}/{}".format(directory_name, package_name))
        for item in os.listdir(package_folder):
            self._logger.debug("Item: {}".format(item))
            if item != "tmp":
                s = os.path.join(package_folder, item)
                d = os.path.join(os.path.join(directory_name, package_name), item)
                if os.path.isdir(s):
                    if item == "charms":
                        os.makedirs(d, exist_ok=True)
                        s_builds = os.path.join(s, "builds")
                        for charm in charm_list:
                            self._logger.debug("Copying charm {}".format(charm))
                            if charm in os.listdir(s):
                                s_charm = os.path.join(s, charm)
                            elif charm in os.listdir(s_builds):
                                s_charm = os.path.join(s_builds, charm)
                            else:
                                raise ClientException(
                                    "The charm {} referenced in the descriptor file "
                                    "could not be found in {}/charms or in {}/charms/builds".format(
                                        charm, package_folder, package_folder
                                    )
                                )
                            d_temp = os.path.join(d, charm)
                            self._logger.debug(
                                "Copying tree: {} -> {}".format(s_charm, d_temp)
                            )
                            if os.path.isdir(s_charm):
                                shutil.copytree(
                                    s_charm, d_temp, symlinks=True, ignore=ignore
                                )
                            else:
                                shutil.copy2(s_charm, d_temp)
                            self._logger.debug("DONE")
                    else:
                        self._logger.debug("Copying tree: {} -> {}".format(s, d))
                        shutil.copytree(s, d, symlinks=True, ignore=ignore)
                        self._logger.debug("DONE")
                else:
                    if item in ignore_patterns:
                        continue
                    self._logger.debug("Copying file: {} -> {}".format(s, d))
                    shutil.copy2(s, d)
                    self._logger.debug("DONE")
        return directory_name, package_name

    def copy_tree(self, s, d, ignore):
        self._logger.debug("Copying tree: {} -> {}".format(s, d))
        shutil.copytree(s, d, symlinks=True, ignore=ignore)
        self._logger.debug("DONE")

    def create_temp_dir_sol004_007(self, package_folder, charm_list=None):
        """
        Method to create a temporary folder where we can move the files in package_folder
        """
        self._logger.debug("")
        ignore_patterns = ".gitignore"
        ignore = shutil.ignore_patterns(ignore_patterns)
        directory_name = os.path.abspath(package_folder)
        package_name = os.path.basename(directory_name)
        directory_name += "/tmp"
        os.makedirs("{}/{}".format(directory_name, package_name), exist_ok=True)
        self._logger.debug("Makedirs DONE: {}/{}".format(directory_name, package_name))
        for item in os.listdir(package_folder):
            self._logger.debug("Item: {}".format(item))
            if item != "tmp":
                s = os.path.join(package_folder, item)
                d = os.path.join(os.path.join(directory_name, package_name), item)
                if os.path.isdir(s):
                    if item == "Scripts":
                        os.makedirs(d, exist_ok=True)
                        scripts_folder = s
                        for script_item in os.listdir(scripts_folder):
                            scripts_destination_folder = os.path.join(d, script_item)
                            if script_item == "charms":
                                s_builds = os.path.join(
                                    scripts_folder, script_item, "builds"
                                )
                                for charm in charm_list:
                                    self._logger.debug("Copying charm {}".format(charm))
                                    if charm in os.listdir(
                                        os.path.join(scripts_folder, script_item)
                                    ):
                                        s_charm = os.path.join(
                                            scripts_folder, script_item, charm
                                        )
                                    elif charm in os.listdir(s_builds):
                                        s_charm = os.path.join(s_builds, charm)
                                    else:
                                        raise ClientException(
                                            "The charm {} referenced in the descriptor file "
                                            "could not be found in {}/charms or in {}/charms/builds".format(
                                                charm, package_folder, package_folder
                                            )
                                        )
                                    d_temp = os.path.join(
                                        scripts_destination_folder, charm
                                    )
                                    self.copy_tree(s_charm, d_temp, ignore)
                            else:
                                self.copy_tree(
                                    os.path.join(scripts_folder, script_item),
                                    scripts_destination_folder,
                                    ignore,
                                )
                    else:
                        self.copy_tree(s, d, ignore)
                else:
                    if item in ignore_patterns:
                        continue
                    self._logger.debug("Copying file: {} -> {}".format(s, d))
                    shutil.copy2(s, d)
                    self._logger.debug("DONE")
        return directory_name, package_name

    def charms_search(self, descriptor_file, desc_type):
        self._logger.debug(
            "descriptor_file: {}, desc_type: {}".format(descriptor_file, desc_type)
        )
        charms_set = set()
        with open("{}".format(descriptor_file)) as yaml_desc:
            descriptor_dict = yaml.safe_load(yaml_desc)
            # self._logger.debug("\n"+yaml.safe_dump(descriptor_dict, indent=4, default_flow_style=False))

            if (
                desc_type == "vnf"
                and (
                    "vnfd:vnfd-catalog" in descriptor_dict
                    or "vnfd-catalog" in descriptor_dict
                )
            ) or (
                desc_type == "ns"
                and (
                    "nsd:nsd-catalog" in descriptor_dict
                    or "nsd-catalog" in descriptor_dict
                )
            ):
                charms_set = self._charms_search_on_osm_im_dict(
                    descriptor_dict, desc_type
                )
            else:
                if desc_type == "ns":
                    get_charm_list = self._charms_search_on_nsd_sol006_dict
                elif desc_type == "vnf":
                    get_charm_list = self._charms_search_on_vnfd_sol006_dict
                else:
                    raise Exception("Bad descriptor type")
                charms_set = get_charm_list(descriptor_dict)
        return charms_set

    def _charms_search_on_osm_im_dict(self, osm_im_dict, desc_type):
        self._logger.debug("")
        charms_set = set()
        for k1, v1 in osm_im_dict.items():
            for k2, v2 in v1.items():
                for entry in v2:
                    if "{}-configuration".format(desc_type) in entry:
                        vnf_config = entry["{}-configuration".format(desc_type)]
                        for k3, v3 in vnf_config.items():
                            if "charm" in v3:
                                charms_set.add((v3["charm"]))
                    if "vdu" in entry:
                        vdus = entry["vdu"]
                        for vdu in vdus:
                            if "vdu-configuration" in vdu:
                                for k4, v4 in vdu["vdu-configuration"].items():
                                    if "charm" in v4:
                                        charms_set.add((v4["charm"]))
        return charms_set

    def _charms_search_on_vnfd_sol006_dict(self, sol006_dict):
        self._logger.debug("")
        charms_set = set()
        dfs = sol006_dict.get("vnfd", {}).get("df", [])
        for df in dfs:
            day_1_2s = (
                df.get("lcm-operations-configuration", {})
                .get("operate-vnf-op-config", {})
                .get("day1-2")
            )
            if day_1_2s is not None:
                for day_1_2 in day_1_2s:
                    exec_env_list = day_1_2.get("execution-environment-list", [])
                    for exec_env in exec_env_list:
                        if "juju" in exec_env and "charm" in exec_env["juju"]:
                            charms_set.add(exec_env["juju"]["charm"])
        return charms_set

    def _charms_search_on_nsd_sol006_dict(self, sol006_dict):
        self._logger.debug("")
        charms_set = set()
        nsd_list = sol006_dict.get("nsd", {}).get("nsd", [])
        for nsd in nsd_list:
            charm = nsd.get("ns-configuration", {}).get("juju", {}).get("charm")
            if charm:
                charms_set.add(charm)
        return charms_set
