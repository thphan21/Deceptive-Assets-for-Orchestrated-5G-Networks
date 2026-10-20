#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^[1-9][0-9]*$ ]]; then
    echo "Usage: $0 <highest-subscriber-number>"
    echo "Example: $0 50"
    exit 1
fi

COUNT="$1"
IMSI_PREFIX="999700000000"

if (( COUNT < 2 )); then
    echo "Nothing to delete."
    echo "Subscriber ${IMSI_PREFIX}001 is preserved as the template."
    exit 0
fi

MONGO_POD=$(
    kubectl -n open5gs get pods \
        -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' \
    | grep -Ei 'mongo|mongodb' \
    | head -1
)

if [[ -z "$MONGO_POD" ]]; then
    echo "ERROR: MongoDB pod not found." >&2
    exit 1
fi

FIRST_DELETE="${IMSI_PREFIX}002"
LAST_DELETE=$(printf '%s%03d' "$IMSI_PREFIX" "$COUNT")

echo "MongoDB pod: $MONGO_POD"
echo
echo "The following generated subscriber range will be deleted:"
echo "  $FIRST_DELETE through $LAST_DELETE"
echo
echo "The template subscriber will be preserved:"
echo "  ${IMSI_PREFIX}001"
echo

read -r -p "Continue? [y/N] " ANSWER

if [[ "$ANSWER" != "y" && "$ANSWER" != "Y" ]]; then
    echo "Cancelled."
    exit 0
fi

kubectl -n open5gs exec "$MONGO_POD" -- \
    mongosh --quiet open5gs --eval "
const count = $COUNT;
const prefix = '$IMSI_PREFIX';

let deleted = 0;
let missing = 0;

for (let number = 2; number <= count; number++) {
    const imsi = prefix + String(number).padStart(3, '0');

    const result = db.subscribers.deleteOne({ imsi: imsi });

    if (result.deletedCount === 1) {
        print('DELETE ' + imsi);
        deleted++;
    } else {
        print('SKIP   ' + imsi + ' does not exist');
        missing++;
    }
}

print('');
print('Deleted:  ' + deleted);
print('Missing:  ' + missing);
print('Total DB: ' + db.subscribers.countDocuments());
"
