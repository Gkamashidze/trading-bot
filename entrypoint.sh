#!/bin/sh
set -e
# Railway mounts Volumes as root at container start, overriding Dockerfile RUN commands.
# This script runs as root, fixes /data ownership, then drops privileges to appuser.
mkdir -p /data/raw
chown -R appuser:appgroup /data
exec gosu appuser "$@"
