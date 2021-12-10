# Configuration guide

A default configuration file is provided in this directory, called "default.conf".
It will not work as is, and is provided for illustration purposes only. However,
you may copy it into a file with the name of your choice, and start by making changes
to it.

## Global directives

All wiki databases in your test clusters will have the same users and passwords.
In MediaWiki installations, there are normally three such users, the root user with full
privileges to do and touch everything, the wiki db user, which will have full access
to any wiki database but nothing else, and the wiki admin user, which will be able to
do reads and inserts to wiki databases but with certain limitations. These last two users
correspond to $wgDBadmin and $wgDBuser in your MediaWiki configuration.

If you want one set of wiki db users for all test clusters, you may put those user names and
passwords in the global section, in the passwords stanza under the db entry. Or you can
leave the "wikidb_user" name and the corresponding password and use that instead. These users
will get privileges corresponding to the wiki db admin user.

If you do not want any such global users, you may remove any such lines from the global db
entry.

Similarly a db root user will be set up with the password specified in the global stanza,
with access to all test clusters if it is under the global passwords stanza in the db section.

All containers in your clusters will be accessible via ssh as the root user; the password
for that account should be specified here, under the containers section, for the parameter
"root".

If you do not want the root user to be global with the same password across all test clusters,
simply remove the entry in the global db stanza.

If you want no global entries, remove all entries from the global stanza in your configuration
but leave the keyword there.

If you want to fall back to the global entries in default.conf, remove the global stanza and
keyword from your configuration.

## Test clusters

### Naming

You should decide how many test clusters you want to configure. Initially, we recommend
setting up one simple cluster to verify that everything is working the way you want.
But later you may add others as desired. These will all go under the "sets" entry.
The "defaultset" entry in this list would be set up to have all containers begin
with the string "defaultset-" and to have the cluster network name called "defaultset"
as well. You might prefer a shorter name, if you expect to use container or network
names for the cluster frequently.

### db users and passwords

If you want the wiki db users for your test clusters to differ from one cluster to another,
you'll need to add the user names and passwords to the db entry of the passwords stanza
for each test cluster. Note that the test suite will create these users and grant them access
to every wiki in the set.

You can also add an entry for "root" with a password, in the same section, and the root
user for that test cluster will have the specified password.

The value for the root password must be specified in either the global or the test cluster
config; there is no default value.

Likewise at least one wiki db user must be specified in either the global or test cluster
config; there is no default name or password.

### container root credentials

If you want the shell root user to have a different password on different test clusters,
you will need to add an entry for "root" with the desired password, in the containers section for
each test wiki config.

The value for the root password must be specified in either the global or the test cluster
config; there is no default value.

### Volumes

Some containers in the test suite will have a wikifarm directory tree, which will include one
or more copies of the mediawiki repo checked out, mounted as one volume. You can specify this
path in the "volumes" stanza in your test cluster config, in the "wikifarm" entry.

Some containers in the test suite will have a copy of the dumps repo, mounted as one volume. You
can specify this path in the "volumes" stanza in your test cluster config, in the "dumpsrepo" entry.

Some containers in the test suite will have a mounted volume containing the database files.
You can specify this path in the "volumes" stanza in your test cluster config, in the "dbdata"
entry. This directory must exist and be writable by the group with 499 gid; this will be the
group the mysql user, runnning the mariadb server, will have in the container. You can do
sudo chgrp +499 /path/to/db/files
on the host with the directory, to accomplish that.

