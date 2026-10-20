#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 || ! "$1" =~ ^[1-9][0-9]*$ ]]; then
    echo "Usage: $0 <number-of-subscribers>"
    echo "Example: $0 50"
    exit 1
fi

COUNT="$1"
IMSI_PREFIX="999700000000"

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

echo "MongoDB pod: $MONGO_POD"
echo

kubectl -n open5gs exec "$MONGO_POD" -- \
    mongosh --quiet open5gs --eval "
const count = $COUNT;
const prefix = '$IMSI_PREFIX';

/*
 * Dynamically select the subscriber with the numerically smallest IMSI
 * as the template.
 */
const template = db.subscribers
    .find({})
    .sort({ imsi: 1 })
    .limit(1)
    .toArray()[0];

if (!template) {
    throw new Error('No template subscriber exists in the database.');
}

const firstImsi = prefix + String(1).padStart(3, '0');
const lastImsi = prefix + String(count).padStart(3, '0');

print('===== Template subscriber =====');
print('IMSI: ' + template.imsi);
print('K:    ' + template.security.k);
print('OPc:  ' + template.security.opc);
print('AMF:  ' + template.security.amf);
print('SST:  ' + template.slice[0].sst);
print('DNN:  ' + template.slice[0].session[0].name);

print('');
print('===== Requested subscriber range =====');
print(firstImsi + ' through ' + lastImsi);
print('');

let created = 0;
let skipped = 0;

for (let number = 1; number <= count; number++) {
    const imsi = prefix + String(number).padStart(3, '0');

    if (db.subscribers.findOne({ imsi: imsi })) {
        print('SKIP   ' + imsi + ' already exists');
        skipped++;
        continue;
    }

    const subscriber = EJSON.parse(EJSON.stringify(template));

    /*
     * Remove MongoDB-generated IDs copied from the template.
     */
    delete subscriber._id;

    for (const slice of subscriber.slice || []) {
        delete slice._id;

        for (const session of slice.session || []) {
            delete session._id;
        }
    }

    /*
     * Assign the new identity and reset the authentication sequence.
     */
    subscriber.imsi = imsi;
    subscriber.security.sqn = Long('0');

    db.subscribers.insertOne(subscriber);

    print('CREATE ' + imsi);
    created++;
}

print('');
print('Requested: ' + count);
print('Created:   ' + created);
print('Skipped:   ' + skipped);
print('Total DB:  ' + db.subscribers.countDocuments());
"
