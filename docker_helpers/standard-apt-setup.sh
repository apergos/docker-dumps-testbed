#!/bin/bash

# to be run from within a Dockerfile.
# this expects to find the wikimedia apt key in /root/wikimedia-apt-key

# set up apt properly
DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND

echo "deb http://mirrors.wikimedia.org/debian/ buster main contrib non-free" >> /etc/apt/sources.list
echo "deb-src http://mirrors.wikimedia.org/debian/ buster main contrib non-free" >> /etc/apt/sources.list

echo "deb http://security.debian.org/debian-security buster/updates main contrib non-free" >> /etc/apt/sources.list
echo "deb-src http://security.debian.org/debian-security buster/updates main contrib non-free" >> /etc/apt/sources.list

echo "deb http://mirrors.wikimedia.org/debian/ buster-updates main contrib non-free"
echo "deb-src http://mirrors.wikimedia.org/debian/ buster-updates main contrib non-free"

apt-get update -y
apt-get install -y gnupg
apt-key add /root/wikimedia-apt-key

# now that we have the key accepted, we can add our apt repo and set up for any updates we may want
echo "deb http://apt.wikimedia.org/wikimedia buster-wikimedia main thirdparty/hwraid" >> /etc/apt/sources.list
echo "deb-src http://apt.wikimedia.org/wikimedia buster-wikimedia main thirdparty/hwraid" >> /etc/apt/sources.list

apt-get update -y && apt-get upgrade -y && apt-get install -y apt-utils
apt-get install -y python3-software-properties bash-completion

# ssh access into container, allow login as root with password
apt-get install -y openssh-server && mkdir -p /var/run/sshd  && echo 'root:testing' |chpasswd
sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config
