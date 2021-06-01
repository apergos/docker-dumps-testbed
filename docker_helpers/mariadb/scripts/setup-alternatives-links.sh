#!/bin/bash

mkdir -p /usr/local/bin
/usr/bin/update-alternatives --install /usr/local/bin/mariadb mariadb /opt/wmf-mariadb104/bin/mysql 1
/usr/bin/update-alternatives --install /usr/local/bin/mariadbdump mariadbdump /opt/wmf-mariadb104/bin/mysqldump 1
/usr/bin/update-alternatives --install /usr/local/bin/mysql mysql /opt/wmf-mariadb104/bin/mysql 1
/usr/bin/update-alternatives --install /usr/local/bin/mysqldump mysqldump /opt/wmf-mariadb104/bin/mysqldump 1
/usr/bin/update-alternatives --install /usr/local/bin/mysqlbinlog mysqlbinlog /opt/wmf-mariadb104/bin/mysqlbinlog 1
/usr/bin/update-alternatives --install /usr/local/bin/mysql_upgrade mysql_upgrade /opt/wmf-mariadb104/bin/mysql_upgrade 1
/usr/bin/update-alternatives --install /usr/local/bin/mysqlcheck mysqlcheck /opt/wmf-mariadb104/bin/mysqlcheck 1
/usr/bin/update-alternatives --install /usr/local/bin/xtrabackup xtrabackup /opt/wmf-mariadb104/bin/mariabackup 1
/usr/bin/update-alternatives --install /usr/local/bin/mbstream mbstream /opt/wmf-mariadb104/bin/mbstream 1
