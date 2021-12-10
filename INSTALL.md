# Prerequisites and installation

## Prerequisites

You will need the following in order to get the testbed installed and running:

 - https://github.com/apergos/dockerhosts 
 - dnsmasq
 - docker
 - mysql_install_db and mysqld binaries
 - python-mysqldb
 - python-docker
 - mwbzutils
 - https://github.com/wikimedia/operations-dumps

## Preparation for installation

### Data for import

You'll want to export one or more wikis from an existing MediaWiki installation to populate the testbed.
In the future some sample files will be provided. To produce a file suitable for import, run:

  mysqldump -u root -p --default-character-set=binary <dbname> | gzip > <dbname>.sql.gz

for each wiki that you want to import, and follow the instructions in the file
docker_helpers/mariadb/imports/README.txt for making a directory in which to place the file, as well
as copying the file into place so that the installation scripts can use it.

### MariaDB

While you do not need a running database on the host which will run the test cluster of containers,
you do need to have the binaries mysql_install_db and mysqld available in /usr/bin, /usr/local/bin or
/usr/libexec so that the setup script can find them.

You'll also need to install python-mysqldb for use during testsuite setup.

### Networking

You need to install dnsmasq via your linux distribution's package manager, and then clone a copy
of https://github.com/apergos/dockerhosts and install it by running

  sudo ./install.sh

Once that's done, you'll need to add the entry

  DNS=127.0.0.54

to the file /etc/systemd/resolv.conf at the beginning of the [Resolve] stanza.

### Docker

Make sure that Docker itself is installed; depending on your distribution you may be able to install
via your standard package manager, or you may need to enable the Docker repositories and install from
there.

You'll also need the python Docker SDK, typically available in a package called python-docker.

### Dumps

You need a clean checkout of the operations/dumps repo from Wikimedia to start. You'll want to
set up a configuration file for the testbed; you can start with a copy of default.conf and add
or adjust things to see fit. You will want to add the path to your checkout of the dumps
repo under the "volumes" section of your test cluster configuration, for the "dumpsrepo" parameter.

You will be able to make changes to the code in this directory and test them, since the
directory will be a mounted volume used within the testbed containers to run dumps tests.

### Configuration

At this point you should proceed to configuration. Please see the document "CONFIGURE.md"
in this directory for more information.


