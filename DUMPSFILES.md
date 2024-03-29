# Setup of dumps repo and other files

Three directories should be provided on your local host for dumps-related
files. Each of these will become a mounted volume available to the snapshot
containers when they are created.

## Dumps repo

You will need to check out a copy of the dumps python scripts repo. Either
that directory or some parent directory should be made available to the
containers, by providing its path to the volumes:dumpsrepo entry in the
config for the given container set. This directory should be readable by
the world or by the group with gid 489.

## Dumps config file and dblists

You should create a directory which will hold your dump run configuration file,
as well as the various lists of databases that the dumsp use to decide which
ones have various extensions enabled, which ones are private, and so on. Provide
the path to this directory as a value for the volumes:dumpsetc entry in the
config for the given container set. This directory should be readable by
the world or by the group with gid 489.

## Dumps run output files

You should create a directory where dumps output for all runs will be written.
Provide the path to this directory as a value for the volumes:dumpsetc entry in
the config for the given container set. This directory should be readable and
writeable by the world or (preferrably) by the group with gid 489.

## Dumps template files

Some heml files and text templates are used during the dump run in order to
generate html pages showing the status of a dump run for one or all wikis.
These templates must be placed in a directory, preferably under the dumpsetc
path someplace, and your dumps configuration file should include that path.
Samples of such files are available in the dumps repo in xmldumps-backup/samples/
and can be copied in and edited to suit your taste for testing.
