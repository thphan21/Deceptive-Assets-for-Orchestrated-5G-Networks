# -*- coding: utf-8 -*-

# Copyright 2020 Whitestack, LLC
# *************************************************************
#
# This file is part of OSM common repository.
# All Rights Reserved to Whitestack, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# For those usages not covered by the Apache License, Version 2.0 please
# contact: agarcia@whitestack.com
##

from osm_im.validation import Validation, ValidationException


class TranslationException(Exception):
    pass


# ******************** Translation public functions ********************

def translate_im_model_to_sol006(im_model_data):
    _validate_im_model(im_model_data)
    descriptor_type = _get_im_model_descriptor_type(im_model_data)
    if descriptor_type == "vnfd":
        return translate_im_vnfd_to_sol006(im_model_data)
    if descriptor_type == "nsd":
        return translate_im_nsd_to_sol006(im_model_data)
    # For sanity, should not happen
    raise TranslationException("Error in translation: cannot determine the type of OSM-IM descriptor. Found {}, "
                               "expected one of: vnfd:vnfd-catalog, vnfd-catalog, nsd:nsd-catalog, nsd-catalog."
                               .format(descriptor_type))


def translate_im_vnfd_to_sol006(im_vnfd):
    im_vnfd = _remove_im_vnfd_envelope(im_vnfd)
    sol006_vnfd = {}
    _add_im_vnfd_basic_data_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_vnfd_mgmt_interface_cp_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_vdu_flavors_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_vdu_guest_epa_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_vdu_images_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_vdus_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_internal_vlds_to_sol006_vfnd(im_vnfd, sol006_vnfd)
    _add_im_vnf_configuration_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_ip_profiles_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_vdu_monitoring_params_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_scaling_group_descriptors_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_kdus_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_k8s_clusters_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _add_im_placement_groups_to_sol006_vnfd(im_vnfd, sol006_vnfd)
    _cleanup_juju_in_configurations(sol006_vnfd)
    return {"vnfd": sol006_vnfd}


def translate_im_nsd_to_sol006(im_nsd):
    im_nsd = _remove_im_nsd_envelope(im_nsd)
    sol006_nsd = {}
    _add_im_nsd_basic_data_to_sol006_nsd(im_nsd, sol006_nsd)
    _add_im_constituent_vnfds_to_sol006_nsd(im_nsd, sol006_nsd)
    _add_im_vlds_to_sol006_nsd(im_nsd, sol006_nsd)
    return {"nsd": {"nsd": [sol006_nsd]}}


# ******************** Common translation private functions ********************

def _validate_im_model(im_model_data):
    descriptor_type = _get_im_model_descriptor_type(im_model_data)
    try:
        Validation().pyangbind_validation(descriptor_type, im_model_data)
    except ValidationException as e:
        raise TranslationException("Error on input model validation: {}".format(str(e)))


def _get_im_model_descriptor_type(im_model_data):
    data_root = list(im_model_data.keys())[0]
    if "vnfd" in data_root:
        return "vnfd"
    if "nsd" in data_root:
        return "nsd"
    raise TranslationException("Error in translation: cannot determine the type of OSM-IM descriptor. Found {}, "
                               "expected one of: vnfd:vnfd-catalog, vnfd-catalog, nsd:nsd-catalog, nsd-catalog."
                               .format(data_root))


# ******************** VNFD translation private functions ********************

def _remove_im_vnfd_envelope(im_vnfd):
    # Data is wrapped as { vnfd-catalog: { vnfd: [ <data> ] } }
    return list(im_vnfd.values())[0]["vnfd"][0]


def _add_im_vnfd_basic_data_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    sol006_vnfd["id"] = im_vnfd["id"]
    if im_vnfd.get("name"):
        sol006_vnfd["product-name"] = im_vnfd["name"]
    if im_vnfd.get("description"):
        sol006_vnfd["description"] = im_vnfd["description"]
    if im_vnfd.get("vendor"):
        sol006_vnfd["provider"] = im_vnfd["vendor"]
    if im_vnfd.get("version"):
        sol006_vnfd["version"] = im_vnfd["version"]


def _add_im_vnfd_mgmt_interface_cp_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    sol006_vnfd["mgmt-cp"] = "{}-ext".format(im_vnfd["mgmt-interface"]["cp"])


def _add_im_vdu_flavors_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    storage_descriptors = []
    compute_descriptors = []
    for vdu in im_vnfd.get("vdu", ()):
        vdu_id = vdu.get("id")
        vdu_flavor = vdu.get("vm-flavor")
        if not vdu_flavor:
            continue
        storage_descriptor = {"id": "{}-storage".format(vdu_id)}
        compute_descriptor = {"id": "{}-compute".format(vdu_id)}
        if vdu_flavor.get("storage-gb"):
            storage_descriptor["size-of-storage"] = int(vdu_flavor["storage-gb"])
            storage_descriptors.append(storage_descriptor)
        if vdu_flavor.get("vcpu-count"):
            compute_descriptor["virtual-cpu"] = {"num-virtual-cpu": int(vdu_flavor["vcpu-count"])}
        if vdu_flavor.get("memory-mb"):
            compute_descriptor["virtual-memory"] = {"size": float(vdu_flavor["memory-mb"]) / 1024.0}
        if len(compute_descriptor) > 1:
            compute_descriptors.append(compute_descriptor)
    if len(storage_descriptors) > 0:
        sol006_vnfd["virtual-storage-desc"] = storage_descriptors
    if len(compute_descriptors) > 0:
        sol006_vnfd["virtual-compute-desc"] = compute_descriptors


def _add_im_vdu_guest_epa_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    for vdu in im_vnfd.get("vdu", ()):
        vdu_guest_epa = vdu.get("guest-epa")
        if not vdu_guest_epa:
            continue

        _add_im_vdu_guest_epa_memory_and_cpu_to_sol006_vnfd(vdu, sol006_vnfd)
        _add_im_vdu_guest_epa_disk_io_to_sol006_vnfd(vdu, sol006_vnfd)


def _add_im_vdu_guest_epa_memory_and_cpu_to_sol006_vnfd(im_vdu, sol006_vnfd):
    vdu_guest_epa = im_vdu.get("guest-epa")
    virtual_memory = _get_virtual_memory_from_im_vdu_guest_epa(vdu_guest_epa)
    virtual_cpu = _get_virtual_cpu_from_im_vdu_guest_epa(vdu_guest_epa)
    # Find this vdu compute descriptor and update it with the EPA options. If the
    # vdu compute descriptor does not exist, create one with the EPA options only.
    compute_descriptor_id = "{}-compute".format(im_vdu["id"])
    compute_descriptor = {"id": compute_descriptor_id}
    compute_descriptor_found = False
    for vcd in sol006_vnfd.get("virtual-compute-desc", ()):
        if vcd.get("id") == compute_descriptor_id:
            compute_descriptor = vcd
            compute_descriptor_found = True

    compute_descriptor_virtual_memory = compute_descriptor.get("virtual-memory", {})
    compute_descriptor_virtual_cpu = compute_descriptor.get("virtual-cpu", {})
    compute_descriptor_virtual_memory.update(virtual_memory)
    compute_descriptor_virtual_cpu.update(virtual_cpu)
    if compute_descriptor_virtual_memory:
        compute_descriptor["virtual-memory"] = compute_descriptor_virtual_memory
    if compute_descriptor_virtual_cpu:
        compute_descriptor["virtual-cpu"] = compute_descriptor_virtual_cpu

    if not compute_descriptor_found:
        if sol006_vnfd.get("virtual-compute-desc"):
            sol006_vnfd["virtual-compute-desc"].append(compute_descriptor)
        else:
            sol006_vnfd["virtual-compute-desc"] = [compute_descriptor]


def _add_im_vdu_guest_epa_disk_io_to_sol006_vnfd(im_vdu, sol006_vnfd):
    vdu_guest_epa = im_vdu.get("guest-epa")
    disk_io_quota = vdu_guest_epa.get("disk-io-quota", {})
    if not disk_io_quota:
        return
    # Find this vdu storage descriptor and update it with the EPA options. If the
    # vdu storage descriptor does not exist, create one with the EPA options only.
    storage_descriptor_id = "{}-storage".format(im_vdu["id"])
    storage_descriptor = {"id": storage_descriptor_id}
    storage_descriptor_found = False
    for vsd in sol006_vnfd.get("virtual-storage-desc", ()):
        if vsd.get("id") == storage_descriptor_id:
            storage_descriptor = vsd
            storage_descriptor_found = True

    storage_descriptor["disk-io-quota"] = disk_io_quota
    if not storage_descriptor_found:
        if sol006_vnfd.get("virtual-storage-desc"):
            sol006_vnfd["virtual-storage-desc"].append(storage_descriptor)
        else:
            sol006_vnfd["virtual-storage-desc"] = [storage_descriptor]


def _get_virtual_memory_from_im_vdu_guest_epa(im_vdu_guest_epa):
    virtual_memory = {}
    if im_vdu_guest_epa.get("mempage-size"):
        virtual_memory["mempage-size"] = im_vdu_guest_epa["mempage-size"]
    if im_vdu_guest_epa.get("numa-node-policy"):
        virtual_memory["numa-enabled"] = True
        virtual_memory["numa-node-policy"] = im_vdu_guest_epa["numa-node-policy"]
    if im_vdu_guest_epa.get("mem-quota"):
        virtual_memory["mem-quota"] = im_vdu_guest_epa["mem-quota"]
    return virtual_memory


def _get_virtual_cpu_from_im_vdu_guest_epa(im_vdu_guest_epa):
    virtual_cpu = {}
    if im_vdu_guest_epa.get("cpu-pinning-policy") or im_vdu_guest_epa.get("cpu-thread-pinning-policy"):
        virtual_cpu["pinning"] = {}
        if im_vdu_guest_epa.get("cpu-pinning-policy"):
            if im_vdu_guest_epa["cpu-pinning-policy"] == "SHARED":
                virtual_cpu["pinning"]["policy"] = "dynamic"
            else:
                virtual_cpu["pinning"]["policy"] = "static"
        if im_vdu_guest_epa.get("cpu-thread-pinning-policy"):
            virtual_cpu["pinning"]["thread-policy"] = im_vdu_guest_epa["cpu-thread-pinning-policy"]
    if im_vdu_guest_epa.get("cpu-quota"):
        virtual_cpu["cpu-quota"] = im_vdu_guest_epa["cpu-quota"]
    return virtual_cpu


def _add_im_vdu_images_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    image_descriptors = []
    all_images = set()  # To avoid duplicated images
    for vdu in im_vnfd.get("vdu", ()):
        vdu_image = vdu.get("image")
        if vdu_image and vdu_image not in all_images:
            image_descriptors.append({"id": vdu_image, "name": vdu_image, "image": vdu_image})
            all_images.add(vdu_image)
        for alternative_image in vdu.get("alternative-images", ()):
            alt_image = alternative_image.get("image")
            alt_image_descriptor = {"id": alt_image, "name": alt_image, "image": alt_image}
            if alternative_image.get("vim-type"):
                alt_image_descriptor["vim-type"] = alternative_image["vim-type"]
            if alt_image not in all_images:
                image_descriptors.append(alt_image_descriptor)
                all_images.add(alt_image)

    if len(image_descriptors) > 0:
        sol006_vnfd["sw-image-desc"] = image_descriptors


def _add_im_vdus_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    vdus = []
    ext_cpds = []
    vdu_configurations = []
    df_instantiation_level = {"id": "default-instantiation-level", "vdu-level": []}
    df = {"id": "default-df", "vdu-profile": [], "instantiation-level": [df_instantiation_level]}
    for vdu in im_vnfd.get("vdu", ()):
        vdu_descriptor = {"id": vdu["id"]}
        if vdu.get("description"):
            vdu_descriptor["description"] = vdu["description"]
        if vdu.get("name"):
            vdu_descriptor["name"] = vdu["name"]
        if vdu.get("cloud-init-file"):
            vdu_descriptor["cloud-init-file"] = vdu["cloud-init-file"]
        if vdu.get("cloud-init"):
            vdu_descriptor["cloud-init"] = vdu["cloud-init"]
        if vdu.get("supplemental-boot-data"):
            vdu_descriptor["supplemental-boot-data"] = vdu["supplemental-boot-data"]
        if vdu.get("alarm"):
            vdu_descriptor["alarm"] = vdu["alarm"]
        if vdu.get("pdu-type"):
            vdu_descriptor["pdu-type"] = vdu["pdu-type"]

        _add_im_vdu_images_to_sol006_vdu(vdu, vdu_descriptor)
        _add_im_vdu_flavor_to_sol006_vdu(vdu, vdu_descriptor)

        vdu_int_cpds, vdu_ext_cpds = _get_int_and_ext_cpds_from_im_vdu(vdu, im_vnfd)
        vdu_descriptor["int-cpd"] = vdu_int_cpds
        ext_cpds.extend(vdu_ext_cpds)

        vdu_profile = _get_vdu_profile_from_im_vdu(vdu, im_vnfd)
        vdu_level = _get_instantiation_level_vdu_level_from_im_vdu(vdu)
        if vdu.get("vdu-configuration"):
            vdu_configuration = vdu["vdu-configuration"]
            vdu_configuration["id"] = vdu["id"]
            vdu_configurations.append(vdu_configuration)
        df["vdu-profile"].append(vdu_profile)
        df["instantiation-level"][0]["vdu-level"].append(vdu_level)

        vdus.append(vdu_descriptor)

    if len(vdus) > 0:
        sol006_vnfd["vdu"] = vdus
        sol006_vnfd["df"] = [df]
    if len(ext_cpds) > 0:
        sol006_vnfd["ext-cpd"] = ext_cpds
    if len(vdu_configurations) > 0:
        _prepare_dict_entries_for_configurations(sol006_vnfd)
        sol006_vnfd["df"][0]["lcm-operations-configuration"]["operate-vnf-op-config"]["day1-2"].extend(vdu_configurations)


def _add_im_vdu_images_to_sol006_vdu(im_vdu, sol006_vdu):
    if im_vdu.get("image"):
        sol006_vdu["sw-image-desc"] = im_vdu["image"]
    alternative_images = []
    for alternative_image in im_vdu.get("alternative-images", ()):
        alternative_images.append(alternative_image.get("image"))
    if len(alternative_images) > 0:
        sol006_vdu["alternative-sw-image-desc"] = alternative_images


def _add_im_vdu_flavor_to_sol006_vdu(im_vdu, sol006_vdu):
    vdu_flavor = im_vdu.get("vm-flavor")
    if vdu_flavor:
        if vdu_flavor.get("vcpu-count") or vdu_flavor.get("memory-mb"):
            sol006_vdu["virtual-compute-desc"] = "{}-compute".format(im_vdu["id"])
        if vdu_flavor.get("storage-gb"):
            sol006_vdu["virtual-storage-desc"] = ["{}-storage".format(im_vdu["id"])]


def _get_int_and_ext_cpds_from_im_vdu(im_vdu, im_vnfd):
    int_cpds = []
    ext_cpds = []
    for interface in im_vdu.get("interface", ()):
        int_cpd = {"id": "{}-int".format(interface["name"])}
        virtual_network_interface_requirement = {"name": interface["name"]}
        if interface.get("virtual-interface"):
            virtual_network_interface_requirement["virtual-interface"] = interface["virtual-interface"]
        if "position" in interface:
            virtual_network_interface_requirement["position"] = int(interface["position"])
        int_cpd["virtual-network-interface-requirement"] = [virtual_network_interface_requirement]
        if interface.get("external-connection-point-ref"):
            ext_cpd = {
                "id": "{}-ext".format(interface["external-connection-point-ref"]),
                "int-cpd": {
                    "vdu-id": im_vdu["id"],
                    "cpd": int_cpd["id"]
                }
            }
            for cp in im_vnfd.get("connection-point", ()):
                if cp.get("name", "") != interface["external-connection-point-ref"]:
                    continue
                if "port-security-enabled" in cp:
                    ext_cpd["port-security-enabled"] = cp["port-security-enabled"]
                if cp.get("port-security-disable-strategy"):
                    ext_cpd["port-security-disable-strategy"] = cp["port-security-disable-strategy"]
            ext_cpds.append(ext_cpd)

        int_cpds.append(int_cpd)

    return int_cpds, ext_cpds


def _get_vdu_profile_from_im_vdu(im_vdu, im_vnfd):
    vdu_profile = {"id": im_vdu["id"]}
    initial_instances = int(im_vdu.get("count", 1))
    vdu_profile["min-number-of-instances"] = initial_instances
    for scaling_group_descriptor in im_vnfd.get("scaling-group-descriptor", ()):
        for sgd_vdu in scaling_group_descriptor.get("vdu", []):
            if sgd_vdu.get("vdu-id-ref") == im_vdu["id"]:
                sgd_max_instances = int(scaling_group_descriptor.get("max-instance-count", 1))
                sgd_min_instances = int(scaling_group_descriptor.get("min-instance-count", 0))
                vdu_profile["min-number-of-instances"] = sgd_min_instances + initial_instances
                vdu_profile["max-number-of-instances"] = sgd_max_instances + initial_instances
    return vdu_profile


def _get_instantiation_level_vdu_level_from_im_vdu(im_vdu):
    vdu_level = {"vdu-id": im_vdu["id"]}
    vdu_level["number-of-instances"] = int(im_vdu.get("count", 1))
    return vdu_level


def _add_im_internal_vlds_to_sol006_vfnd(im_vnfd, sol006_vnfd):
    int_virtual_link_descs = []
    for ivld in im_vnfd.get("internal-vld", ()):
        int_virtual_link_desc = {"id": ivld["id"]}
        _add_im_internal_vld_connection_point_refs_to_sol006_vnfd(ivld, im_vnfd, sol006_vnfd)

        int_virtual_link_descs.append(int_virtual_link_desc)

    if len(int_virtual_link_descs) > 0:
        sol006_vnfd["int-virtual-link-desc"] = int_virtual_link_descs


def _add_im_internal_vld_connection_point_refs_to_sol006_vnfd(ivld, im_vnfd, sol006_vnfd):
    all_int_cp_refs_interfaces = {}
    for vdu in im_vnfd.get("vdu", ()):
        for interface in vdu.get("interface", ()):
            int_cp_ref = interface.get("internal-connection-point-ref")
            if not int_cp_ref:
                continue
            all_int_cp_refs_interfaces[int_cp_ref] = (vdu["id"], interface["name"])

    for int_cp in ivld.get("internal-connection-point", ()):
        int_cp_ref = int_cp["id-ref"]
        (vdu_id, interface_name) = all_int_cp_refs_interfaces[int_cp_ref]
        sol006_int_cpd_id = "{}-int".format(interface_name)
        # Search for this int_cp on sol006_vnfd and update it
        for vdu in sol006_vnfd.get("vdu", ()):
            if vdu["id"] != vdu_id:
                continue
            for int_cpd in vdu.get("int-cpd", ()):
                if int_cpd["id"] == sol006_int_cpd_id:
                    int_cpd["int-virtual-link-desc"] = ivld["id"]

def _prepare_dict_entries_for_configurations(sol006_vnfd):
    sol006_vnfd["df"] = sol006_vnfd.get("df", [{}])
    if not sol006_vnfd["df"][0].get("lcm-operations-configuration"):
        sol006_vnfd["df"][0]["lcm-operations-configuration"] = {
            "operate-vnf-op-config": {
                "day1-2": []
            }
        }

def _cleanup_juju_in_configurations(sol006_vnfd):
    configs = sol006_vnfd["df"][0].get("lcm-operations-configuration")
    if configs:
        for day12_config in configs["operate-vnf-op-config"]["day1-2"]:
            if "juju" in day12_config:
                ee_name = _create_execution_environment_for_juju(day12_config, day12_config["juju"]["charm"])
                for primitive in day12_config.get("config-primitive", []):
                    primitive["execution-environment-ref"] = ee_name
                for primitive in day12_config.get("initial-config-primitive", []):
                    primitive["execution-environment-ref"] = ee_name
                for primitive in day12_config.get("terminate-config-primitive", []):
                    primitive["execution-environment-ref"] = ee_name
                day12_config.pop("juju", None)

def _create_execution_environment_for_juju(day12_config, charm_name):
    if not "execution-environment-list" in day12_config:
        day12_config["execution-environment-list"] = []

    day12_config["execution-environment-list"].append(
        {
            "id": charm_name + "-ee",
            "juju": {
                "charm": charm_name
            }
        }
    )

    return charm_name + "-ee"

def _add_im_vnf_configuration_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    vnf_configuration = im_vnfd.get("vnf-configuration")
    if not vnf_configuration:
        return
    vnf_configuration["id"] = im_vnfd.get("id")
    _prepare_dict_entries_for_configurations(sol006_vnfd)
    sol006_vnfd["df"][0]["lcm-operations-configuration"]["operate-vnf-op-config"]["day1-2"].append(vnf_configuration)


def _add_im_ip_profiles_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    all_ivlds_ip_profiles = {}
    for ivld in im_vnfd.get("internal-vld", ()):
        if ivld.get("ip-profile-ref"):
            all_ivlds_ip_profiles[ivld["ip-profile-ref"]] = ivld["id"]

    virtual_link_profiles = []
    for ip_profile in im_vnfd.get("ip-profiles", ()):
        virtual_link_profile = {"id": all_ivlds_ip_profiles[ip_profile["name"]], "flavour": ""}
        ip_profile_params = ip_profile.get("ip-profile-params")
        if ip_profile_params:
            l3_protocol_data = {"name": "{}-l3-protocol-data".format(virtual_link_profile["id"])}
            if ip_profile_params.get("ip-version"):
                l3_protocol_data["ip-version"] = ip_profile_params["ip-version"]
            if ip_profile_params.get("subnet-address"):
                l3_protocol_data["cidr"] = ip_profile_params["subnet-address"]
            if ip_profile_params.get("gateway-address"):
                l3_protocol_data["gateway-ip"] = ip_profile_params["gateway-address"]
            if ip_profile_params.get("security-group"):
                l3_protocol_data["security-group"] = ip_profile_params["security-group"]
            if ip_profile_params.get("dhcp-params", {}).get("enabled"):
                l3_protocol_data["dhcp-enabled"] = ip_profile_params["dhcp-params"]["enabled"]
            if ip_profile.get("description"):
                l3_protocol_data["description"] = ip_profile["description"]

            virtual_link_profile["virtual-link-protocol-data"] = {"l3-protocol-data": l3_protocol_data}

        virtual_link_profiles.append(virtual_link_profile)

    if len(virtual_link_profiles) > 0:
        sol006_vnfd["df"][0]["virtual-link-profile"] = virtual_link_profiles


def _add_im_vdu_monitoring_params_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    all_vdu_monitoring_param_metrics = {}
    for vdu in im_vnfd.get("vdu", ()):
        for monitoring_param in vdu.get("monitoring-param", ()):
            monitoring_param_metric = monitoring_param.get("nfvi-metric")
            if monitoring_param_metric:
                all_vdu_monitoring_param_metrics[(vdu["id"], monitoring_param["id"])] = monitoring_param_metric

    for monitoring_param in im_vnfd.get("monitoring-param", ()):
        sol006_mp = {"id": monitoring_param["id"]}
        if monitoring_param.get("name"):
            sol006_mp["name"] = monitoring_param["name"]
        if monitoring_param.get("vdu-monitoring-param"):
            monitoring_param_vdu_id = monitoring_param["vdu-monitoring-param"].get("vdu-ref")
            monitoring_param_id = monitoring_param["vdu-monitoring-param"].get("vdu-monitoring-param-ref")
            metric = all_vdu_monitoring_param_metrics.get((monitoring_param_vdu_id, monitoring_param_id))
            if metric:
                sol006_mp["performance-metric"] = metric
            # Find that vdu inside sol006_vnfd and update its monitoring-parameter list
            for vdu in sol006_vnfd.get("vdu", ()):
                if vdu["id"] != monitoring_param_vdu_id:
                    continue
                if vdu.get("monitoring-parameter"):
                    vdu["monitoring-parameter"].append(sol006_mp)
                else:
                    vdu["monitoring-parameter"] = [sol006_mp]


def _add_im_scaling_group_descriptors_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    scaling_aspects = []
    for scaling_group_descriptor in im_vnfd.get("scaling-group-descriptor", ()):
        scaling_aspect = {"id": scaling_group_descriptor["name"], "name": scaling_group_descriptor["name"]}
        if scaling_group_descriptor.get("max-instance-count"):
            scaling_aspect["max-scale-level"] = int(scaling_group_descriptor["max-instance-count"])
        if scaling_group_descriptor.get("scaling-policy"):
            scaling_aspect["scaling-policy"] = scaling_group_descriptor["scaling-policy"]
        if scaling_group_descriptor.get("scaling-config-action"):
            scaling_aspect["scaling-config-action"] = scaling_group_descriptor["scaling-config-action"]

        delta = {"id": "{}-delta".format(scaling_aspect["id"])}
        vdu_deltas = []
        for vdu in scaling_group_descriptor.get("vdu", ()):
            vdu_delta = {}
            if vdu.get("count"):
                vdu_delta["number-of-instances"] = int(vdu["count"])
            if vdu.get("vdu-id-ref"):
                vdu_delta["id"] = vdu["vdu-id-ref"]
            vdu_deltas.append(vdu_delta)
        if len(vdu_deltas) > 0:
            delta["vdu-delta"] = vdu_deltas
        scaling_aspect["aspect-delta-details"] = {"deltas": [delta]}

        scaling_aspects.append(scaling_aspect)

    if len(scaling_aspects) > 0:
        sol006_vnfd["df"][0]["scaling-aspect"] = scaling_aspects


def _add_im_kdus_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    if im_vnfd.get("kdu"):
        sol006_vnfd["kdu"] = im_vnfd["kdu"]
        kdu_configs = []
        for a_kdu in sol006_vnfd["kdu"]:
            if "kdu-configuration" in a_kdu:
                kdu_config = a_kdu.pop("kdu-configuration")
                kdu_config["id"] = a_kdu["name"]
                kdu_configs.append(kdu_config)
        if len(sol006_vnfd.get("df", ())) == 0:
            sol006_vnfd["df"] = [{"id": "default-df"}]
        if len(kdu_configs) > 0:
            _prepare_dict_entries_for_configurations(sol006_vnfd)
            sol006_vnfd["df"][0]["lcm-operations-configuration"]["operate-vnf-op-config"]["day1-2"].extend(kdu_configs)



def _add_im_k8s_clusters_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    im_k8s_cluster = im_vnfd.get("k8s-cluster")
    if not im_k8s_cluster:
        return

    sol006_k8s_cluster = {}
    if im_k8s_cluster.get("version"):
        sol006_k8s_cluster["version"] = im_k8s_cluster["version"]
    if im_k8s_cluster.get("cni"):
        sol006_k8s_cluster["cni"] = im_k8s_cluster["cni"]

    nets = []
    k8s_cluster_ext_cpds = []
    for net in im_k8s_cluster.get("nets", ()):
        if net.get("external-connection-point-ref"):
            ext_cpd = {"id": "{}-ext".format(net["external-connection-point-ref"]), "k8s-cluster-net": net["id"]}
            k8s_cluster_ext_cpds.append(ext_cpd)
        nets.append({"id": net["id"]})
    if len(nets) > 0:
        sol006_k8s_cluster["nets"] = nets

    sol006_vnfd["k8s-cluster"] = sol006_k8s_cluster
    if len(k8s_cluster_ext_cpds) > 0:
        if not sol006_vnfd.get("ext-cpd"):
            sol006_vnfd["ext-cpd"] = []
        sol006_vnfd["ext-cpd"].extend(k8s_cluster_ext_cpds)


def _add_im_placement_groups_to_sol006_vnfd(im_vnfd, sol006_vnfd):
    if im_vnfd.get("placement-groups"):
        sol006_vnfd["placement-groups"] = im_vnfd["placement-groups"]


# ******************** NSD translation private functions ********************

def _remove_im_nsd_envelope(im_nsd):
    # Data is wrapped as { nsd-catalog: { nsd: [ <data> ] } }
    return list(im_nsd.values())[0]["nsd"][0]


def _add_im_nsd_basic_data_to_sol006_nsd(im_nsd, sol006_nsd):
    sol006_nsd["id"] = im_nsd["id"]
    if im_nsd.get("name"):
        sol006_nsd["name"] = im_nsd["name"]
    if im_nsd.get("description"):
        sol006_nsd["description"] = im_nsd["description"]
    if im_nsd.get("vendor"):
        sol006_nsd["designer"] = im_nsd["vendor"]
    if im_nsd.get("version"):
        sol006_nsd["version"] = im_nsd["version"]


def _add_im_constituent_vnfds_to_sol006_nsd(im_nsd, sol006_nsd):
    vnfd_ids = set()
    for constituent_vnfd in im_nsd.get("constituent-vnfd", ()):
        if constituent_vnfd.get("vnfd-id-ref"):
            vnfd_ids.add(constituent_vnfd["vnfd-id-ref"])

    if len(vnfd_ids) > 0:
        sol006_nsd["vnfd-id"] = list(vnfd_ids)


def _add_im_vlds_to_sol006_nsd(im_nsd, sol006_nsd):
    vlds = im_nsd.get("vld", [])
    flattened_vlds = [{**vld, **cp_ref} for vld in vlds for cp_ref in vld.get("vnfd-connection-point-ref", ())]
    all_vlds_by_member_vnf_index = {}
    for vld in flattened_vlds:
        member_vnf_index = str(vld.get("member-vnf-index-ref", ""))
        if member_vnf_index in all_vlds_by_member_vnf_index:
            all_vlds_by_member_vnf_index[member_vnf_index].append(vld)
        else:
            all_vlds_by_member_vnf_index[member_vnf_index] = [vld]

    df = {"id": "default-df", "vnf-profile": []}

    for member_vnf_index in all_vlds_by_member_vnf_index:
        vnf_profile = {"id": member_vnf_index}
        vnf_profile["vnfd-id"] = all_vlds_by_member_vnf_index.get(member_vnf_index, [{}])[0].get("vnfd-id-ref")
        vnf_profile["virtual-link-connectivity"] = []
        for vld in all_vlds_by_member_vnf_index[member_vnf_index]:
            virtual_link_connectivity = {"virtual-link-profile-id": vld["id"]}
            virtual_link_connectivity["constituent-cpd-id"] = [{
                "constituent-base-element-id": member_vnf_index,
                "constituent-cpd-id": "{}-ext".format(vld.get("vnfd-connection-point-ref"))
            }]
            if vld.get("ip-address"):
                virtual_link_connectivity["constituent-cpd-id"][0]["ip-address"] = vld["ip-address"]
            vnf_profile["virtual-link-connectivity"].append(virtual_link_connectivity)

        vlcs_by_virtual_link_profile = {}
        for vlc in vnf_profile.get("virtual-link-connectivity"):
            vl_profile_id = vlc.get("virtual-link-profile-id")
            if vl_profile_id in vlcs_by_virtual_link_profile:
                vlc_constituent_cpds = vlcs_by_virtual_link_profile[vl_profile_id].get("constituent-cpd-id")
                vlc_constituent_cpds.extend(vlc.get("constituent-cpd-id"))
            else:
                vlcs_by_virtual_link_profile[vl_profile_id] = vlc

        vnf_profile["virtual-link-connectivity"] = list(vlcs_by_virtual_link_profile.values())

        df["vnf-profile"].append(vnf_profile)

    sol006_nsd["df"] = [df]

    virtual_link_descs = []
    for vld in im_nsd.get("vld", ()):
        virtual_link_desc = {"id": vld["id"]}
        if vld.get("mgmt-network"):
            virtual_link_desc["mgmt-network"] = vld["mgmt-network"]
        if vld.get("vim-network-name"):
            virtual_link_desc["vim-network-name"] = vld["vim-network-name"]
        virtual_link_descs.append(virtual_link_desc)

    if len(virtual_link_descs) > 0:
        sol006_nsd["virtual-link-desc"] = virtual_link_descs
