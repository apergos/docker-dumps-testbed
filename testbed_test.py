#!/usr/bin/python3
'''
some unit tests for the sql/xml dumps testbed
'''
import os
import pwd
import shutil
import subprocess
import unittest
import psutil
import yaml
import docker_dumps_tester
from docker_helpers.setup_image import MariaDB


class MariaDBTest(unittest.TestCase):
    '''
    test startup and shutdown of mariadb server, running queries, etc
    '''
    MYSQLTESTDIR = "dump_test_temp"

    @staticmethod
    def get_datadir():
        return os.path.join(os.getcwd(), MariaDBTest.MYSQLTESTDIR, "mysqldata")
        
    @staticmethod
    def get_logfile():
        return os.path.join(os.getcwd(), MariaDBTest.MYSQLTESTDIR, "mysqld.log")

    @staticmethod
    def get_config(configpath):
        '''
        read a yaml config file and return whatever's in it. meh.
        '''
        if not configpath:
            return None
        try:
            with open(configpath, "r") as fin:
                contents = fin.read()
                return yaml.safe_load(contents)
        except Exception:
            print("unable to read configuration from {path}, continuing".format(path=configpath))
            return None

    def setUp(self):
        '''
        set up a temporary datadir and "install" mariadb/mysqldb
        with the basic system dbs into it
        '''
        # see if we have the mysql install binary, otherwise don't bother with setup
        basedir = self.get_mysqld_basedir("mysql_install_db")
        mysql_install_db_path = os.path.join(basedir, "bin", "mysql_install_db")
        if not os.path.exists(mysql_install_db_path):
            mysql_install_db_path = os.path.join(basedir, "libexec", "mysql_install_db")
            if not os.path.exists(mysql_install_db_path):
                return

        datadir = self.get_datadir()
        if os.path.exists(datadir):
            shutil.rmtree(datadir)
        os.makedirs(datadir)

        current_user = pwd.getpwuid(os.geteuid()).pw_name
        command = ["mysql_install_db", "--basedir=" + basedir, "--datadir=" + datadir,
                   "--auth-root-authentication-method=normal", "--user=" + current_user]
        result = subprocess.run(command, capture_output=True, check=False)
        if result.returncode:
            error = "Unknown error"
            if result.stderr:
                error = result.stderr.decode('utf8')
                print("failed to do base install of mysqld server into " +
                      datadir + " (", error, ")")

    def tearDown(self):
        '''
        try to shoot the db server if it's running, only ones we started,
        and then cleanup the data dir and the log file
        we expect the db server to already be shut down properly but if
        tests fail, who knows
        '''
        datadir = self.get_datadir()
        for proc in psutil.process_iter():
            if proc.name() != 'mysqld':
                continue
            for field in proc.cmdline():
                if datadir in field:
                    proc.kill()
                    # we keep on with the outer loop in case there's a straggler
                    break
        if os.path.exists(datadir):
            shutil.rmtree(datadir)
        logfile = self.get_logfile()
        if os.path.exists(logfile):
            os.unlink(logfile)

    def get_mysqld_basedir(self, executable="mysqld"):
        '''check a config file first, and then various paths for the mysqld executable,
        and return the appropriate basedir'''
        basedir = None
        configpath = os.path.join(os.getcwd(), "testbed.config")
        if os.path.exists(configpath):
            config = self.get_config(configpath)
            if 'basedir' in config:
                basedir = config['basedir']
        if (not basedir or (not os.path.exists(os.path.join(basedir, "bin", executable)) and
                            not os.path.exists(os.path.join(basedir, "libexec", executable)))):
            if os.path.exists(os.path.join("/usr/local/bin", executable)):
                basedir = "/usr/local"
            elif os.path.exists(os.path.join("/usr/local/libexec", executable)):
                basedir = "/usr/local"
            elif os.path.exists(os.path.join("/usr/bin", executable)):
                basedir = "/usr"
            elif os.path.exists(os.path.join("/usr/libexec", executable)):
                basedir = "/usr"
            else:
                return None
        return basedir

    def test_start_stop_server(self):
        '''
        start the db server,
        run a random query,
        stop it, verify it's stopped
        '''
        sockname = os.path.join(os.getcwd(), self.MYSQLTESTDIR, "mysqld.sock")
        # read the sole configuration value for these so-called unit tests
        # we need to get the base dir for mysqld and friends from somewhere,
        # in case it's in some unusual place
        basedir = self.get_mysqld_basedir()
        if not basedir:
            # BAIL, we don't have the binaries
            print("Skipping this test, no mysqld binaries available")
            return

        datadir = self.get_datadir()
        mdb = MariaDB(sockname, basedir, datadir)
        # we're using the local host's config, which surely is set up with
        # mysqld starting as root, changing to some other user, writing logs
        # and pid file in some system locations, and running on the standard
        # port, let's not do any of that.
        logfile = self.get_logfile()
        pidfile = os.path.join(os.getcwd(), self.MYSQLTESTDIR, "mysql.pid")
        current_user = pwd.getpwuid(os.geteuid()).pw_name
        config_overrides = {'log_error': logfile, 'pid_file': pidfile,
                            'user': current_user}

        proc = mdb.start_server(config_overrides=config_overrides)
        mdb.stop_server(proc=proc)


class MergeInDefaultsTest(unittest.TestCase):
    '''
    test merging of one dict (like default config
    settings) into another dict (like user-specified
    config settings)
    '''
    def test_merge_missing_settings(self):
        '''test that we can merge one dict of some settings
        into another'''
        default_content = {'global': {'passwords': {
            'dbs': {'wikidb_user': 'wikidbuser_defaultset',
                    'wikidb_admin': 'wikidbadmin_defaultset',
                    'root': 'notverysecure'},
            'containers': {'root': 'testing'}
        }}}
        # entire password section missing
        user_provided_content = {'global': {'other_junk': 'stuff'}}
        merged = docker_dumps_tester.ContainerConfig.merge_in_defaults(
            user_provided_content['global'], default_content['global'], 'passwords')
        self.assertEqual(merged, default_content['global']['passwords'])

        # db section missing
        user_provided_content = {'global': {'passwords': {
            'containers': {'root': 'testing'}
        }}}
        merged = docker_dumps_tester.ContainerConfig.merge_in_defaults(
            user_provided_content['global'], default_content['global'], 'passwords')

        # wikidb_admin setting missing
        merged = docker_dumps_tester.ContainerConfig.merge_in_defaults(
            user_provided_content['global'], default_content['global'], 'passwords')
        user_provided_content = {'global': {'passwords': {
            'dbs': {'wikidb_user': 'wikidbuser_defaultset',
                    'root': 'notverysecure'},
            'containers': {'root': 'testing'}
        }}}
        self.assertEqual(merged, default_content['global']['passwords'])


if __name__ == '__main__':
    unittest.main()
