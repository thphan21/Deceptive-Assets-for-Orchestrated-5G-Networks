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

import os
import yaml
import hashlib


class SOLPackageException(Exception):
    pass


class SOLPackage:
    _METADATA_FILE_PATH = "TOSCA-Metadata/TOSCA.meta"
    _METADATA_DESCRIPTOR_FIELD = "Entry-Definitions"
    _METADATA_MANIFEST_FIELD = "ETSI-Entry-Manifest"
    _METADATA_CHANGELOG_FIELD = "ETSI-Entry-Change-Log"
    _METADATA_LICENSES_FIELD = "ETSI-Entry-Licenses"
    _METADATA_DEFAULT_CHANGELOG_PATH = "ChangeLog.txt"
    _METADATA_DEFAULT_LICENSES_PATH = "Licenses"
    _MANIFEST_FILE_PATH_FIELD = "Source"
    _MANIFEST_FILE_HASH_ALGORITHM_FIELD = "Algorithm"
    _MANIFEST_FILE_HASH_DIGEST_FIELD = "Hash"

    _MANIFEST_ALL_FIELDS = []

    def __init__(self, package_path=""):
        self._package_path = package_path

        self._package_metadata = self._parse_package_metadata()

        try:
            self._manifest_data = self._parse_manifest_data()
        except Exception:
            self._manifest_data = None

        try:
            self._manifest_metadata = self._parse_manifest_metadata()
        except Exception:
            self._manifest_metadata = None

    def _parse_package_metadata(self):
        try:
            return self._parse_package_metadata_with_metadata_dir()
        except FileNotFoundError:
            return self._parse_package_metadata_without_metadata_dir()

    def _parse_package_metadata_with_metadata_dir(self):
        try:
            return self._parse_file_in_blocks(self._METADATA_FILE_PATH)
        except FileNotFoundError as e:
            raise e
        except (Exception, OSError) as e:
            raise SOLPackageException(
                "Error parsing {}: {}".format(self._METADATA_FILE_PATH, e)
            )

    def _parse_package_metadata_without_metadata_dir(self):
        package_root_files = {f for f in os.listdir(self._package_path)}
        package_root_yamls = [
            f for f in package_root_files if f.endswith(".yml") or f.endswith(".yaml")
        ]
        if len(package_root_yamls) != 1:
            error_msg = "Error parsing package metadata: there should be exactly 1 descriptor YAML, found {}"
            raise SOLPackageException(error_msg.format(len(package_root_yamls)))

        base_manifest = [
            {
                SOLPackage._METADATA_DESCRIPTOR_FIELD: package_root_yamls[0],
                SOLPackage._METADATA_MANIFEST_FIELD: "{}.mf".format(
                    os.path.splitext(package_root_yamls[0])[0]
                ),
                SOLPackage._METADATA_CHANGELOG_FIELD: SOLPackage._METADATA_DEFAULT_CHANGELOG_PATH,
                SOLPackage._METADATA_LICENSES_FIELD: SOLPackage._METADATA_DEFAULT_LICENSES_PATH,
            }
        ]

        return base_manifest

    def _parse_manifest_data(self):
        manifest_path = None
        for tosca_meta in self._package_metadata:
            if SOLPackage._METADATA_MANIFEST_FIELD in tosca_meta:
                manifest_path = tosca_meta[SOLPackage._METADATA_MANIFEST_FIELD]
                break
        else:
            error_msg = "Error parsing {}: no {} field on path".format(
                self._METADATA_FILE_PATH, self._METADATA_MANIFEST_FIELD
            )
            raise SOLPackageException(error_msg)

        try:
            return self._parse_file_in_blocks(manifest_path)

        except (Exception, OSError) as e:
            raise SOLPackageException("Error parsing {}: {}".format(manifest_path, e))

    def _parse_manifest_metadata(self):
        try:
            base_manifest = {}
            manifest_file = os.open(
                os.path.join(
                    self._package_path,
                    base_manifest[SOLPackage._METADATA_MANIFEST_FIELD],
                ),
                "rw",
            )
            for line in manifest_file:
                fields_in_line = line.split(":", maxsplit=1)
                fields_in_line[0] = fields_in_line[0].strip()
                fields_in_line[1] = fields_in_line[1].strip()
                if fields_in_line[0] in self._MANIFEST_ALL_FIELDS:
                    base_manifest[fields_in_line[0]] = fields_in_line[1]
            return base_manifest
        except (Exception, OSError) as e:
            raise SOLPackageException(
                "Error parsing {}: {}".format(
                    base_manifest[SOLPackage._METADATA_MANIFEST_FIELD], e
                )
            )

    def _get_package_file_full_path(self, file_relative_path):
        return os.path.join(self._package_path, file_relative_path)

    def _parse_file_in_blocks(self, file_relative_path):
        file_path = self._get_package_file_full_path(file_relative_path)
        with open(file_path) as f:
            blocks = f.read().split("\n\n")
        parsed_blocks = map(yaml.safe_load, blocks)
        return [block for block in parsed_blocks if block is not None]

    def _get_package_file_manifest_data(self, file_relative_path):
        for file_data in self._manifest_data:
            if (
                file_data.get(SOLPackage._MANIFEST_FILE_PATH_FIELD, "")
                == file_relative_path
            ):
                return file_data

        error_msg = (
            "Error parsing {} manifest data: file not found on manifest file".format(
                file_relative_path
            )
        )
        raise SOLPackageException(error_msg)

    def get_package_file_hash_digest_from_manifest(self, file_relative_path):
        """Returns the hash digest of a file inside this package as specified on the manifest file."""
        file_manifest_data = self._get_package_file_manifest_data(file_relative_path)
        try:
            return file_manifest_data[SOLPackage._MANIFEST_FILE_HASH_DIGEST_FIELD]
        except Exception as e:
            raise SOLPackageException(
                "Error parsing {} hash digest: {}".format(file_relative_path, e)
            )

    def get_package_file_hash_algorithm_from_manifest(self, file_relative_path):
        """Returns the hash algorithm of a file inside this package as specified on the manifest file."""
        file_manifest_data = self._get_package_file_manifest_data(file_relative_path)
        try:
            return file_manifest_data[SOLPackage._MANIFEST_FILE_HASH_ALGORITHM_FIELD]
        except Exception as e:
            raise SOLPackageException(
                "Error parsing {} hash digest: {}".format(file_relative_path, e)
            )

    @staticmethod
    def _get_hash_function_from_hash_algorithm(hash_algorithm):
        function_to_algorithm = {"SHA-256": hashlib.sha256, "SHA-512": hashlib.sha512}
        if hash_algorithm not in function_to_algorithm:
            error_msg = (
                "Error checking hash function: hash algorithm {} not supported".format(
                    hash_algorithm
                )
            )
            raise SOLPackageException(error_msg)
        return function_to_algorithm[hash_algorithm]

    def _calculate_file_hash(self, file_relative_path, hash_algorithm):
        file_path = self._get_package_file_full_path(file_relative_path)
        hash_function = self._get_hash_function_from_hash_algorithm(hash_algorithm)
        try:
            with open(file_path, "rb") as f:
                return hash_function(f.read()).hexdigest()
        except Exception as e:
            raise SOLPackageException(
                "Error hashing {}: {}".format(file_relative_path, e)
            )

    def validate_package_file_hash(self, file_relative_path):
        """Validates the integrity of a file using the hash algorithm and digest on the package manifest."""
        hash_algorithm = self.get_package_file_hash_algorithm_from_manifest(
            file_relative_path
        )
        file_hash = self._calculate_file_hash(file_relative_path, hash_algorithm)
        expected_file_hash = self.get_package_file_hash_digest_from_manifest(
            file_relative_path
        )
        if file_hash != expected_file_hash:
            error_msg = "Error validating {} hash: calculated hash {} is different than manifest hash {}"
            raise SOLPackageException(
                error_msg.format(file_relative_path, file_hash, expected_file_hash)
            )

    def validate_package_hashes(self):
        """Validates the integrity of all files listed on the package manifest."""
        for file_data in self._manifest_data:
            if SOLPackage._MANIFEST_FILE_PATH_FIELD in file_data:
                file_relative_path = file_data[SOLPackage._MANIFEST_FILE_PATH_FIELD]
                self.validate_package_file_hash(file_relative_path)

    def create_or_update_metadata_file(self):
        """
        Creates or updates the metadata file with the hashes calculated for each one of the package's files
        """
        if not self._manifest_metadata:
            self.generate_manifest_data_from_descriptor()

        self.write_manifest_data_into_file()

    def generate_manifest_data_from_descriptor(self):
        pass

    def write_manifest_data_into_file(self):
        with open(self.get_manifest_location(), "w") as metadata_file:
            # Write manifest metadata
            for metadata_entry in self._manifest_metadata:
                metadata_file.write(
                    "{}: {}\n".format(
                        metadata_entry, self._manifest_metadata[metadata_entry]
                    )
                )

            # Write package's files hashes
            file_hashes = {}
            for root, dirs, files in os.walk(self._package_path):
                for a_file in files:
                    file_path = os.path.join(root, a_file)
                    file_relative_path = file_path[len(self._package_path) :]
                    if file_relative_path.startswith("/"):
                        file_relative_path = file_relative_path[1:]
                    file_hashes[file_relative_path] = self._calculate_file_hash(
                        file_relative_path, "SHA-512"
                    )

            for file, hash in file_hashes.items():
                file_block = "Source: {}\nAlgorithm: SHA-512\nHash: {}\n\n".format(
                    file, hash
                )
                metadata_file.write(file_block)

    def get_descriptor_location(self):
        """Returns this package descriptor location as a relative path from the package root."""
        for tosca_meta in self._package_metadata:
            if SOLPackage._METADATA_DESCRIPTOR_FIELD in tosca_meta:
                return tosca_meta[SOLPackage._METADATA_DESCRIPTOR_FIELD]

        error_msg = "Error: no {} entry found on {}".format(
            SOLPackage._METADATA_DESCRIPTOR_FIELD, SOLPackage._METADATA_FILE_PATH
        )
        raise SOLPackageException(error_msg)

    def get_manifest_location(self):
        """Return the VNF/NS manifest location as a relative path from the package root."""
        for tosca_meta in self._package_metadata:
            if SOLPackage._METADATA_MANIFEST_FIELD in tosca_meta:
                return tosca_meta[SOLPackage._METADATA_MANIFEST_FIELD]

        raise SOLPackageException("No manifest file defined for this package")
