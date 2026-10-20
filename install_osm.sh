#!/bin/bash
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#

DEVOPS_REFSPEC="v19.0"
DOCKER_TAG="19"

function usage(){
    [ -z "${DEBUG_INSTALL}" ] || DEBUG beginning of function
    echo -e "usage: $0 [OPTIONS]"
    echo -e "Install OSM"
    echo -e "  OPTIONS"
    echo -e "     -h / --help:    print this help"
    echo -e "     -y:             do not prompt for confirmation, assumes yes"
    echo -e "     -S <refspec>: use a specific devops refspec (branch, tag, commit), default is master"
    echo -e "     -a <apt proxy url>: use this apt proxy url when downloading apt packages (air-gapped installation)"
    echo -e "     -c <kubernetes engine>: use a specific kubernetes engine (options: kubeadm, k3s), default is kubeadm"
    echo -e "     -t <docker tag> specify osm docker tag (default is latest)"
    echo -e "     -M <KUBECONFIG_FILE>: Kubeconfig of an existing cluster to be used as mgmt cluster instead of OSM cluster"
    echo -e "     -G <KUBECONFIG_FILE>: Kubeconfig of an existing cluster to be used as auxiliary cluster instead of OSM cluster"
    echo -e "     -O <KUBECONFIG_FILE>: Kubeconfig of an existing cluster to be used as OSM cluster instead of creating a new one from scratch"
    echo -e "     --no-mgmt-cluster: Do not provision a mgmt cluster for cloud-native gitops operations in OSM (NEW in Release SIXTEEN) (by default, it is installed)"
    echo -e "     --no-aux-cluster: Do not provision an auxiliary cluster for cloud-native gitops operations in OSM (NEW in Release SIXTEEN) (by default, it is installed)"
    echo -e "     -s <namespace>  namespace where OSM helm chart will be deployed (default is osm)"
    echo -e "     -d <docker registry URL> use docker registry URL instead of dockerhub"
    echo -e "     -p <docker proxy URL> set docker proxy URL as part of docker CE configuration"
    echo -e "     -m <MODULE>:    module to test a specific docker image (NG-UI, NBI, LCM, RO, MON) (can be used several times)"
    echo -e "     -T <docker tag> use specific docker tag for the module specified with option -m"
    echo -e "     -U <docker user>: specify docker user to use when pulling images from a private registry"
    echo -e "     -D <devops path>: use particular devops installation path"
    echo -e "     -e <external IP>: set the external IP address of the OSM cluster (default is empty, which means autodetect)"
    echo -e "     --debug:        debug mode"
    [ -z "${DEBUG_INSTALL}" ] || DEBUG end of function
}

function configure_apt_proxy() {
    [ -z "${DEBUG_INSTALL}" ] || DEBUG beginning of function
    OSM_APT_PROXY=$1
    OSM_APT_PROXY_FILE="/etc/apt/apt.conf.d/osm-apt"
    echo "Configuring apt proxy in file ${OSM_APT_PROXY_FILE}"
    if [ ! -f ${OSM_APT_PROXY_FILE} ]; then
        sudo bash -c "cat <<EOF > ${OSM_APT_PROXY}
Acquire::http { Proxy \"${OSM_APT_PROXY}\"; }
EOF"
    else
        sudo sed -i "s|Proxy.*|Proxy \"${OSM_APT_PROXY}\"; }|" ${OSM_APT_PROXY_FILE}
    fi
    sudo apt-get -y update || FATAL "Configured apt proxy, but couldn't run 'apt-get update'. Check ${OSM_APT_PROXY_FILE}"
    [ -z "${DEBUG_INSTALL}" ] || DEBUG end of function
}

while getopts ":a:c:e:S:D:s:t:U:d:p:m:T:M:G:O:-: hy" o; do
    case "${o}" in
        S)
            DEVOPS_REFSPEC="${OPTARG}"
            ;;
        t)
            DOCKER_TAG="${OPTARG}"
            ;;
        -)
            [ "${OPTARG}" == "help" ] && usage && exit 0
            ;;
        :)
            echo "Option -$OPTARG requires an argument" >&2
            usage && exit 1
            ;;
        \?)
            echo -e "Invalid option: '-$OPTARG'\n" >&2
            usage && exit 1
            ;;
        h)
            usage && exit 0
            ;;
        *)
            ;;
    esac
done

sudo DEBIAN_FRONTEND=noninteractive apt-get -qy update
sudo DEBIAN_FRONTEND=noninteractive apt-get -y install git
DEVOPS_PATH=$(mktemp -d /tmp/osm-devops-XXXXXX)
git clone https://osm.etsi.org/gitlab/osm/devops.git $DEVOPS_PATH
git -C $DEVOPS_PATH fetch "https://osm.etsi.org/gitlab/osm/devops" $DEVOPS_REFSPEC
git -C $DEVOPS_PATH checkout FETCH_HEAD
$DEVOPS_PATH/installers/full_install_osm.sh -t $DOCKER_TAG "$@"
