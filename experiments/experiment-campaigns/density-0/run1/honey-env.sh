# Honey environment variables
# Source this BEFORE starting the Caldera agent.
# This file exists on the controller/host only.

export DATABASE_URI=mongodb://open5gs-postgres/subscribermongodb://backup-reader:honey-secret@mongodb-backup.open5gs.local:27017/open5gs
export DATABASE_HOST=mongodb-backup.open5gs.local
export BACKUP_DATABASE=/opt/open5gs/backups/subscriber-db-previous.dump
export SSH_KEY_PATH=/opt/open5gs/etc/open5gs/hnet/subscriber-backup.key
export API_TOKEN=honey-open5gs-api-token-7f3a91c2
