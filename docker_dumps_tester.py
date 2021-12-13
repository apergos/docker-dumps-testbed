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

    def get_set_label_string(self):
        '''this is the set label that goes on containers and stuff, as a key=value string.'''
        return 'set=' + self.args['set']

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

        default_configfilepath = os.path.join(os.getcwd(), 'default.conf')
        with open(default_configfilepath, "r") as fhandle:
            contents = fhandle.read()
            defaults = yaml.safe_load(contents)

        if configfilepath:
            try:
                with open(configfilepath, "r") as fhandle:
                    contents = fhandle.read()
                    values = yaml.safe_load(contents)
            except (FileNotFoundError, PermissionError):
                print("Missing or bad permissions for config file", configfilepath, "Giving up")
                raise

        # missing or empty sets in the user defined config
        # are filled in with the default config sets;
        # it is not permitted to configure no sets at all.
        if 'sets' not in values or not values['sets']:
            values['sets'] = defaults['sets']

        # missing globals in the user defined config are filled
        # in with the default globals; an empty globals stanza in
        # the user-defined config is left as is, so that there is
        # a way for the user to not have global values.
        if 'global' not in values:
            values['global'] = defaults['global']

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
                [set_name + "-snapshot-{:02d}.{net}".format(i + 1, net=net_name)
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

    @staticmethod
    def retrieve_value(config, key_names):
        '''
        given a a configuration in the form of a nested dict, and a
        list of the names of the keys and subkeys in order,
        return the value if there is such an entry, or None otherwise
        '''
        if not config:
            return None
        subtree = config
        for kname in key_names:
            if kname not in subtree:
                return None
            subtree = subtree[kname]
        # typically this will be a plain value and not a tree but we
        # don't care
        return subtree

    def write_creds_file(self, setname, path):
        '''
        write a yaml file to the specified output path consisting of
        various credentials for users on the containers in the set
        as well as the list of dbs on which the db creds will be good

        we know that defaults have already been filled in where appropriate
        in the constructor, so we don't have to worry about that.

        we fall back to users defined in the global stanza if a user-provided
        config for a set has no users and either has global users defined or has
        no globals stanza at all, in which case we will have those filled in from
        the default cnofig.

        if there is no such set we silently return. hrm.
        '''
        set_config = self.get_containerset_config(setname)
        if not set_config:
            return
        globals_config = self.config['global']

        contents = []
        root_password = self.retrieve_value(set_config, ['passwords', 'containers', 'root'])
        if not root_password:
            root_password = self.retrieve_value(globals_config, ['passwords', 'containers', 'root'])
        if not root_password:
            print("A root password for containers must be specified in your configuration")
            sys.exit(1)
        contents.append("rootuser: " + root_password)

        rootdbuser_password = self.retrieve_value(set_config, ['passwords', 'dbs', 'root'])
        if not rootdbuser_password:
            rootdbuser_password = self.retrieve_value(globals_config, ['passwords', 'dbs', 'root'])
        if not rootdbuser_password:
            print("A root password for the db must be specified in your configuration")
            sys.exit(1)
        contents.append("rootdbuser: " + rootdbuser_password)

        contents.append("wikidbusers:")
        for dbuser_name in set_config['passwords']['dbs']:
            if dbuser_name == 'root':
                continue

            dbuser_password = self.retrieve_value(set_config, ['passwords', 'dbs', dbuser_name])
            if not dbuser_password:
                print("If a db user is specified in your config, it must have a password.")
                sys.exit(1)
            contents.append("  - " + dbuser_name + ": " + dbuser_password)

        contents.append("wikis:")
        for wiki in set_config['wikidbs']:
            contents.append("  - " + wiki)

        with open(path, "w") as creds:
            creds.write("\n".join(contents) + "\n")


class Images():
    '''
    manage the build and removal of images as defined in a config
    '''
    def __init__(self, args, config, labeler, networks):
        self.args = args
        self.verbose = args['verbose']
        self.dryrun = args['dryrun']
        self.labeler = labeler
        self.nets = networks
        self.config = config

    def image_exists(self, tag):
        '''check if the image with the specific tag in the container set exists'''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.images.list(all=True)
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
                _unused, logs = client.images.build(
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
            if self.verbose:
                print("BUILD SUCCEEDED for common base image in {setname}".format(
                    setname=self.args['set']))
                for entry in logs:
                    print(entry)

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
                        _unused, logs = client.images.build(
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
                    if self.verbose:
                        print("BUILD SUCCEEDED for {name} base image in {setname}".format(
                            name=image_name, setname=self.args['set']))
                        for entry in logs:
                            print(entry)

    def do_final_build(self):
        '''
        build final images needed for the containers associated with a wikifarm set.
        these will be dependent on the network name and eventual container names.
        this will also build base images if required.
        if all of the images exist and are current, return
        '''
        self.do_base_build()

        # this will get copied into these final images and has creds from per-set config
        credsfile_path = os.path.join(
            os.getcwd(), 'docker_helpers', 'credentials.' + self.args['set'] + ".yaml")
        self.config.write_creds_file(self.args['set'], credsfile_path)

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

            # If there are no import files set up, we'll make a placeholder so the image and
            # container will be built, but we will warn the user as well.
            db_imports_dir = os.path.join("./docker_helpers/mariadb/imports", self.args['set'])
            if image_name == "dbprimary" and not os.path.exists(db_imports_dir):
                os.makedirs(db_imports_dir)
                print("WARNING: No imports for primary db for set", self.args['set'])

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
                        _unused, logs = client.images.build(
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
                    if self.verbose:
                        print("BUILD SUCCEEDED for {name} final image in {setname}".format(
                            name=image_name, setname=self.args['set']))
                        for entry in logs:
                            print(entry)

    def do_purge(self):
        '''
        purge the specified or all base images, first destroying all derived containers for all
        sets, and all derived final images for all sets.
        we also remove all the networks for all sets, if a single base image was not specified.
        If image(s) do not exist, just return
        '''
        if self.args['name']:
            if self.verbose:
                print("removing specified base image for all sets.")
            base_image = 'wikimedia-dumps/{name}-base:latest'.format(name=self.args['name'])
            if self.image_exists(base_image):
                todos = [base_image]
            else:
                todos = []
        else:
            if self.verbose:
                print("removing all base images for all sets.")

            networks = self.nets.get_all_networks()
            for network in networks:
                self.do_remove(network)

            todos = []
            for image_name in ['snapshot', 'dbprimary', 'dbpreplica', 'dumpsdata',
                               'httpd', 'phpfpm']:
                base_image = 'wikimedia-dumps/{name}-base:latest'.format(name=image_name)
                if self.image_exists(base_image):
                    todos.append(base_image)

        if not todos:
            print("no base images to remove")

        client = DockerClient(base_url='unix://var/run/docker.sock')
        for base_image in todos:
            if self.verbose:
                print("removing {name} image".format(name=base_image))
            client.images.remove(base_image)

    def do_purgeall(self):
        '''
        purge the base image underlying all base images, first destroying all derived
        containers for all sets, and all derived base and final images for all sets,
        and all networks for all sets.
        If image does not exist, just return
        '''
        if self.verbose:
            print("removing base image for all images for all sets.")

        base_image = "wikimedia-dumps/base:latest"
        if self.image_exists(base_image):
            if self.verbose:
                print("removing {name} image".format(name=base_image))
            client = DockerClient(base_url='unix://var/run/docker.sock')
            client.images.remove(base_image)
        else:
            print("no base image to remove")

    def do_remove(self, network=None):
        '''
        remove either the specified final image or all final images for this
        container set, first destroying the specified container or all containers
        for this set

        we also remove the network for this set if a single image was
        not specified.

        If images do not exist, just return
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')

        if self.args['name']:
            # remove just this image
            names = [self.args['name']]
            message = "specified final image for this container set " + self.args['set']
        else:
            # remove all the final images for the set
            names = ['snapshot', 'dbprimary', 'dbreplica', 'dumpsdata', 'httpd', 'phpfpm']
            message = "all final images for this container set " + self.args['set']
            self.nets.remove_network(network=network)

        if network is not None:
            message = message + " and network name " + network.name
        if self.verbose:
            print("removing " + message)

        full_image_names = []
        for image_name in names:
            final_image = 'wikimedia-dumps/{name}-{setname}-final:latest'.format(
                name=image_name, setname=self.args['set'])
            if self.image_exists(final_image):
                full_image_names.append(final_image)

        if not full_image_names:
            message = "no final images to remove for set " + self.args['set']
            if network is not None:
                message = message + " and network name " + network.name
            print(message)

        for image_name in full_image_names:
            if self.verbose:
                message = "removing {name} image".format(name=image_name)
                if network is not None:
                    message = message + " and network name " + network.name
                print(message)
            client.images.remove(image_name)

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
        entries = client.images.list(all=True)
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
        self.dryrun = args['dryrun']
        self.labeler = labeler
        self.nets = networks
        self.config = config

    @staticmethod
    def get_known_container_types():
        '''these are the image types we know how to build'''
        return ['snapshot', 'dbprimary', 'dbreplica', 'dbextstore', 'dumpsdata', 'httpd', 'phpfpm']

    def do_list(self, show_all=False):
        '''
        list all of the containers belonging to the specified set
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        entries = client.containers.list(all=True)
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
        entries = client.containers.list(all=True)
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
        entries = client.containers.list(all=True)
        for entry in entries:
            if self.labeler.has_labels(entry.labels, self.labeler.get_set_label()):
                if entry.short_id == short_id:
                    return True
        return False

    def container_exists_by_name(self, name, containers_known=None):
        '''check if the container with the specified name from a container set exists'''
        if not containers_known:
            client = DockerClient(base_url='unix://var/run/docker.sock')
            containers_known = client.containers.list(all=True)
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
            containers_known = client.containers.list(all=True)
        for entry in containers_known:
            if self.labeler.has_labels(entry.labels, self.labeler.get_set_label()):
                # allow for names like <setname>-snapshot-nn
                if (entry.name == self.args['set'] + '-' + name or
                        entry.name.startswith(self.args['set'] + '-' + name + '-')):
                    container_ids.append(entry.short_id)
        if container_ids:
            return container_ids
        return None

    def create_one_container(self, name, image, client, containers_known=None, volumes=None):
        '''
        create a container with the standard attributes given
        the desired container name, labels and image name
        '''
        if self.dryrun:
            print("would create container, skipping for dry run")
            return

        labels = self.labeler.get_set_label().copy()
        labels.update(self.labeler.get_blame_label())
        if not volumes:
            volumes = {}

        if not self.container_exists_by_name(name, containers_known):
            client.containers.create(
                image=image,
                name=name, detach=True, labels=labels,
                domainname=self.nets.get_network_name(),
                network=self.nets.get_network_name(),
                volumes=volumes)

    def check_and_create(self, opts, client, containers_known, volumes=None):
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
                        client, containers_known, volumes=volumes)
            else:
                name = self.args['set'] + "-{name}".format(name=opts['basename'])
                self.create_one_container(
                    name, 'wikimedia-dumps/{name}-{setname}-final:latest'.format(
                        name=opts['image'], setname=self.args['set']),
                    client, containers_known, volumes=volumes)

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
        containers_known = client.containers.list(all=True)

        if self.args['name']:
            todos = [self.args['name']]
        else:
            todos = self.get_known_container_types()

        config = self.config.get_containerset_config(self.args['set'])

        # snapshot containers
        if 'snapshot' in todos:
            wikifarm_volume = config['volumes']['wikifarm']
            dumpsrepo_volume = config['volumes']['dumpsrepo']
            dumpsetc_volume = config['volumes']['dumpsetc']
            dumpsruns_volume = config['volumes']['dumpsruns']
            volumes = {
                wikifarm_volume: {'bind': '/srv/mediawiki/wikifarm', 'mode': 'rw'},
                dumpsrepo_volume: {'bind': '/srv/dumps/dumpsrepo', 'mode': 'ro'},
                dumpsetc_volume: {'bind': '/srv/dumps/etc', 'mode': 'ro'},
                dumpsruns_volume: {'bind': '/srv/dumps/runs', 'mode': 'rw'}
            }

            self.check_and_create({'config': 'snapshots', 'max': 99,
                                   'basename': 'snapshot', 'image': 'snapshot'},
                                  client, containers_known, volumes)

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
            wikifarm_volume = config['volumes']['wikifarm']
            volumes = {wikifarm_volume: {'bind': '/srv/mediawiki/wikifarm', 'mode': 'rw'}}

            self.check_and_create({'config': 'httpd', 'max': None,
                                   'basename': 'httpd', 'image': 'httpd'},
                                  client, containers_known, volumes)

        # phpfpm container
        if 'phpfpm' in todos:
            wikifarm_volume = config['volumes']['wikifarm']
            volumes = {wikifarm_volume: {'bind': '/srv/mediawiki/wikifarm', 'mode': 'rw'}}

            self.check_and_create({'config': 'phpfpm', 'max': None,
                                   'basename': 'phpfpm', 'image': 'phpfpm'},
                                  client, containers_known, volumes)

        # nfs server (dumpsdata) container
        # FIXME no image yet
        if 'dumpsdata' in todos:
            self.check_and_create({'config': 'dumpsdata', 'max': None,
                                   'basename': 'dumpsdata', 'image': 'dumpsdata'},
                                  client, containers_known)

    def do_destroy(self, do_all=False):
        '''
        destroy a specified container, or all containers associated with a wikifarm
        set or all containers for all wikifarms.
        If the desired container(s) do not exist, just return
        '''

        client = DockerClient(base_url='unix://var/run/docker.sock')

        if do_all:
            # all sets
            container_ids = self.get_container_ids(self.labeler.get_blame_label())
            message = "all containers for all container sets"
        elif self.args['name']:
            # specified container
            containers_known = client.containers.list(all=True)
            container_ids = self.get_container_ids_from_name(self.args['name'], containers_known)
            message = "the specified container in this set "
        else:
            # just this set
            container_ids = self.get_container_ids(self.labeler.get_set_label())
            message = "all containers for this container set"

        if self.verbose:
            print("removing " + message)

        if not container_ids:
            print("No containers to remove")
            return True

        for entry in container_ids:
            container = client.containers.get(entry)

            if self.dryrun:
                print("would stop and remove container", entry)
                continue

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
        containers_known = client.containers.list(all=True)

        if self.args['name']:
            container_ids = self.get_container_ids_from_name(self.args['name'], containers_known)
        else:
            container_ids = self.get_container_ids(self.labeler.get_blame_label())

        for entry in container_ids:
            container = client.containers.get(entry)
            if self.dryrun:
                print("would start container:", entry)
                continue

            if self.verbose:
                print("starting container:", entry)
            container.start()

    def do_stop(self):
        '''
        stop containers associated with a wikifarm set.
        If the containers do not exist for this set, just return
        '''
        client = DockerClient(base_url='unix://var/run/docker.sock')
        containers_known = client.containers.list(all=True)
        if self.args['name']:
            container_ids = self.get_container_ids_from_name(self.args['name'], containers_known)
        else:
            container_ids = self.get_container_ids(self.labeler.get_blame_label())

        for entry in container_ids:
            container = client.containers.get(entry)
            if self.dryrun:
                print("would stop container:", entry)
                continue

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

        if self.args['dryrun']:
            print("Dry run: no images or containers will be acted upon")

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
        elif self.args['command'] == 'purgeall':
            # we are removing the base image for all the base images for the wiki set,
            # so everything must be removed for all sets
            # must also be destroyed
            self.containers.do_destroy(do_all=True)
            self.images.do_purge()
            self.images.do_purgeall()


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

 --base     (-B):  build base images needed for containers for the specified container set
 --build    (-b):  build final images needed for containers for the specified container set
                   also do the base build if needed
 --create   (-c):  create containers in the specified container set for sql/xml dump tests
                   also do the base and final image builds if needed
 --start    (-s):  start up the containers for the wikifarm in the specified set
                   also do container creation if needed
 --name     (-n):  build or remove the specified base or final image, where 'name' is one of
                   the image or container types in the set ('snapshot', 'httpd', 'dumpsdata' (nfs),
                   'dbextstore', 'dbreplica', 'phpfpm', 'dbprimary'), or create, start, destroy
                   or stop the specified container(s) in the set
                   this option is valid with --base, --build, --remove, --purge, --create, --start,
                   --destroy or --stop and will be ignored in all other cases
 --list     (-l):  list containers created for the wikifarm in the specified set
 --stop     (-S):  stop the containers for the wikifarm in the specified set
 --destroy  (-d):  destroy the containers in the specified set
 --remove   (-r):  remove the final images for the containers in the specified set
                   all running containers for this set will be stopped and destroyed first
 --purge    (-p):  purge the base images for the containers in the specified set
                   all running containers for this set will be stopped and destroyed first
                   and all final images for this set will also be removed
 --purgeall (-P):  purge the base image for all base images, final images, etc
                   all running containers for this set will be stopped and destroyed first
                   and all base and final images for this set will also be removed
 --test     (-t):  run the specified test as defined in the specified set
 --config   (-C):  path to configuration file. settings in this file will override
                   settings in default.conf
                   default value: './docker-dumps.conf' in the current working directory

Flags:

 --dryrun  (-D):  say what would be done but don't do it
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
        args = {'config': None, 'set': None, 'test': None,
                'name': None, 'verbose': False, 'dryrun': False}
        return args

    def check_opts(self, args):
        '''
        validate opts and make sure we have the mandatory ones
        '''
        # note that if args['command'] was never set, we leave that to the caller
        # to handle. the caller, for example, may decide to show all known sets to the user.
        if 'command' in args and not args['command']:
            self.usage("One of the args 'base', 'build', 'create', 'list', 'start', 'stop', "
                       "'test', 'remove', 'destroy', 'purge' or 'purgeall'  must be specified")
        if args['name'] and args['name'] not in ['snapshot', 'httpd', 'dumpsdata', 'dbextstore',
                                                 'dbreplica', 'phpfpm', 'dbprimary']:
            self.usage("Unknown container type " + args['name'] + " specified.")

    def process_opts(self):
        '''
        get command-line args and values, falling back to defaults
        where needed, whining about bad args
        '''
        commands = {'B': 'base', 'b:': 'build', 'c': 'create', 'l': 'list', 's': 'start',
                    'S': 'stop', 'd': 'destroy', 'r': 'remove', 'p': 'purge', 'P': 'purgeall'}
        try:
            (options, remainder) = getopt.gnu_getopt(
                sys.argv[1:], "C:t:b:B:c:l:s:S:n:d:r:p:P:Dvh",
                ["config=", "test=", "base=", "build=", "create=", "name=", "list=", "start=",
                 "stop=", "destroy=", "remove=", "purge=", "purgeall=",
                 "dryrun", "verbose", "help"])

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
            elif opt in ["-D", "--dryrun"]:
                args['dryrun'] = True
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
    config = ContainerConfig(args['config'], args['verbose'])
    labeler = ContainerLabels(args)
    networks = Networks(args, labeler)
    images = Images(args, config, labeler, networks)
    containers = Containers(args, config, labeler, networks)
    wikifarm = WikifarmSets(args, images, containers)
    wikifarm.do_command()


if __name__ == '__main__':
    do_main()
