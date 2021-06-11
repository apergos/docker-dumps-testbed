# Dumps docker testbed architecture and todos

## What I want in a testbed

Someone can write out a small configuration file in yaml, run a script with the steps
"build", "create", "start" and the specified container set name, and get a little
testbed all set up automatically.

Then they can run the script with "test" and the name of a pre-existing test to run
that test and get results automatically.

Or they can create a test themselves, add the relevant information about it to a
config file, and run that via "test" and the name.

Or they can do live runs on the containers by scp-ing files into and out of them
as needed for additional setup, logging into them, and running dumps steps by hand.

They can log in to inspect the private logs, connect to the dumps web server (if
configured) on port 8080 via their browser and look at (and even download, heh) dumps
output files.

They can connect to the wiki farm in that container set by connecting to the app server
on port 80 via their browser, and look at (and even edit) wiki articles.

They can revert any changes they make by destroying the existing container set and
creating and starting a new one.

They can have multiple sets so that they can compare behavior between different
configurations or different code versions.

They can stop, destroy and remove container sets and their underlying images with the
same script.

## How we get there

### Containers needed 
We need the following containers:

* one or more snapshot instances (generates dumps)
* optional dumpsdata server (provides nfs fileshare to dumps generators)
* optional dumps web server (nginx, receives rsync from dumpsdata server, serves via port 8080)
* mariadb primary server (has the usual tables for every wiki in the farm, r/w)
* optional mariadb replica (read-only replica of the mariadb primary)
* optional mariadb storage server (has blobs containing revision content, r/w)
* mediawiki php-fpm instance (processes all php web requests)
* mediawiki web server (apache, responds to all http requests on port 80, using php-fpm instance for php requests)

### Not needed, or at least not yet 

There are no provisions at this stage for memcached, varnish, redis and so on.
Any caching that goes in front of the app server will not be added, as it's not
implicated in our testing. We should eventually add other caching that's used internal
to MediaWiki however.

We'll use whatever the parsing mechanism is within MediaWiki, without Parsoid/RESTbase,
for now. Setting up Cassandra containers with RESTbase on top of them is beyond the
initial scope of this project.

Wikibase? Not for testing purposes. Eventually it will be good to have a properly
configured Wikidata member of the wiki farm, so that we can test Wikidata entity dumps.
Later.

### Wiki farm notes 

We'll need a Commons-like member of the farm, and several wikis of varying sizes.
At least one of those will use a non-ascii character set for article titles.

As noted above, no Wikidata member, at least for now.

Access to wikis in the farm won't be via nice names like we do in production.
Naming in containers is annoying and maintaining a list of virtual hosts and
a pile of mappings is also outside the scope of this project. We should be
able to get everything done by using something like
<container-setname>-mw.<container-setname>.lan/<wikiname>/mw/
as the lead prefix for entry to each wiki.

All wikis will share a very small CommonSettings.php and an equally small
InitialiseSettings.php, as well as a LocalSettings.php identical across
all members of the farm. There is also a db_mapping.php file which contains
a map from the name of the wiki (directory) to the name of the wiki db, since
these are not necessarily identical.

There is no MWScript facility for now. We could rearrange everything to use
one at some point. I'm not sure how much utility it would add.

### Dockerfiles 

We should keep in mind the documented Best Practices at
https://docs.docker.com/develop/develop-images/dockerfile_best-practices/
but not necessarily be inflexible about these rules.

TBD: what do we want to do about apt-get update, having latest packages
for security reasons but also having reproducibility for purposes of
testing?

We'll use ENTRYPOINT even if warned off it via those guidelines. We need
it; see later in this document for why.

It would be nice to create as few intermediate images as possible, so
we want RUN statements that do several things, and COPY statements that
copy as many files into place as possible in one line. We can avoid ADD
altogether.

### Docker volumes 

We should try to keep the number of volumes to a minimum and organize
them by container set and instance type. For a given container set,
we will need:

* volume for all branches of mediawiki in use by the wikifarm php-fpm instances
* volume for the dumps repo used by all the snapshot instances
* if there is a dumpsdata instance, the nfs filesystem with all the dumps output files should contain a mounted volume
* if there is a dumps webserver instance, the filesystem with all the dumps output files should contain a mounted volume
* the database instances should all have mounted volumes containing their mysql database tables and logs.

These should all probably on the host's local disk be nicely organized by container set and subdirectory
so it doesn't become a huge mess.

### Networking 

Networking in Docker containers, and especially to the host running them, is a nuisance
at best. Networking connectivity we need:

* php-fpm instance to db instances (3306)
* mediawiki web server to php-fpm instance (9000)
* snapshot instances to db instances (3306)
* snapshot instances to app server instance (80)
* snapshot instance to dumpsdata instance, if configured (nfs)
* dumpsdata instance to dumps web server instance, if configured (rsync)
* db replica to db primary (3306?)

In addition the host (laptop/desktop) should have access to all instances via ssh,
and various instances on specific ports, namely:

* db instances: 3306
* mediawiki web server instance: 80
* dumps web server, if configured: 8080

Because names of the containers are not determined until they are created, because
only at that time are they attached to a specific network, the name of which
is embedded in the container name to distinguish it from containers in some
other set, we cannot just hardcode all the names into the configuration. For example,
we must tell the mediawiki web server where the php-fpm instance is. This name will
not be known at image creation. Likewise we must configure some users and grants
for mariadb; here we are in better shape, since we can specify a wildcard to cover
all users from 17.16.*.*

Once the name of the network is known, we can generate the names of all containers
in the set, but these must then be shoved into various configurations somehow
at container creation time. This is best done via use of ENTRYPOINT in combination
with CMD; see the section on that in this document for more details.

To make networking from the desktop/latop suck less, we use a modified version of
https://github.com/nicolai-budico/dockerhosts which is currently living at
https://github.com/apergos/dockerhosts
It relies on dnsmasq and a one-line modification to /etc/systemd/resolved.conf

This may not be the best choice, but the more popular solution, DPS, works by
editing /etc/hosts periodically, and other soliutions that I investigated had equally
problematic approaches. This one seemed the least objectionable. Note however this
method requires use of a Linux distro that uses systemd-resolved. Most modern distros do.

With that setup in place, we can get to any container in any container set by
specifying the fqdn: container-name.set-name.lan
All names end in ".lan" so that we are sorta-kinda in compliance with "don't
use fake TLDs except these known ones that external resolvers know to ignore,
in theory".

### ENTRYPOINT 

We want proper signalling of the process(es) run in the container so that they
can gracefully stop if they have that capability. This means we want to use the "exec"
form of ENTRYPOINT. Containers will be running a shell script that sets up last
minute configuration based on the network name, invokes sshd as a daemon, and
lastly executes the main process (httpd, mariadb, etc). This shell script should
call the main process via exec. Containers that have no such main process, such
as the snapshot containers, should start sshd in the foreground as the main process,
also with exec.

Background reading (can't find the post I wanted, here's a random one):
https://www.ctl.io/developers/blog/post/dockerfile-entrypoint-vs-cmd/

### Database back ends 

This is set up to use mariadb; it's what we use in production. You CANNOT MIX the standard
mysql client with the mariadb server; you will get garbage results, such as all of the database
names, table names and column names being rendered as hex instead of strings.

Converting this to use mysql might be possible if you want to try it, but we won't support it.

It should go without saying that support for e.g. postgres is entirely off the table.

### Security 

Not so much. This is a testbed. Run it on a laptop or desktop not exposed to the world.

* At some point we should replace the hardcoded mysql root password with something configurable.
* At some point we should replace the hardcoded root password for ssh with a user-generated ssh key.
* At some point we should generate random passwords for the wikifarm users that access wiki databases.
* It might be nice to restrict which instances can send requests to the php-fpm instance.
* We don't drop any capabilities for these containers. Maybe we should.
* Probably lots of other stuff.

### Current state 

* We can spin up and destroy images and containers on a particular network from a config.
* The snapshot instance doesn't actually contain the dump repo or the mediawiki one.
* The mariadb primary instance has no data beyond the system tables.
* There is no mediawiki web server instance, nor php-fpm instance (yet).
* The optional images don't exist.

### Current work next steps 

* Write a generic entrypoint script
* Get a minimal mediawiki web server instance working, without php-fpm or mediawiki, just the web server with a config that is production-like but adapted to the few resources of a container on a laptop
* Get a php-fpm instance that serves only one file (index.php which just prints hello, let's say) working with the mw web server
* Get a mariadb primary instance set up with elwikivoyage test data imported.
* Add appropriate users and grants to the mariadb primary instance for mediawiki access to elwikivoyage via wikifarm.
* Add wikifarm volume to php-fpm instance. This should include the various configs initially; the goal is just to get it to work.
* Add wikifarm volume and dumps repo volume to snapshot instance. This should include the various configs initially.
* Clean up and finalization of locations of things, etc.

### Work to do for the generic entrypoint script 

* It should accept names for all instances that must communicate with each other.
* It should reference a configuration, and a directory of templates.
* For each template in the configuration, it should read the file, substitute the values in, and copy it to the configured location.
* Probably the templates should end in tmpl just to be nice.
* The values should have been passed in at docker create time, as arguments to the command, and should be pulled out and parsed.
* The command to run should be defined in the configuration as well.
* The configuration file will differ from one instance type to another, but can be defined at image creation time.

### Next steps for the mariadb primary instance 

* COPY in some smallish sql.gz files and import them via script, then verify that the resulting image provides a usable not too huge container. SAVE THAT IMAGE (1)
* Add users and grants via script and check that the resulting container looks right. SAVE THAT IMAGE (2)
* Add a user for replication and save that image (3)
* See if a second container from (2) can be converted manually to use replication against (3). What's required? Can it be automated?

Note that this first version will have one wiki only, use compression for content blobs which will
continue to live right in the text (?) table of the same wiki db, no external store.

Already done:

* system tables are installed via mysql_install_db
* the test db is gone
* the local root user has a (crap) password, anon user is gone, remote root user is gone
* /etc/my.cnf has been modified from the production one to values more suitable for a tiny container on a laptop.

### Work to do for the minimal mw web server instance 

* Check all configurations copied over from production docker images/puppet.
* Look into all the environment variables it may need and that we set in the production docker images.

We use SetHandler for php-fpm (available since Apache 2.4.10) rather than ProxyPassMatch, see
https://bugzilla.redhat.com/show_bug.cgi?id=1136290

We use TCP rather than unix sockets. If we wanted to use a unix socket, it would have to be made available
to the mw web server instance and the php-fpm instance, probably via a volume. We'll use volumes only for
repos and large amounts of data, however.

With SetHandler, we want to define a worker for the same fcgi backend, see
https://httpd.apache.org/docs/2.4/mod/mod_proxy_fcgi.html
This means adding a Proxy directive with enablereuse=on.

We use apachectl, as the production docker image does, rather than invoking httpd directly, because... 

#### In /etc/apache2/conf-enabled: 

We can leave out the 50-wikimedia-cluster.conf defined in puppet and in the production docker images,
because it's all about setting a SERVERGROUP for separating out parsoid app servers from mw ones for
logging, and we don't care about that.

We can leave out 50-php-admin-port.conf defined in puppet and in the production docker images,
because it's about prometheus metrics and we also don't care about that.

We can skip 50-server-header.conf defined in puppet and in the production docker images,
because it's about mod_security2 (traffic filtering, monitoring, analysis, see
https://github.com/SpiderLabs/ModSecurity for more) and we don't care about that either.

We can use 00-defaults.conf and 00-fcgi-headers.conf as is.

We use much smaller values in 50-worker.conf (for mpm_worker settings) than are used on production
app servers since we are running tiny little containers on a laptop. This is not yet in the production
docker-images, I stole it from the template in puppet.

#### In /etc/apache2/modules-enabled: 

We can keep as is, the files alias.conf, dir.conf, autoindex.conf, mime.conf; these are either identical
to the versions in the debian package or the changes are harmless.

We can skip setenvif.conf, which is directed at ancient browers.

We can skip security2.conf since that's the filtering/firewall bit and we don't care.

We can skip proxy.conf as it is entirely commented out.

We can skip expires.conf because it deals with expire headers and CORS for static content and
we definitely don't care about that.

We can skip mpm_worker.conf because we already have 50-worker.conf which has values for the
same settings (why are there both files in prod??) and have been tuned for a tiny container
on a laptop.

#### In /etc/apache2/sites-enabled: 

We'll keep 00-dummy.conf as is, in case the wildcard thing is something we need.
The rest are not useful for our configuration. We'll set up a custom 30-wikifarm.conf
and that will be it.

#### Top level /etc/apache2/apache2.conf 

This needs a complete rewrite as well.

