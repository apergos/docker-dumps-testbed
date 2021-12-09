#!/bin/bash

# to be run from within a Dockerfile.
# this expects to find the wikimedia apt key in /root/wikimedia-apt-key

# set up apt properly
DEBIAN_FRONTEND=noninteractive
export DEBIAN_FRONTEND

echo "deb http://security.debian.org/ buster/updates main contrib non-free"  >> /etc/apt/sources.list
echo "deb-src http://security.debian.org/ buster/updates main contrib non-free" >> /etc/apt/sources.list

apt-get update -y
apt-get upgrade -y
apt-get install -y apt-utils python3-software-properties

apt-get install -y gnupg wget
wget -O - -o /dev/null http://apt.wikimedia.org/autoinstall/keyring/wikimedia-archive-keyring.gpg | apt-key add -
#apt-key add /root/wikimedia-apt-key

# now that we have the key accepted, we can add our apt repo and set up for any updates we may want
echo "deb http://mirrors.wikimedia.org/debian/ buster main contrib non-free" >> /etc/apt/sources.list
echo "deb-src http://mirrors.wikimedia.org/debian/ buster main contrib non-free"

echo "deb http://mirrors.wikimedia.org/debian/ buster-updates main contrib non-free" >> /etc/apt/sources.list
echo "deb-src http://mirrors.wikimedia.org/debian/ buster-updates main contrib non-free" >> /etc/apt/sources.list

echo "deb http://mirrors.wikimedia.org/debian/ buster-backports main contrib non-free" >> /etc/apt/sources.list
echo "deb-src http://mirrors.wikimedia.org/debian/ buster-backports main contrib non-free" >> /etc/apt/sources.list

echo "deb http://apt.wikimedia.org/wikimedia buster-wikimedia main component/php72 thirdparty/hwraid" >> /etc/apt/sources.list
echo "deb-src http://apt.wikimedia.org/wikimedia buster-wikimedia main component/php72 thirdparty/hwraid" >> /etc/apt/sources.list

# we prefer wmf packages always for installation
cat <<\EOF >> /etc/apt/preferences.d/wikimedia.pref
Package: *
Pin: release o=Wikimedia
Pin-Priority: 1001
EOF

apt-get update -y

# yaml and mysqldb are required for the base/final image setup script
apt-get install -y bash-completion python3-yaml python3-mysqldb


# ssh access into container, allow login as root with password
apt-get install -y openssh-server && mkdir -p /var/run/sshd  && echo 'root:testing' |chpasswd
sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config

