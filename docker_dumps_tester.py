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


class ContainerLabels():
    '''manage various labels for containers and networks'''
    def __init__(self, args):
        self.args = args

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

    @staticmethod
    def has_labels(labels, labels_wanted):
        '''check that the one bleep of labels has all the other ones in it'''
        for key, value in labels_wanted.items():
            if key not in labels or labels[key] != value:
                return False
        return True


class Networks():
    '''manage various aspects of container set networks'''
    def __init__(self, args, labeler):
        self.args = args
        self.verbose = args['verbose']
        self.labeler = labeler

    def get_network_name(self):
        '''
        return the network name, at this point we have it end in '.lan'
        and maybe that should be configurable. FIXME?
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
            if (entry.name == self.args['set'] + ".lan" and
                    self.labeler.has_labels(entry.attrs['Labels'], self.labeler.get_set_label())):
                if self.verbose:
                    print("Network already exists.")
                return
            # collect the address space info
            for settings in entry.attrs['IPAM']['Config']:
                if 'Subnet' in settings and settings['Subnet'].startswith('172.'):
                    ip_spaces.append(settings['Subnet'])

        if self.verbose:
            print("ip spaces already used:", ip_spaces)
        possible = netaddr.IPSet(['172.16.0.0/12'])
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
        labels = self.labeler.get_set_label().copy()
        labels.update(self.labeler.get_blame_label())
        client.networks.create(self.get_network_name(), driver="bridge",
                               labels=labels, ipam=ipam_config)

    @staticmethod
    def get_all_networks():
        '''return list of all the networks defined on this host'''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        networks = client.networks.list()
        return networks

    def remove_network(self, labels=None, network=None):
        '''
        if there is a network defined for the set, remove it
        if a specific network name is passed in, try to remove that

        note that if there are multiple networks defined for the set
        because someone created one or more manually, they all get removed.

        if we specify a dict of labels, then just remove every network
        with all of those labels
        '''
        networks = self.get_all_networks()
        if labels:
            for entry in networks:
                if self.labeler.has_labels(entry.attrs['Labels'], labels):
                    if self.verbose:
                        print("Removing network")
                        entry.remove()
        else:
            for entry in networks:
                if ((network and entry.name == network) or
                    (entry.name == self.get_network_name()) and
                        self.labeler.has_labels(entry.attrs['Labels'],
                                                self.labeler.get_set_label())):
                    if self.verbose:
                        print("Removing network")
                        entry.remove()


class ContainerConfig():
    '''manage the config for the container set'''
    def __init__(self, configpath, verbose):
        self.verbose = verbose
        self.config = self.get_config(configpath)

    def get_config(self, configfilepath):
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

        if self.verbose:
            print("configuration:", values)
        return values

    def get_containerset_config(self, setname):
        '''get the config settings for the specified wikifarm set'''
        for entry in self.config['sets']:
            if entry == setname:
                return self.config['sets'][entry]
        return [{}]

    def container_configured(self, image_name, set_name):
        '''check that the desired container type is configured in the specified container set'''
        config = self.get_containerset_config(set_name)
        if image_name == 'dumpsdata':
            return bool(config['dumpsdata'])
        if image_name == 'httpd':
            return bool(config['httpd'])
        if image_name == 'phpfpm':
            return bool(config['httpd'])
        if image_name == 'dbreplica':
            return bool(config['dbreplicas'])
        if image_name == 'dbextstore':
            return bool(config['dbextstore'])
        return True

    def get_set_container_names(self, set_name, net_name):
        '''
        based on the configuration, generate all of the container names the
        set will have once instantiated; these names are used in building
        final images
        '''
        containers = []
        config = self.get_containerset_config(set_name)

        if config['snapshots']:
            containers.extend(
                [set_name + "-snapshot-{:02d}.{net}.lan".format(i + 1, net=net_name)
                 for i in range(config['snapshots'])])
        containers.append(set_name + "-dbprimary.{net}".format(net=net_name))
        if config['dbreplicas']:
            containers.extend(
                [set_name + "-db-{:02d}.{net}".format(i + 1, net=net_name)
                 for i in range(config['dbreplicas'])])
        if config['httpd']:
            containers.append(set_name + "-httpd.{net}".format(net=net_name))
            containers.append(set_name + "-phpfpm.{net}".format(net=net_name))
        if config['dumpsdata']:
            containers.append(set_name + "-dumpsdata.{net}".format(net=net_name))

        return containers

    def write_container_set_names(self, set_name, net_name):
        '''generate the list of container names for this set and write them to a file'''
        container_names = self.get_set_container_names(set_name, net_name)
        container_list_path = os.path.join(os.getcwd(), 'docker_helpers',
                                           'container_list.' + set_name)
        with open(container_list_path, "w") as fhandle:
            fhandle.write('\n'.join(container_names) + '\n')

    def show_known_sets(self):
        '''
        display the sets we know about from the config.
        this does not mean that any containers or images in these sets exist.
        '''
        print("Known sets:", ', '.join(list(self.config['sets'].keys())))


class Images():
    '''
    manage the build and removal of images as defined in a config
    '''
    def __init__(self, args, config, labeler, networks):
        self.args = args
        self.verbose = args['verbose']
        self.labeler = labeler
        self.nets = networks
        self.config = config

    def image_exists(self, tag):
        '''check if the image with the specific tag in the container set exists'''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.images.list('all')
        for entry in entries:
            if self.labeler.has_blame_label(entry) and tag in entry.tags:
                return True
        return False

    @staticmethod
    def get_known_image_types():
        '''these are the image types we know how to build'''
        return ['snapshot', 'dbprimary', 'dbreplica', 'dbextstore', 'dumpsdata', 'httpd', 'phpfpm']

    def do_basest_base_build(self, client):
        '''build the base image for all other base images.'''

        # this is the basest of all base images :-P
        base_image = 'wikimedia-dumps/base:latest'
        do_squash = self.config.config['squash']
        if not self.image_exists(base_image):
            path = os.path.join(os.getcwd(), 'docker_helpers')
            dockerfile = 'Dockerfile.base'
            if self.verbose:
                print("building base image for all images in " + self.args['set'])
            try:
                client.images.build(
                    path=path,
                    rm=True,
                    forcerm=True,
                    dockerfile=dockerfile,
                    tag=base_image,
                    squash=do_squash,
                    labels=self.labeler.get_blame_label())
            except docker.errors.BuildError as error:
                print("BUILD FAILED for base image for all images in " + self.args['set'])
                for line in error.build_log:
                    print(line)
                raise

    def do_base_build(self):
        '''
        build base images needed for the containers associated with a wikifarm set.
        these will be independent of network names and eventual container names.
        if all of the images exist and are current, return
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        self.do_basest_base_build(client)

        todos = self.get_known_image_types()
        if self.args['name']:
            todos = [self.args['name']]
        do_squash = self.config.config['squash']
        for image_name in todos:
            base_image = 'wikimedia-dumps/{name}-base:latest'.format(name=image_name)
            if self.config.container_configured(image_name, self.args['set']):
                if not self.image_exists(base_image):
                    path = os.path.join(os.getcwd(), 'docker_helpers')
                    dockerfile = 'Dockerfile.' + image_name + '-base'

                    # see, a bunch of these don't exist yet :-P :-P FIXME by removing later.
                    if not os.path.exists(os.path.join(path, dockerfile)):
                        if self.verbose:
                            print("skipping build of {name} base image, no Dockerfile yet".format(
                                name=image_name))
                        continue

                    if self.verbose:
                        print("building {name} base image for".format(name=base_image),
                              self.args['set'])
                        try:
                            client.images.build(
                                path=path,
                                rm=True,
                                forcerm=True,
                                dockerfile=dockerfile,
                                tag=base_image,
                                squash=do_squash,
                                labels=self.labeler.get_blame_label())
                        except docker.errors.BuildError as error:
                            print("BUILD FAILED for {name} base image in {setname}".format(
                                name=image_name, setname=self.args['set']))
                            for line in error.build_log:
                                print(line)
                            raise

    def do_final_build(self):
        '''
        build final images needed for the containers associated with a wikifarm set.
        these will be dependent on the network name and eventual container names.
        this will also build base images if required.
        if all of the images exist and are current, return
        '''
        self.do_base_build()

        client = DockerClient(base_url='unix://var/run/docker.sock')

        # all known container names in this set go into a file that can be
        # COPYed into the docker image and the values used by a script during
        # the build
        self.config.write_container_set_names(self.args['set'], self.nets.get_network_name())

        todos = self.get_known_image_types()
        if self.args['name']:
            todos = [self.args['name']]
        do_squash = self.config.config['squash']
        for image_name in todos:
            final_image = 'wikimedia-dumps/{name}-{setname}-final:latest'.format(
                name=image_name, setname=self.args['set'])
            if self.config.container_configured(image_name, self.args['set']):
                if not self.image_exists(final_image):
                    path = os.path.join(os.getcwd(), 'docker_helpers')
                    dockerfile = 'Dockerfile.' + image_name + '-final'

                    # see, a bunch of these don't exist yet :-P :-P FIXME by removing later.
                    if not os.path.exists(os.path.join(path, dockerfile)):
                        if self.verbose:
                            print("skipping build of {name} final image, no Dockerfile yet".format(
                                name=image_name))
                        continue

                    if self.verbose:
                        print("building {name} final image for".format(name=final_image),
                              self.args['set'])
                        try:
                            client.images.build(
                                path=path,
                                rm=True,
                                forcerm=True,
                                dockerfile=dockerfile,
                                tag=final_image,
                                labels=self.labeler.get_blame_label(),
                                squash=do_squash,
                                buildargs={'SETNAME': self.args['set']})
                        except docker.errors.BuildError as error:
                            print("BUILD FAILED for {name} final image in {setname}".format(
                                name=image_name, setname=self.args['set']))
                            for line in error.build_log:
                                print(line)
                            raise

    def do_purge(self):
        '''
        purge all base images, first destroying all containers for all
        sets, and all final images for all sets.
        we also remove all the networks for all sets.
        If images do not exist, just return
        '''
        if self.verbose:
            print("removing all base images for all sets.")
        networks = self.nets.get_all_networks()

        client = DockerClient(base_url='unix://var/run/docker.sock')
        for network in networks:
            self.do_remove(network)

        for image_name in ['snapshot', 'dbprimary', 'dbpreplica', 'dumpsdata', 'httpd', 'phpfpm']:
            base_image = 'wikimedia-dumps/{name}-base:latest'.format(name=image_name)
            if self.image_exists(base_image):
                if self.verbose:
                    print("removing {name} image".format(name=base_image))
            client.images.remove(base_image)

    def do_remove(self, network=None):
        '''
        remove all final images for this container set, first destroying
        all the containers for this set.
        we also remove the network for this set.
        If images do not exist, just return
        '''
        if self.verbose:
            print("removing all base images for this container set")
        self.nets.remove_network(network=network)

        client = DockerClient(base_url='unix://var/run/docker.sock')

        for image_name in ['snapshot', 'dbprimary', 'dbreplica', 'dumpsdata', 'httpd', 'phpfpm']:
            final_image = 'wikimedia-dumps/{name}-{setname}-final:latest'.format(
                name=image_name, setname=self.args['set'])
        if self.image_exists(final_image):
            if self.verbose:
                print("removing {name} image".format(name=image_name))
            client.images.remove(final_image)

    def image_in_set(self, entry):
        '''check if an image is a final image in our set'''
        for tag in entry.tags:
            if tag.endswith('-' + self.args['set'] + '-final:latest'):
                return True
        return False

    @staticmethod
    def image_is_base(entry):
        '''check if an image is a base image (used to build final images for all sets'''
        for tag in entry.tags:
            if tag.endswith('-base:latest'):
                return True
        return False

    def do_list(self, show_all=False):
        '''
        list all of the images belonging to the specified set, or all sets
        if show_all is True
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')

        displayed = False
        entries = client.images.list('all')
        for entry in entries:
            if self.labeler.has_blame_label(entry):
                if show_all or self.image_in_set(entry) or self.image_is_base(entry):
                    displayed = True
                    tags = ','.join(entry.tags)
                    if not tags:
                        # skip intermediate cached images, no one cares about them
                        continue
                    print("image:  id ({short_id}) tags {tags}".format(
                        short_id=entry.short_id, tags=tags))
        if not displayed:
            print("<None>")


class Containers():
    '''manage the creation, destruction, starting and stoppping of containers as
    defined in a config'''
    def __init__(self, args, config, labeler, networks):
        self.args = args
        self.verbose = args['verbose']
        self.labeler = labeler
        self.nets = networks
        self.config = config

    @staticmethod
    def get_known_container_types():
        '''these are the image types we know how to build'''
        return ['snapshot', 'adbprimary', 'dbreplica', 'dbextstore', 'dumpsdata', 'httpd', 'phpfpm']

    def do_list(self, show_all=False):
        '''
        list all of the containers belonging to the specified set
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.containers.list('all')
        displayed = False
        padding = max([len(entry.name) for entry in entries])
        for entry in entries:
            if 'set' in entry.labels:
                if show_all or self.args['set'] in entry.labels['set']:
                    displayed = True
                    print("container: {name} ({short_id}), status: {status}, from: {image}".format(
                        name=entry.name.ljust(padding + 3),
                        image=entry.attrs['Config']['Image'],
                        short_id=entry.short_id, status=entry.status))
        if not displayed:
            print("<None>")

    def get_container_ids(self, labels=None):
        '''return short ids of the containers for the given set'''
        containers = []
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.containers.list('all')
        if labels:
            for entry in entries:
                if self.labeler.has_labels(entry.labels, labels):
                    containers.append(entry.short_id)
        else:
            for entry in entries:
                print(entry.labels, entry.name)
                if self.labeler.has_labels(entry.labels, self.labeler.get_set_label()):
                    containers.append(entry.short_id)
        return containers

    def container_exists(self, short_id):
        '''check if the container with the specified id from a container set exists'''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.containers.list('all')
        for entry in entries:
            if self.labeler.has_labels(entry.labels, self.labeler.get_set_label()):
                if entry.short_id == short_id:
                    return True
        return False

    def container_exists_by_name(self, name, containers_known=None):
        '''check if the container with the specified name from a container set exists'''
        if not containers_known:
            client = DockerClient(base_url='unix://var/run/docker.sock')
            containers_known = client.containers.list('all')
        for entry in containers_known:
            if self.labeler.has_labels(entry.labels, self.labeler.get_set_label()):
                if entry.name == name:
                    return True
        return False

    def get_container_ids_from_name(self, name, containers_known=None):
        '''check if the container with the specified name from a container set exists'''
        container_ids = []
        if not containers_known:
            client = DockerClient(base_url='unix://var/run/docker.sock')
            containers_known = client.containers.list('all')
        for entry in containers_known:
            if self.labeler.has_labels(entry.labels, self.labeler.get_set_label()):
                # allow for names like <setname>-snapshot-nn
                if (entry.name == self.args['set'] + '-' + name or
                        entry.name.startswith(self.args['set'] + '-' + name + '-')):
                    container_ids.append(entry.short_id)
        if container_ids:
            return container_ids
        return None

    def create_one_container(self, name, image, client, containers_known=None):
        '''
        create a container with the standard attributes given
        the desired container name, labels and image name
        '''
        labels = self.labeler.get_set_label().copy()
        labels.update(self.labeler.get_blame_label())

        if not self.container_exists_by_name(name, containers_known):
            client.containers.create(
                image=image,
                name=name, detach=True, labels=labels,
                domainname=self.nets.get_network_name(),
                network=self.nets.get_network_name())

    def check_and_create(self, opts, client, containers_known):
        '''
        check that we are configured to create this container type,
        and that an absurd number of containers was not requested;
        if so, create it with the appropriate name from the right
        image and return

        the opts passed in should look like:
        {'config': config key for container,
         'max': None or max number of containers to create,
         'basename': container basename e.g. "snapshot",
         'image': image basename e.g. "snapshot"}
        '''

        config = self.config.get_containerset_config(self.args['set'])

        container_config = config[opts['config']]
        if container_config:
            if opts['max']:
                if container_config > opts['max']:
                    raise ValueError("You want more than {maxnum} {imagetype} images?"
                                     " On one host? Really? Yeahnope.".format(
                                         maxnum=opts['max'], imagetype=opts['image']))
                for i in range(container_config):
                    name = self.args['set'] + "-{name}-{:02d}".format(i + 1, name=opts['basename'])
                    self.create_one_container(
                        name, 'wikimedia-dumps/{name}-{setname}-final:latest'.format(
                            name=opts['image'], setname=self.args['set']),
                        client, containers_known)
            else:
                name = self.args['set'] + "-{name}".format(name=opts['basename'])
                self.create_one_container(
                    name, 'wikimedia-dumps/{name}-{setname}-final:latest'.format(
                        name=opts['image'], setname=self.args['set']),
                    client, containers_known)

    def do_create(self):
        '''
        create containers associated with a wikifarm set.
        if final images or base images need to be built first, do so
        If the containers already exist for this set, raise an exception
        '''

        if self.verbose:
            print("creating network if needed")
        self.nets.create_network()

        client = DockerClient(base_url='unix://var/run/docker.sock')
        containers_known = client.containers.list('all')

        if self.args['name']:
            todos = [self.args['name']]
        else:
            todos = self.get_known_container_types()

        # snapshot containers
        if 'snapshot' in todos:
            self.check_and_create({'config': 'snapshots', 'max': 99,
                                   'basename': 'snapshot', 'image': 'snapshot'},
                                  client, containers_known)

        # mariadb primary server container
        if 'dbprimary' in todos:
            self.check_and_create({'config': 'dbprimary', 'max': None,
                                   'basename': 'dbprimary', 'image': 'dbprimary'},
                                  client, containers_known)

        # mariadb replica containers
        # FIXME no image yet
        if 'dbreplica' in todos:
            self.check_and_create({'config': 'dbreplicas', 'max': 99,
                                   'basename': 'db', 'image': 'dbreplica'},
                                  client, containers_known)

        # external storage (content blobs) container
        # FIXME no image yet
        if 'dbextstore' in todos:
            self.check_and_create({'config': 'dbextstore', 'max': None,
                                   'basename': 'dbextstore', 'image': 'dbextstore'},
                                  client, containers_known)

        # httpd container
        if 'httpd' in todos:
            self.check_and_create({'config': 'httpd', 'max': None,
                                   'basename': 'httpd', 'image': 'httpd'},
                                  client, containers_known)

        # phpfpm container
        if 'phpfpm' in todos:
            self.check_and_create({'config': 'phpfpm', 'max': None,
                                   'basename': 'phpfpm', 'image': 'phpfpm'},
                                  client, containers_known)

        # nfs server (dumpsdata) container
        # FIXME no image yet
        if 'dumpsdata' in todos:
            self.check_and_create({'config': 'dumpsdata', 'max': None,
                                   'basename': 'dumpsdata', 'image': 'dumpsdata'},
                                  client, containers_known)

    def do_destroy(self, do_all=False):
        '''
        destroy containers associated with a wikifarm set or with
        all wikifarms.
        If the desired containers do not exist, just return
        '''
        label = None
        if do_all:
            label = self.labeler.get_blame_label()

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
        return True

    def do_start(self):
        '''
        start containers associated with a wikifarm set.
        this will create the containers if needed.
        '''
        self.do_create()

        client = DockerClient(base_url='unix://var/run/docker.sock')
        containers_known = client.containers.list('all')

        if self.args['name']:
            container_ids = self.get_container_ids_from_name(self.args['name'], containers_known)
        else:
            container_ids = self.get_container_ids()

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


class WikifarmSets():
    '''
    manage the build and running of images and containers as defined
    in a config
    '''
    def __init__(self, args, images, containers):
        self.args = args
        self.verbose = args['verbose']
        self.images = images
        self.containers = containers

    def show_wikifarm_info(self):
        '''display the sets, images and containers known for all wikifarms'''
        self.containers.config.show_known_sets()
        print("Known containers:")
        self.containers.do_list(show_all=True)
        print("Known images:")
        self.images.do_list(show_all=True)

    def do_command(self):
        '''
        run the appropriate command
        '''
        if 'command' not in self.args:
            self.show_wikifarm_info()
            return

        if self.args['command'] == 'list':
            self.containers.do_list()
        elif self.args['command'] == 'build':
            self.images.do_final_build()
        elif self.args['command'] == 'base':
            self.images.do_base_build()
        elif self.args['command'] == 'start':
            self.images.do_final_build()
            self.containers.do_start()
        elif self.args['command'] == 'create':
            self.images.do_final_build()
            self.containers.do_create()
        elif self.args['command'] == 'stop':
            self.containers.do_stop()
        elif self.args['command'] == 'destroy':
            self.containers.do_destroy()
        elif self.args['command'] == 'remove':
            self.containers.do_destroy()
            self.images.do_remove()
        elif self.args['command'] == 'purge':
            # we are removing all base images for the wiki set, but
            # containers in the other sets depend on them too so they
            # must also be destroyed
            self.containers.do_destroy(do_all=True)
            self.images.do_purge()


class DumpsTestbedOpts():
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
            usage_message = """Usage: $0 <command> <setname>
        or --test <testname>
       [--name <image/container type>] [--config <path>] [--verbose]
or: $0 --help

Create, manage, and destroy a wikifarm of images/containers for testing xml/sql
dumps on MediaWiki, as well as run specific tests.

Container setup is defined in the configuration; see default.conf for documentation
and the default values for every setting.  Multiple such definitions may be defined
in the configuration file; each such definition is a "container set".

To give a <command>, supply one of the folllowing, followed by the <setname>:
  --base|build|create|list|start|stop|destroy|remove

Note that this script does not try to recreate existing containers or rebuild
existing images. If you update a Dockerfile or a script or config file used
in the image, you will need to remove the image and any containers that rely
 upon it, before rebuilding. A reminder that you can run 'docker images -a' and
and 'docker ls -a' to see the list of images or containers, and the commands
 'docker rm <container>' or 'docker rmi <image>' will remove the container or image
 in question.

Arguments:

 --base    (-B):  build base images needed for containers for the specified container set
 --build   (-b):  build final images needed for containers for the specified container set
                  also do the base build if needed
 --create  (-c):  create containers in the specified container set for sql/xml dump tests
                  also do the base and final image builds if needed
 --start   (-s):  start up the containers for the wikifarm in the specified set
                  also do container creation if needed
 --name    (-n):  build the specified base or final image, where 'name' is one of
                  the image or container types in the set ('snapshot', 'httpd', 'dumpsdata' (nfs),
                  'dbextstore', 'dbreplica', 'phpfpm', 'dbprimary'), or create or start the specified
                  container(s) in the set
                  this option is only valied with --base, --build, --create or --start and will be
                  ignored in all other cases
 --list    (-l):  list containers created for the wikifarm in the specified set
 --stop    (-S):  stop the containers for the wikifarm in the specified set
 --destroy (-d):  destroy the containers in the specified set
 --remove  (-r):  remove the final images for the containers in the specified set
                  all running containers for this set will be stopped and destroyed first
 --purge   (-p):  purge the base images for the containers in the specified set
                  all running containers for this set will be stopped and destroyed first
                  and all final images for this set will also be removed
 --test    (-t):  run the specified test as defined in the specified set
 --config  (-C):  path to configuration file. settings in this file will override
                  settings in default.conf
                  default value: './docker-dumps.conf' in the current working directory

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
        args = {'configfile': None, 'set': None, 'test': None,
                'name': None, 'verbose': False}
        return args

    def check_opts(self, args):
        '''
        validate opts and make sure we have the mandatory ones
        '''
        # note that if args['command'] was never set, we leave that to the caller
        # to handle. the caller, for example, may decide to show all known sets to the user.
        if 'command' in args and not args['command']:
            self.usage("One of the args 'base', 'build', 'create', 'list', 'start', 'stop', "
                       "'test', 'remove' or 'destroy' must be specified")
        if args['name'] and args['name'] not in ['snapshot', 'httpd', 'dumpsdata', 'dbextstore',
                                                 'dbreplica', 'phpfpm', 'dbprimary']:
            self.usage("Unknown container type " + args['name'] + " specified.")

    def process_opts(self):
        '''
        get command-line args and values, falling back to defaults
        where needed, whining about bad args
        '''
        commands = {'B': 'base', 'b:': 'build', 'c': 'create', 'l': 'list', 's': 'start',
                    'S': 'stop', 'd': 'destroy', 'r': 'remove'}
        try:
            (options, remainder) = getopt.gnu_getopt(
                sys.argv[1:], "C:t:b:B:c:l:s:S:n:d:r:vh",
                ["config=", "test=", "base=", "build=", "create=", "name=", "list=", "start=",
                 "stop=", "destroy=", "remove=", "verbose", "help"])

        except getopt.GetoptError as err:
            self.usage("Unknown option specified: " + str(err))

        args = self.get_default_opts()

        for (opt, val) in options:
            if opt[1:] in commands.keys():
                args['command'] = opt[1:]
                args['set'] = val
            elif opt[2:] in commands.values():
                args['command'] = opt[2:]
                args['set'] = val
            elif opt in ["-n", "--name"]:
                args['name'] = val
            elif opt in ["-t", "--test"]:
                args['command'] = 'test'
                args['test'] = val
            elif opt in ["-C", "--config"]:
                args['config'] = val
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


def do_main():
    '''entry point'''
    opts = DumpsTestbedOpts()
    args = opts.process_opts()
    config = ContainerConfig(args['configfile'], args['verbose'])
    labeler = ContainerLabels(args)
    networks = Networks(args, labeler)
    images = Images(args, config, labeler, networks)
    containers = Containers(args, config, labeler, networks)
    wikifarm = WikifarmSets(args, images, containers)
    wikifarm.do_command()


if __name__ == '__main__':
    do_main()
