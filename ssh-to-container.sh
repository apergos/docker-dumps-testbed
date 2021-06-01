#!/bin/bash

# ssh into a container, given the base name. we can just get the network name and append it, then
# ssh there  :-P

if [ -z "$1" ]; then
    echo "Usage: $0 container-name"
    echo "Pass in the container name and it will be turned into a fqdn automatically."
    echo "If the name you pass in has a dot in it, it will be passed through as is."
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
