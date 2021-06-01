docker dumps testbed
====

OK First up:

This is not working! I am committing the broken pieces so I don't lose them.
Right now I can build images, spin up and down containers and their network,
and do it based on configuration in a file. And I can ssh into the so-called
snapshot container. It doesn't do anything!

But it will.

Eventually you'll be able to spin up containers with preloaded wiki databases,
a web server to view pages and even make edits from your laptop, and the ability
to define dumps test suites as well. You'll define wiki farms from configuration,
all for test purposes.

But not yet.

Be patient and check back form time to time. It'll happen.

One note:

For name resolution I settled on an update of https://github.com/nicolai-budico/dockerhosts
which is now available at https://github.com/apergos/dockerhosts
It's a pretty clean approach which doesn't involve overwriting resolv.conf or adding
things to /etc/hosts, which is why I chose this instead of DPS. But it likely only works on
*nix hosts.
