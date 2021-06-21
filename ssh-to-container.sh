#!/bin/bash

# ssh into a container
# given the base name (setname-containertype[-number]) we get the network name and append it, then
# ssh there, without recording the IP in the known hosts file, so that re-instantiation of
# the containers in the testbed won't cause whines at the next ssh attempt

if [ -z "$1" ]; then
    echo "Usage: $0 container-name"
    echo "Pass in the container name and it will be turned into a fqdn automatically."
    echo "If the name you pass in has a dot in it, it will be treated as a fqdn and"
    echo "passed through as is."
    echo "Container names have the format <setname>-<containertype>[-<two-digit-number>]"
    echo "Known containers:"
    /usr/bin/python3 docker_dumps_tester.py
    exit 1
fi

CONTAINERNAME="$1"
if [[ $CONTAINERNAME != *.* ]]; then
    NETWORK=$( docker inspect  -f "{{json .NetworkSettings.Networks }}" $CONTAINERNAME | jq -r keys[0] )
    if [ -z "$NETWORK" ]; then
	echo "No network found for ${CONTAINERNAME}, giving up"
	exit 1
    fi
    CONTAINERNAME="${CONTAINERNAME}.$NETWORK"
fi

ssh -l root -o "StrictHostKeyChecking no" -o "UserKnownHostsFile /dev/null" -o "LogLevel=ERROR" "$CONTAINERNAME"
