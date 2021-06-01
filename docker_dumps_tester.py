#!/usr/bin/python3

"""
manage one or more wikifarms of containers for sql/xml dump tests
"""
import os
import sys
import getopt
import yaml
from docker import DockerClient
import docker
import netaddr


class WikifarmSets():
    '''
    manage the build and running of images and containers as defined
    in a config
    '''
    def __init__(self, args, config, verbose):
        self.args = args
        self.config = config
        self.verbose = verbose

    @staticmethod
    def get_blame_label():
        '''this is the label name and value we slap on all
        images and containers created by us. Containers
        also get a set name in addition, handled elsewhere'''
        return {'blame': 'atgdumps'}

    def get_set_label(self):
        '''this is the set label that goes on containers and stuff.'''
        return {'set': self.args['set']}

    def has_blame_label(self, image):
        '''
        determine whether the image has our special blame label in there
        '''
        label = self.get_blame_label()
        for key, value in label.items():
            if key not in image.labels or value != image.labels[key]:
                return False
        return True

    def do_list(self):
        '''
        list all of the containers belonging to the specified set
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.containers.list('all')
        for entry in entries:
            if 'set' in entry.labels:
                if self.args['set'] in entry.labels['set']:
                    print("container: {name} ({short_id}), from: {image}, cmd: {cmd} "
                          "labels: {labels}, status: {status}".format(
                              name=entry.name, image=entry.attrs['Config']['Image'],
                              cmd=entry.attrs['Config']['Cmd'], labels=entry.labels,
                              short_id=entry.short_id, status=entry.status))

    @staticmethod
    def has_labels(labels, labels_wanted):
        '''check that the one bleep of labels has all the other ones in it'''
        for key, value in labels_wanted.items():
            if key not in labels or labels[key] != value:
                return False
        return True

    def get_container_ids(self, labels=None):
        '''return short ids of the containers for the given set'''
        containers = []
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.containers.list('all')
        if labels:
            for entry in entries:
                if self.has_labels(entry.labels, labels):
                    containers.append(entry.short_id)
        else:
            for entry in entries:
                print(entry.labels, entry.name)
                if self.has_labels(entry.labels, self.get_set_label()):
                    containers.append(entry.short_id)
        return containers

    def get_containerset_config(self):
        '''get the config settings for the specified wikifarm set'''
        for entry in self.config['sets']:
            if entry == self.args['set']:
                return self.config['sets'][entry]
        return [{}]

    def container_exists(self, short_id):
        '''check if the container with the specified id from a container set exists'''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.containers.list('all')
        for entry in entries:
            if self.has_labels(entry.labels, self.get_set_label()):
                if entry.name == short_id:
                    return True
        return False

    def image_exists(self, tag):
        '''check if the image with the specific tag in the container set exists'''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.images.list('all')
        for entry in entries:
            if self.has_blame_label(entry) and tag in entry.tags:
                return True
        return False

    def get_network_name(self):
        '''
        return the network name, at this point we have it end in '.lan'
        and maybe that should be ocnfigurable. FIXME?
        '''
        return self.args['set'] + ".lan"

    def create_network(self):
        '''
        for the specified set, create a bridge network in the 172.xxx.yyy.0/16 space
        with that name if none exists already; if one exists, just return

        this will check all existing docker networks to make sure the new network does
        not conflict with them. note that there is no guarantee that you will get
        the same network ip space for the same set if the network is destroyed and
        recreated.
        '''
        ip_spaces = []
        client = DockerClient(base_url='unix://var/run/docker.sock')
        networks = client.networks.list()
        for entry in networks:
            if (entry.name == self.args['set'] and
                    self.has_labels(entry.attrs['Labels'], self.get_set_label())):
                if self.verbose:
                    print("Network already exists.")
                return
            # collect the address space info
            for settings in entry.attrs['IPAM']['Config']:
                if 'Subnet' in settings and settings['Subnet'].startswith('172.'):
                    ip_spaces.append(settings['Subnet'])

        if self.verbose:
            print("ip spaces already used:", ip_spaces)
        possible =  netaddr.IPSet(['172.16.0.0/12'])
        allocated = netaddr.IPSet(ip_spaces)
        available = possible ^ allocated
        using = None
        for cidr in available.iter_cidrs():
            if cidr.prefixlen != 24:
                cidr.prefixlen = 24
                using = cidr
                if self.verbose:
                    print("using:", using)
                break
        if not using:
            raise ValueError("No network address space available in 172.16")

        ipam_pool = docker.types.IPAMPool(subnet=str(using))
        ipam_config = docker.types.IPAMConfig(pool_configs=[ipam_pool])
        labels = self.get_set_label().copy()
        labels.update(self.get_blame_label())
        client.networks.create(self.get_network_name(), driver="bridge", labels=labels, ipam=ipam_config)

    def remove_network(self, labels=None):
        '''
        if there is a network defined for the set, remove it
        note that if there are multiple networks defined for the set
        because someone created one or more manually, they all get removed.

        if we specify a dict of labels, then just remove every network
        with all of those labels
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        networks = client.networks.list()
        if labels:
            for entry in networks:
                if self.has_labels(entry.attrs['Labels'], labels):
                    if self.verbose:
                        print("Removing network")
                        entry.remove()
        else:
            for entry in networks:
                if (entry.name == self.get_network_name() and
                        self.has_labels(entry.attrs['Labels'], self.get_set_label)):
                    if self.verbose:
                        print("Removing network")
                        entry.remove()

    def do_build(self):
        '''
        build images needed for the containers associated with a wikifarm set.
        if all of the images exist and are current, return
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        config = self.get_containerset_config()

        if not self.image_exists('wikimedia-dumps/snapshot:latest'):
            if self.verbose:
                print("building snapshot image for", self.args['set'])
                client.images.build(path=os.path.join(os.getcwd(), 'docker_helpers'), rm=True,
                                    dockerfile='Dockerfile.snapshot',
                                    tag='wikimedia-dumps/snapshot:latest',
                                    labels=self.get_blame_label())

        if not self.image_exists('wikimedia-dumps/mariadb:latest'):
            if self.verbose:
                print("building mariadb image for", self.args['set'])
                client.images.build(path=os.path.join(os.getcwd(), 'docker_helpers'), rm=True,
                                    dockerfile='Dockerfile.mariadb',
                                    tag='wikimedia-dumps/mariadb:latest',
                                    labels=self.get_blame_label())

        if config['nfs']:
            if not self.image_exists('wikimedia-dumps/dumpsdata:latest'):
                if self.verbose:
                    print("building dumspdata image for", self.args['set'])
                client.images.build(path=os.path.join(os.getcwd(), 'docker_helpers'), rm=True,
                                    dockerfile='Dockerfile.dumpsdata',
                                    tag='wikimedia-dumps/dumpsdata:latest',
                                    labels=self.get_blame_label())

        if config['httpd']:
            if not self.image_exists('wikimedia-dumps/httpd:latest'):
                if self.verbose:
                    print("building httpd image for", self.args['set'])
                client.images.build(path=os.path.join(os.getcwd(), 'docker_helpers'), rm=True,
                                    dockerfile='Dockerfile.httpd',
                                    tag='wikimedia-dumps/httpd:latest',
                                    labels=self.get_blame_label())

    def create_one_container(self, name, image, labels, client):
        '''
        create a container with the standard attributes given
        the desired container name, labels and image name
        '''
        client.containers.create(
            image=image,
            name=name, detach=True, labels=labels,
            domainname=self.get_network_name(),
            network=self.get_network_name())

    def do_create(self):
        '''
        create containers associated with a wikifarm set.
        If the containers already exist for this set, raise an exception
        '''
        if self.verbose:
            print("creating network if needed")
        self.create_network()

        client = DockerClient(base_url='unix://var/run/docker.sock')
        config = self.get_containerset_config()

        labels = self.get_set_label().copy()
        labels.update(self.get_blame_label())

        # snapshot containers
        if config['snapshots']:
            if config['snapshots'] > 99:
                raise ValueError("You want more than 99 snapshot images?"
                                 " On one host? Really? Yeahnope.")
            for i in range(config['snapshots']):
                name = self.args['set'] + "-snap-{:02d}".format(i + 1)
                self.create_one_container(
                    name, 'wikimedia-dumps/snapshot:latest', labels, client)

        # mariadb primary server container
        name = self.args['set'] + "-db-primary"
        self.create_one_container(
            name, 'wikimedia-dumps/mariadb:latest', labels, client)

        # mariadb replica containers
        if config['dbreplicas']:
            if config['dbreplicas'] > 99:
                raise ValueError("Come on. Get real. You are not going to run"
                                 " even 99 db replicas on one host. Just no.")
            for i in range(config['dbreplicas']):
                name = self.args['set'] + "-db-{:02d}".format(i + 1)
                # FIXME this image does not yet exist
                self.create_one_container(
                    name, 'wikimedia-dumps/mariadb-replica:latest', labels, client)

        # httpd container
        if config['httpd']:
            name = self.args['set'] + "-httpd"
            # FIXME this image does not yet exist
            self.create_one_container(
                name, 'wikimedia-dumps/httpd:latest', labels, client)

        # nfs server (dumpsdata) container
        if config['nfs']:
            name = self.args['set'] + "-dumpsdata"
            # FIXME this image does not yet exist
            self.create_one_container(
                name, 'wikimedia-dumps/dumpsdata:latest', labels, client)

    def do_destroy(self, label=None):
        '''
        destroy containers associated with a wikifarm set.
        If the containers do not exist for this set, just return
        '''
        container_ids = self.get_container_ids(label)
        client = DockerClient(base_url='unix://var/run/docker.sock')
        for entry in container_ids:
            container = client.containers.get(entry)
            if self.verbose:
                print("stopping container:", entry)
            container.stop()
            if self.verbose:
                print("removing container:", entry)
            container.remove()

    def do_remove(self):
        '''
        remove base images, first destroying ALL containers.
        that's right, all of them for all sets.
        we also remove the network for the specific set.
        If images do not exist, just return
        '''
        if self.verbose:
            print("removing all containers for all sets.")
        self.do_destroy(self.get_blame_label())
        self.remove_network()
        client = DockerClient(base_url='unix://var/run/docker.sock')

        if self.image_exists('wikimedia-dumps/snapshot:latest'):
            if self.verbose:
                print("removing snapshot image")
            client.images.remove('wikimedia-dumps/snapshot:latest')

        if self.image_exists('wikimedia-dumps/mariadb:latest'):
            if self.verbose:
                print("removing mariadb image")
            client.images.remove('wikimedia-dumps/mariadb:latest')

        if self.image_exists('wikimedia-dumps/dumpsdata:latest'):
            if self.verbose:
                print("removing dumpsdata image")
            client.images.remove('wikimedia-dumps/dumpsdata:latest')

        if self.image_exists('wikimedia-dumps/httpd:latest'):
            if self.verbose:
                print("removing httpd image")
            client.images.remove('wikimedia-dumps/httpd:latest')

    def do_start(self):
        '''
        start containers associated with a wikifarm set.
        If the containers do not exist for this set, raise an exception
        '''
        container_ids = self.get_container_ids()
        print("got these ids:", container_ids)
        client = DockerClient(base_url='unix://var/run/docker.sock')
        for entry in container_ids:
            container = client.containers.get(entry)
            if self.verbose:
                print("starting container:", entry)
            container.start()

    def do_stop(self):
        '''
        stop containers associated with a wikifarm set.
        If the containers do not exist for this set, just return
        '''
        container_ids = self.get_container_ids()
        client = DockerClient(base_url='unix://var/run/docker.sock')
        for entry in container_ids:
            container = client.containers.get(entry)
            if self.verbose:
                print("stopping container:", entry)
            container.stop()

    def do_command(self):
        '''
        run the appropriate command
        '''
        if self.args['command'] == 'list':
            self.do_list()
        elif self.args['command'] == 'build':
            self.do_build()
        elif self.args['command'] == 'start':
            self.do_start()
        elif self.args['command'] == 'create':
            self.do_create()
        elif self.args['command'] == 'stop':
            self.do_stop()
        elif self.args['command'] == 'destroy':
            self.do_destroy()
        elif self.args['command'] == 'remove':
            self.do_remove()


def usage(message=None):
    '''
    display a nice usage message along with an optional message
    describing an error
    '''
    if message:
        sys.stderr.write(message + "\n")
    usage_message = """Usage: $0 --build|create|list|start|stop|destroy|remove <setname>
        or --test <testname>
       [--config <path>] [--verbose]
or: $0 --help

Create, manage, and destroy a wikifarm of images/containers for testing xml/sql
dumps on MediaWiki, as well as run specific tests.

Container setup is defined in the configuration; see default.conf for documentation
and the default values for every setting.  Multiple such definitions may be defined
in the configuration file; each such definition is a "container set".

Arguments:

 --build   (-b):  build images needed for containers for the specified container set
 --create  (-c):  create containers in the specified container set for sql/xml dump tests
 --list    (-l):  list containers created for the wikifarm in the specified set
 --start   (-s):  start up the containers for the wikifarm in the specified set
 --test    (-t):  run the specified test as defined in the specified set
 --stop    (-S):  stop the containers for the wikifarm in the specified set
 --destroy (-d):  destroy the containers in the specified set
 --remove  (-r):  remove the images for the containers in the specified set
                  all running containers for this set will be stopped and destroyed first
 --config  (-C):  path to configuration file. settings in this file will override
                  settings in default.conf
                  default value: './docker-dumps.conf' in the current working directory

Flags:

 --verbose (-v):  write some progress messages some day
 --help    (-h):  show this help message
"""
    sys.stderr.write(usage_message)
    sys.exit(1)


def get_default_opts():
    '''
    initialize args with default values and return them
    set: a collection of containers defined in the config for one wikifarm
    test: a name for a specific test defined in the config and associated with a wikifarm
    '''
    args = {'configfile': None, 'command': None, 'set': None, 'test': None, 'verbose': False}
    return args


def check_opts(args):
    '''
    whine if mandatory args not supplied
    '''
    if 'command' not in args or not args['command']:
        usage("One of the args 'build', 'create', 'list', 'start', 'stop',"
              " 'test', 'remove' or 'destroy' must be specified")


def process_opts():
    '''
    get command-line args and values, falling back to defaults
    where needed, whining about bad args
    '''
    commands = {'b:': 'build', 'c': 'create', 'l': 'list', 's': 'start', 'S': 'stop',
                'd': 'destroy', 'r': 'remove'}
    try:
        (options, remainder) = getopt.gnu_getopt(
            sys.argv[1:], "C:t:b:c:l:s:S:d:r:vh",
            ["config=", "test=", "build=", "create=", "list=", "start=",
             "stop=", "destroy=", "remove=", "verbose", "help"])

    except getopt.GetoptError as err:
        usage("Unknown option specified: " + str(err))

    args = get_default_opts()

    for (opt, val) in options:
        if opt[1:] in commands.keys():
            args['command'] = opt[1:]
            args['set'] = val
        elif opt[2:] in commands.values():
            args['command'] = opt[2:]
            args['set'] = val
        elif opt in ["-t", "--test"]:
            args['command'] = 'test'
            args['test'] = val
        elif opt in ["-C", "--config"]:
            args['config'] = val
        elif opt in ["-v", "--verbose"]:
            args['verbose'] = True
        elif opt in ["-h", "--help"]:
            usage('Help for this script\n')
        else:
            usage("Unknown option specified: <%s>" % opt)

    if remainder:
        usage("Unknown option(s) specified: {opt}".format(opt=remainder[0]))

    check_opts(args)
    return args


def get_config(configfilepath, verbose):
    '''
    read and return the config settings from the specified
    file, falling back to defaults where needed
    '''
    values = {}

    if configfilepath:
        try:
            with open(configfilepath, "r") as fhandle:
                contents = fhandle.read()
                values = yaml.safe_load(contents)
        except (FileNotFoundError, PermissionError):
            pass

    if not values:
        configfilepath = os.path.join(os.getcwd(), 'default.conf')
        with open(configfilepath, "r") as fhandle:
            contents = fhandle.read()
            values = yaml.safe_load(contents)

    if verbose:
        print("configuration:", values)
    return values


def do_main():
    '''entry point'''
    args = process_opts()
    config = get_config(args['configfile'], args['verbose'])
    wikifarm = WikifarmSets(args, config, args['verbose'])
    wikifarm.do_command()


if __name__ == '__main__':
    do_main()
