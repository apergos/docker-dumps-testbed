# Architecture, design, and configuration

## Networking

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

## Container customization

Some containers need to include the names of other containers in their
configuration settings. We could pass this information on the fly
to each container at container start, and have an ENTRYPOINT script
make substitutions in a set of files varying on each container.

Or we can bake these changes into an image derived from the base
image for each container type (httpd, dbprimary, and so on),
so that on startup of the container, it just starts its specific
services.

I still don't know which approach will be better in the long run,
but for now we are going with derived images.

## Database back ends 

This is set up to use mariadb; it's what we use in production. You CANNOT MIX the standard
mysql client with the mariadb server; you will get garbage results, such as all of the database
names, table names and column names being rendered as hex instead of strings.

Converting this to use mysql might be possible if you want to try it, but we won't support it.

It should go without saying that support for e.g. postgres is entirely off the table.

## MediaWiki web server (httpd) instance 

* We use SetHandler for php-fpm (available since Apache 2.4.10) rather than ProxyPassMatch, see https://bugzilla.redhat.com/show_bug.cgi?id=1136290
* We use TCP rather than unix sockets. If we wanted to use a unix socket, it would have to be made available to the mw web server instance and the php-fpm instance, probably via a volume. We'll use volumes only for repos and large amounts of data, however.
* With SetHandler, we want to define a worker for the same fcgi backend, see https://httpd.apache.org/docs/2.4/mod/mod_proxy_fcgi.html This means adding a Proxy directive with enablereuse=on.
* We could use apachectl, as the production docker image does, rather than invoking httpd directly. Should we?

#### In /etc/apache2/conf-enabled: 

* We leave out the 50-wikimedia-cluster.conf defined in puppet and in the production docker images, because it's all about setting a SERVERGROUP for separating out parsoid app servers from mw ones for
logging, and we don't care about that.
* We leave out 50-php-admin-port.conf defined in puppet and in the production docker images, because it's about prometheus metrics and we also don't care about that.
* We skip 50-server-header.conf defined in puppet and in the production docker images, because it's about mod_security2 (traffic filtering, monitoring, analysis, see https://github.com/SpiderLabs/ModSecurity for more) and we don't care about that either.
* We use 00-defaults.conf and 00-fcgi-headers.conf as is.
* We use much smaller values in 50-worker.conf (for mpm_worker settings) than are used on production app servers since we are running tiny little containers on a laptop. This is not yet in the production
docker-images, I stole it from the template in puppet.

#### In /etc/apache2/modules-enabled: 

* We keep as is, the files alias.conf, dir.conf, autoindex.conf, mime.conf; these are either identical to the versions in the debian package or the changes are harmless.
* We skip setenvif.conf, which is directed at ancient browers.
* We skip security2.conf since that's the filtering/firewall bit and we don't care.
* We skip proxy.conf as it is entirely commented out.
* We skip expires.conf because it deals with expire headers and CORS for static content and we definitely don't care about that.
* We skip mpm_worker.conf because we already have 50-worker.conf which has values for the same settings (why are there both files in prod??) and have been tuned for a tiny container
on a laptop.

#### In /etc/apache2/sites-enabled: 

* We need 000-default.conf handling rewrites to index.php, from the production docker images.
* The rest are not useful for our configuration. We might set up a custom 30-wikifarm.conf and that will be it.

#### Top level /etc/apache2/apache2.conf 
* This has been rewritten with many sections kept as is.

