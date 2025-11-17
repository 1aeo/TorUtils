#migrate_instance_keys.sh
#!/bin/bash

# Check if exactly two arguments are provided
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <old_instance> <new_instance>"
    exit 1
fi

# Assign command-line arguments to variables
OLD_INSTANCE="$1"
NEW_INSTANCE="$2"

#  Create the new instance
sudo tor-instance-create "${NEW_INSTANCE}"

# Copy keys from the old instance to the new instance directory
sudo cp -R "tor-instances/${OLD_INSTANCE}/keys" "/var/lib/tor-instances/${NEW_INSTANCE}/"

# Change ownership of the new instance directory
sudo chown -R "_tor-${NEW_INSTANCE}:_tor-${NEW_INSTANCE}" "/var/lib/tor-instances/${NEW_INSTANCE}/"
