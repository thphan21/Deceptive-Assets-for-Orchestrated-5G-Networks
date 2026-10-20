# Honey environment variables
# Source this BEFORE starting the Caldera agent.
# This file exists on the controller/host only.

export DATABASE_URI=mongodb://open5gs-postgres/subscriber-honeymongodb://backup-reader:honey-secret@_honeymongodb-backup.open5gs.local:27017/open5gs_honey
export DATABASE_HOST=mongodb-backup.open5gs.local_honey
export BACKUP_DATABASE=/opt/open5gs/backups/subscriber-db-previous.dump_honey
export SSH_KEY_PATH=/opt/open5gs/etc/open5gs/hnet/subscriber-backup_honey.key
export API_TOKEN=honey-open5gs-api-token-7f3a91c2_honey
