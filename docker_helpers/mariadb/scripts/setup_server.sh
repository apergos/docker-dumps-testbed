#!/bin/bash

password="$1"

#############
# start the server and wait for it to become available
/opt/wmf-mariadb104/bin/mysqld --basedir=/opt/wmf-mariadb104 --datadir=/srv/sqldata --skip-networking --socket=/run/mysqld/mysqld.sock &

for i in {30..0}; do
    if echo 'SELECT 1' | /usr/local/bin/mysql --protocol=socket -uroot -hlocalhost --socket=/run/mysqld/mysqld.sock --database=mysql &>/dev/null; then
        break
    fi
    sleep 1
done
if [ "$i" = 0 ]; then
    echo "Unable to start server."
    exit 1
fi

############
# secure mariadb

# queries and do_query stolen from mysql_secure_installation script
# which is included with every mariadb installation

basedir=/opt/wmf-mariadb104/
command=".mysql.$$"
output=".my.output.$$"

do_query() {
    echo "$1" >$command
    $basedir/bin/mysql -uroot --protocol=socket --socket=/run/mysqld/mysqld.sock <$command >$output
    if [ $? -ne "0" ]; then
	echo "Failed!"
    fi
}

echo "removing anon users"
do_query "DELETE FROM mysql.global_priv WHERE User='';"

echo "removing remote root"
do_query "DELETE FROM mysql.global_priv WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');"

echo "removing test db"
do_query "DROP DATABASE IF EXISTS test;"

echo "removing test db privs"
do_query "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%'"

echo "reloading priv tables"
do_query "FLUSH PRIVILEGES;"

echo "cleanup"
rm -f $command $output

echo "done!"

############
# set up root password
/usr/local/bin/mysql -uroot --protocol=socket --socket=/run/mysqld/mysqld.sock -e "SET PASSWORD FOR root@'localhost' = PASSWORD('notverysecure');"

############
# shut down the server now that we are done with it
if ! /usr/bin/mysqladmin shutdown -uroot -p$password --socket=/run/mysqld/mysqld.sock; then
    echo "Unable to shut down server."
    exit 1
fi
