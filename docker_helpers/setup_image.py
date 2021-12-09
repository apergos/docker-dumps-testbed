#!/usr/bin/python
"""
Image setup for base and final images for each image type
"""
import getopt
import glob
import os
import stat
import sys
import shutil
import subprocess
import time
import yaml
import MySQLdb


class ImageSetupOpts():
    '''
    deal with command line options for this script
    '''

    @staticmethod
    def usage(message=None):
        '''
        display a nice usage message along with an optional message
        describing an error
        '''
        if message:
            sys.stderr.write(message + "\n")
            usage_message = """Usage: $0 --stage base|final --type <imagetype> [--set <setname>]
or: $0 --help

Do image setup for the base or final image of a specific image type, using the
specific setname and associated configuration settings.

Arguments:

 --stage   (-s):  'base' to build the base image for some image type; this is not set-dependent
                  'final' to build the final image for an image type for a specific set
                  using the configuration settings for the set, embedding container names for
                  the set, db credentials and so on into the image.
                  default: none
 --type    (-t):  type of image to build, one of 'snapshot', 'httpd', 'dumpsdata' (nfs),
                  'dbextstore', 'dbreplica', 'phpfpm', 'dbprimary'
                  default: none
 --set     (-S):  setname (required for building 'final' images)
                  default: none

Flags:

 --verbose (-v):  write some progress messages some day
 --help    (-h):  show this help message
"""
            sys.stderr.write(usage_message)
            sys.exit(1)

    @staticmethod
    def get_default_opts():
        '''
        initialize args with default values and return them
        set: a collection of containers defined in the config for one wikifarm
        test: a name for a specific test defined in the config and associated with a wikifarm
        '''
        args = {'stage': None, 'type': None, 'set': None}
        return args

    def check_opts(self, args):
        '''
        validate opts and make sure we have the mandatory ones
        '''
        if 'stage' not in args or not args['stage']:
            self.usage("The --stage argument must be specified and may not be empty.")
        if 'type' not in args or not args['type']:
            self.usage("The --type argument must be specified and may not be empty.")
        if args['type'] not in ['snapshot', 'httpd', 'dumpsdata', 'dbextstore',
                                'dbreplica', 'phpfpm', 'dbprimary']:
            self.usage("Unknown image type " + args['type'] + " specified.")
        if 'stage' == 'final' and ('set' not in args or not args['set']):
            self.usage("When building final images, the --set argument must be"
                       + " specified and may not be empty.")

    def process_opts(self):
        '''
        get command-line args and values, falling back to defaults
        where needed, whining about bad args
        '''
        try:
            (options, remainder) = getopt.gnu_getopt(
                sys.argv[1:], "s:t:S:vh",
                ["stage=", "type=", "set=","verbose", "help"])

        except getopt.GetoptError as err:
            self.usage("Unknown option specified: " + str(err))

        args = self.get_default_opts()

        for (opt, val) in options:
            if opt in ["-s", "--stage"]:
                args['stage'] = val
            elif opt in ["-S", "--set"]:
                args['set'] = val
            elif opt in ["-t", "--type"]:
                args['type'] = val
            elif opt in ["-v", "--verbose"]:
                args['verbose'] = True
            elif opt in ["-h", "--help"]:
                self.usage('Help for this script\n')
            else:
                self.usage("Unknown option specified: <%s>" % opt)

        if remainder:
            self.usage("Unknown option(s) specified: {opt}".format(opt=remainder[0]))

        self.check_opts(args)
        return args


class MariaDB():
    '''start and stop mariadb server, etc.'''
    def __init__(self, sockname, basedir, datadir):
        self.sockname = sockname
        self.basedir = basedir
        self.datadir = datadir

    def start_server(self, password=None, networking=False, config_overrides=None):
        '''
        start the server and wait for it to become available

        because this method is called by the test suite, which relies on the mysql or
        mariadb installation on the host that will run the docker containers, we must
        be able to set additional config values that override the local install
        (i.e. /etc/my.cnf); these should be passed in to config_overrides

        the started process is returned
        '''
        mysqld_path = os.path.join(self.basedir, "bin", "mysqld")
        if not os.path.exists(mysqld_path):
            mysqld_path = os.path.join(self.basedir, "libexec", "mysqld")
        command = [mysqld_path, "--basedir=" + self.basedir,
                   "--datadir=" + self.datadir, "--socket=" + self.sockname]
        if not networking:
            command.append("--skip_networking")
        if config_overrides:
            if 'log_error' in config_overrides:
                command.append('--log-error=' + config_overrides['log_error'])
            if 'pid_file' in config_overrides:
                command.append('--pid-file=' + config_overrides['pid_file'])
            if 'user' in config_overrides:
                command.append('--user=' + config_overrides['user'])
        # result = subprocess.run(command, capture_output=True, check=False)
        proc = subprocess.Popen(command)
        if proc.returncode:
            error = "Unknown error"
            if proc.stderr:
                error = proc.stderr
                print("failed to start mysqld server (", error, ")")

        running = False

        for _index in range(30):
            if self.do_query("SELECT 1;", password, "mysql"):
                running = True
                break
            time.sleep(1)

        if not running:
            # fixme probably an exception, no?
            sys.exit(1)
        return proc

    def do_query(self, command, password=None, database=None):
        '''
        run a single mariadb/mysql query against the running
        local server via unix socket, optional password.
        we don't even bother to return the output, just True
        on success, False on failure
        '''
        # we use an agressive timeout here but honestly 2 seconds is tons
        # of time to establish a connection when we're the only client
        # talking to the server
        kwargs = {'unix_socket': self.sockname,
                  'connect_timeout': 2,
                  'user': 'root',
                  'passwd': password,
                  'db': database}
        try:
            # instead of discarding keyword args with value None, connect() whines that
            # they aren't strings or whatever. silly thing.
            dbconn = MySQLdb.connect(**{k: v for k, v in kwargs.items() if v is not None})
            cursor = dbconn.cursor()
            cursor.execute(command)
        # except MySQLdb.Error as ohno:
        except Exception:
            return False
        return True

    def make_server_secure(self, password=None):
        '''get rid of stuff like test db, anonymous user, etc'''
        # queries and do_query stolen from mysql_secure_installation script
        # which is included with every mariadb installation
        print("removing anon users")
        self.do_query("DELETE FROM mysql.global_priv WHERE User='';", password)

        print("removing remote root")
        self.do_query("DELETE FROM mysql.global_priv WHERE User='root' AND " +
                      "Host NOT IN ('localhost', '127.0.0.1', '::1');", password)

        print("removing test db")
        self.do_query("DROP DATABASE IF EXISTS test;", password)

        print("removing test db privs")
        self.do_query("DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%'",
                      password)

        print("reloading priv tables")
        self.do_query("FLUSH PRIVILEGES;", password)

        print("done!")

    def set_root_password(self, new_password, current_password=None):
        '''set a new root db user password'''
        self.do_query(
            "SET PASSWORD FOR root@'localhost' = PASSWORD('{passwd}');".format(
                passwd=new_password),
            current_password)

    def stop_server(self, password=None, proc=None):
        '''stop mysql/mariadb server politely'''
        # fixme check return and whine if needed
        self.do_query("SHUTDOWN;", password)
        if proc:
            # the server is going to take a little while to shut down after
            # the command was given
            proc.wait()

    @staticmethod
    def import_sql(import_data_path, dbname, password=None):
        '''
        import the sql in the file specified, to the specified db, given the specified
        root password

        if the file does not exist, silently return
        '''
        if not os.path.exists(import_data_path):
            return
        command = "/bin/gzip -dc " + import_data_path + " | /usr/local/bin/mysql -u root"
        if password:
            command = command + " -p" + password
        command = command + " " + dbname
        result = subprocess.run(command, shell=True, capture_output=True, check=False)
        if result.returncode:
            error = "Unknown error"
            if result.stderr:
                error = result.stderr
            print("failed to import data:", import_data_path, "(", error, ")")

    def do_all_imports(self, importdir, wikis, password=None):
        '''
        for the specified directory, process all the sql.gz files in it as imports to
        the local db

        files should be named <wikidb>.anythinghere.sql.gz
        '''
        files = glob.glob(os.path.join(importdir, "*.sql.gz"))
        for sql_file in files:
            prefix = os.path.basename(sql_file).split('.')[0]
            if prefix in wikis:
                self.import_sql(sql_file, prefix, password)


class Httpd():
    '''manage httpd image setup'''

    @staticmethod
    def setup_modules():
        '''
        set up module conf files for httpd server
        '''
        # get rid of whatever module cruft debian put there
        to_toss = glob.glob('/etc/apache2/mods-enabled/*')
        for path in to_toss:
            os.remove(path)

        # for the modules we want, copy in any of our own configs and enable
        # we need access_compat because we use apache 2.2 directives (Order) on apache 2.4, meh

        modules = ["access_compat", "alias", "authn_core", "authz_core", "authz_host",
                   "autoindex", "deflate", "dir", "expires", "filter", "headers", "mime",
                   "mpm_worker", "proxy_fcgi", "proxy", "rewrite", "security2", "setenvif",
                   "status", "unique_id"]
        for module in modules:
            modpath = "/root/httpd-configs/modules/" + module + ".conf"
            if os.path.exists(modpath):
                shutil.copy(modpath, "/etc/apache2/mods-available/")
            result = subprocess.run(["/usr/sbin/a2enmod", "-q", module],
                                    capture_output=True, check=False)
            if result.returncode:
                error = "Unknown error"
                if result.stderr:
                    error = result.stderr
                print("failed to enable", modpath, "(", error, ")")

    @staticmethod
    def setup_configs():
        '''
        set up config files for httpd server
        '''
        # get rid of whatever main config cruft debian put there
        to_toss = glob.glob('/etc/apache2/conf-enabled/*')
        for path in to_toss:
            os.remove(path)

        # for the main configs we want, copy those in too
        configs = glob.glob('/root/httpd-configs/configs/*conf')
        for configpath in configs:
            shutil.copy(configpath, "/etc/apache2/conf-available/")
            config_basename = os.path.splitext(os.path.basename(configpath))[0]
            result = subprocess.run(["/usr/sbin/a2enconf", "-q", config_basename],
                                    capture_output=True, check=False)
            if result.returncode:
                error = "Unknown error"
                if result.stderr:
                    error = result.stderr
                print("failed to enable", configpath, "(", error, ")")

    @staticmethod
    def setup_sites():
        '''
        set up site configs for httpd server
        '''
        # get rid of whatever site config cruft debian put there
        to_toss = glob.glob('/etc/apache2/sites-enabled/*')
        for path in to_toss:
            os.remove(path)

        # for the site configs we want, copy those in too
        sites = glob.glob('/root/httpd-configs/sites/*conf')
        for sitepath in sites:
            shutil.copy(sitepath, "/etc/apache2/sites-available/")
            site_basename = os.path.splitext(os.path.basename(sitepath))[0]
            result = subprocess.run(["/usr/sbin/a2ensite", "-q", site_basename],
                                    capture_output=True, check=False)
            if result.returncode:
                error = "Unknown error"
                if result.stderr:
                    error = result.stderr
                print("failed to enable", sitepath, "(", error, ")")

    @staticmethod
    def setup_html():
        '''
        set up html files (index.html, error pages) for httpd server
        '''
        # make the docroots and copy in the html files
        # and make sure the web server can access files in there

        # one-off index.html, 404.php etc
        os.makedirs('/srv/mediawiki/dumptest', exist_ok=True)
        os.chmod('/srv/mediawiki/dumptest', 0o755)

        # document root is subdir of this, this will be mounted volume
        os.makedirs('/srv/mediawiki/wikifarm', exist_ok=True)
        os.chmod('/srv/mediawiki/wikifarm', 0o755)

        htmlfiles = glob.glob('/root/html/*')
        for htmlfile in htmlfiles:
            shutil.copy(htmlfile, '/srv/mediawiki/dumptest/')
            htmlfile_basename = os.path.basename(htmlfile)
            os.chmod(os.path.join(
                '/srv/mediawiki/dumptest', htmlfile_basename), 0o644)


class BaseImage():
    '''
    manage setup of the base image for any image type
    '''
    def __init__(self, itype, setname, first_db_root_pass=None):
        self.itype = itype
        self.setname = setname
        self.first_db_root_pass = first_db_root_pass

    def run(self):
        '''
        actually do the work needed to finish up a base image, should be the
        last thing called in a docker file (except EXPOSE, CMD)
        '''
        if self.itype == 'httpd':
            shutil.copy('/root/httpd-configs/envvars', '/etc/apache2/')

            # put the top-level config in place
            shutil.copy("/root/httpd-configs/apache2.conf", "/etc/apache2/")

            # other configs
            Httpd.setup_modules()
            Httpd.setup_configs()
            Httpd.setup_sites()

            # html files
            Httpd.setup_html()

        elif self.itype == 'phpfpm':
            # fixme TO BE DONE
            return

        elif self.itype == 'snapshot':
            # fixme TO BE DONE
            return

        elif self.itype == 'dbprimary':
            mdb = MariaDB("/run/mysqld/mysqld.sock", "/opt/wmf-mariadb104", "/srv/sqldata")
            proc = mdb.start_server()
            mdb.make_server_secure()
            mdb.set_root_password(self.first_db_root_pass)
            mdb.stop_server(self.first_db_root_pass, proc=proc)


class Credentials():
    '''
    manage passwords for container access, db access
    '''
    def __init__(self, itype, setname, credspath):
        self.itype = itype
        self.setname = setname
        self.creds = None
        with open(credspath, "r") as creds:
            self.creds = yaml.safe_load(creds.read())

    def set_container_root_creds(self):
        '''
        set the root password for all containers derived from this image
        '''
        if 'rootuser' in self.creds:
            result = subprocess.run(
                'echo "root:{passwd}" |chpasswd'.format(
                    passwd=self.creds['rootuser']),
                shell=True, capture_output=True, check=False)
            if result.returncode:
                error = "Unknown error"
                if result.stderr:
                    error = result.stderr
                print("failed to set container root creds (", error, ")")

    def setup_db_user(self, dbuser, wiki, mdb):
        '''
        create a user and add the appropriate grants for access to a wiki db
        '''
        command = "CREATE USER '{dbuser}'@'%' IDENTIFIED BY '{passwd}';".format(
            dbuser=dbuser, passwd=self.creds[dbuser])
        mdb.do_query(command, self.creds['rootdbuser'])
        command = "GRANT USAGE ON *.* TO `{dbuser}`@`%` IDENTIFIED BY '{passwd}';".format(
            dbuser=dbuser, passwd=self.creds[dbuser])
        mdb.do_query(command, self.creds['rootdbuser'])
        command = ("GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, REFERENCES, INDEX, " +
                   "ALTER, CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE, CREATE VIEW, " +
                   "SHOW VIEW, CREATE ROUTINE, ALTER ROUTINE, EVENT, TRIGGER ON " +
                   "`{wiki}`.* TO `{dbuser}`@`%`;".format(wiki=wiki, dbuser=dbuser))
        mdb.do_query(command, self.creds['rootdbuser'])

    def set_db_creds(self, password=None, config_overrides=None):
        '''
        set root password but also wikidb_user and wikidb_admin passwords for the specified
        wiki databases, as well as creating the dbs themselves (empty)

        for testing config_overrides can specify another user, etc. for mysqld
        '''
        if self.itype != 'dbprimary':
            return
        mdb = MariaDB("/run/mysqld/mysqld.sock", "/opt/wmf-mariadb104", "/srv/sqldata")
        proc = mdb.start_server(password, config_overrides=config_overrides)
        mdb.set_root_password(self.creds['rootdbuser'], password)

        # set up wikidb users for every wikidb we're going to have in the set.
        for wiki in self.creds['wikis']:
            mdb.do_query("CREATE DATABASE IF NOT EXISTS " + wiki,
                         self.creds['rootdbuser'])

            self.setup_db_user('wikidbuser', wiki, mdb)
            self.setup_db_user('wikidbadmin', wiki, mdb)

        mdb.stop_server(self.creds['rootdbuser'], proc=proc)

    def set_all(self, password=None, config_overrides=None):
        '''
        set up all credentials needed for any image type
        '''
        # some things get done on all images, some will check to be sure they are the
        # right image type first, we don't have to do any of that here
        self.set_container_root_creds()
        self.set_db_creds(password, config_overrides)


class FinalImage():
    '''
    manage setup of the base image for any image type
    '''
    def __init__(self, itype, setname, credspath, first_db_root_pass=None):
        self.itype = itype
        self.setname = setname
        self.credspath = credspath
        self.first_db_root_pass = first_db_root_pass

    def run(self):
        '''
        actually do the work needed to finish up a final image, should be the
        last thing called in a docker file (except EXPOSE, CMD)
        '''
        ContainerSubs.do_all('/root/substitution.conf', '/root/container_list', self.setname)
        creds = Credentials(self.itype, "/root/credentials." + self.setname, self.credspath)
        creds.set_all(self.first_db_root_pass)

        if self.itype == 'dbprimary':
            mdb = MariaDB("/run/mysqld/mysqld.sock", "/opt/wmf-mariadb104", "/srv/sqldata")
            proc = mdb.start_server(creds.creds['rootdbuser'])
            mdb.do_all_imports('/root/imports', creds.creds['wikis'], creds.creds['rootdbuser'])
            mdb.stop_server(creds.creds['rootdbuser'], proc=proc)


class ContainerSubs():
    '''
    read a configuration file with file path of templates and destination file paths
    for each entry, substitute in all the container names to each template and put
    the output in its final destination
    '''
    @staticmethod
    def get_container_info(path):
        '''read the container info from the specified file and return it'''
        with open(path, "r") as fin:
            contents = fin.read().splitlines()
            return contents

    @staticmethod
    def get_substitution_entries(path):
        '''read substitution entries from the specified file and return them
        as a list of source, dest tuples
        note that this will fail if source or dest path has whitespace in it'''
        with open(path, "r") as fin:
            lines = fin.read().splitlines()
            lines = [line for line in lines if line.strip() and not line.startswith('#')]
            entries = [line.strip().split(maxsplit=1) for line in lines]
            return entries

    @staticmethod
    def get_container_name(substring, container_info):
        '''return the name of the container having the specific substring.
        if more than one, or none at all, return None.
        you're supposed to be getting ONE UNIQUE container #kthxbai'''
        containers = [line for line in container_info if substring in line]
        if len(containers) != 1:
            return None
        return containers[0]

    @staticmethod
    def do_substitution(entry, container_info):
        '''given a source file, a destination path and container name info,
        swap in the real container names for placeholders in the source file
        and write the result to the destination path'''
        # strings we may replace: PHPFPM HTTPD DBPRIMARY (more later)
        with open(entry[0], "r") as fin:
            contents = fin.read()
            vars_to_containers = {'PHPFPM': 'phpfpm', 'HTTPD': 'httpd', 'DBPRIMARY': 'dbprimary'}
            for var, container in vars_to_containers.items():
                contents = contents.replace(
                    var, ContainerSubs.get_container_name(container, container_info))
            with open(entry[1], "w") as fout:
                fout.write(contents)

    @staticmethod
    def do_all(config_file, container_file, setname):
        '''entry point'''
        # setname = sys.argv[1]
        container_info = ContainerSubs.get_container_info(container_file + "." + setname)
        subs_entries = ContainerSubs.get_substitution_entries(config_file)
        for entry in subs_entries:
            ContainerSubs.do_substitution(entry, container_info)


def do_main():
    '''entry point'''
    opts = ImageSetupOpts()
    args = opts.process_opts()
    if args['stage'] == 'base':
        manager = BaseImage(args['type'], args['set'], 'notverysecure')
    elif args['stage'] == 'final':
        credspath = "/root/credentials." + args['set'] + ".yaml"
        manager = FinalImage(args['type'], args['set'], credspath, 'notverysecure')
    manager.run()


if __name__ == '__main__':
    do_main()
