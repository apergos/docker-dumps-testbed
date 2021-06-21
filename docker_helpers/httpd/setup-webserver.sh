#!/bin/bash

# set up environment vars, we'll use apachectl to start the server and it needs these
cp -f /root/httpd-configs/envvars /etc/apache2/

# get rid of whatever module cruft debian put there
rm -f /etc/apache2/mods-enabled/*

# for the modules we want, copy in any of our own configs and enable
# we need access_compat because we use apache 2.2 directives (Order) on apache 2.4, meh
MODULES="access_compat alias authn_core authz_core authz_host autoindex deflate dir expires filter headers mime mpm_worker proxy_fcgi proxy rewrite security2 setenvif status unique_id"
for module in $MODULES; do
    if [ -e "/root/httpd-configs/modules/${module}.conf" ]; then
	cp -f "/root/httpd-configs/modules/${module}.conf" /etc/apache2/mods-available/
    fi
    /usr/sbin/a2enmod -q $module
done

# get rid of whatever main config cruft debian put there
rm -f /etc/apache2/conf-enabled/*

# for the main configs we want, copy those in too
CONFIGS=/root/httpd-configs/configs/*conf
for configpath in $CONFIGS; do
    config=$( basename $configpath )
    cp -f "/root/httpd-configs/configs/${config}" /etc/apache2/conf-available/
    /usr/sbin/a2enconf -q $config
done

# get rid of whatever site config cruft debian put there
rm -f /etc/apache2/sites-enabled/*

# for the site configs we want, copy those in too
SITES=/root/httpd-configs/sites/*conf
for sitepath in $SITES; do
    site=$( basename $sitepath )
    cp -f "/root/httpd-configs/sites/${site}" /etc/apache2/sites-available/
    /usr/sbin/a2ensite -q $site
done

# put the top-level config in place
cp -f /root/httpd-configs/apache2.conf /etc/apache2/

# and finally make the docroots and copy in the html files
mkdir -p /srv/mediawiki/docroot/default /srv/app
chmod -R a+rx /srv/mediawiki
cp -f /root/html/* /srv/mediawiki/docroot/default/
cp -f /root/html/* /srv/app/
chmod -R a+r /srv/mediawiki/docroot/default/* /srv/app/*
