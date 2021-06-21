#!/usr/bin/python3

'''
read a configuration file with file path of templates and destination file paths
for each entry, substitute in all the container names to each template and put
the output in its final destination
'''
import sys


def get_container_info(path):
    '''read the container info from the specified file and return it'''
    with open(path, "r") as fin:
        contents = fin.read().splitlines()
        return contents


def get_substitution_entries(path):
    '''read substitution entries from the specified file and return them
    as a list of source, dest tuples
    note that this will fail if source or dest path has whitespace in it'''
    with open(path, "r") as fin:
        lines = fin.read().splitlines()
        lines = [line for line in lines if line.strip() and not line.startswith('#')]
        entries = [line.strip().split(maxsplit=1) for line in lines]
        return entries


def get_container_name(substring, container_info):
    '''return the name of the container having the specific substring.
    if more than one, or none at all, return None.
    you're supposed to be getting ONE UNIQUE container #kthxbai'''
    containers = [line for line in container_info if substring in line]
    if len(containers) != 1:
        return None
    return containers[0]


def do_substitution(entry, container_info):

    '''given a source file, a destination path and container name info,
    swap in the real container names for placeholders in the source file
    and write the result to the destination path'''
    # strings we may replace: PHPFPM HTTPD DBPRIMARY (more later)
    with open(entry[0], "r") as fin:
        contents = fin.read()
        vars_to_containers = {'PHPFPM': 'phpfpm', 'HTTPD': 'httpd', 'DBPRIMARY': 'dbprimary'}
        for var, container in vars_to_containers.items():
            contents = contents.replace(var, get_container_name(container, container_info))
        with open(entry[1], "w") as fout:
            fout.write(contents)


def do_main(config_file, container_file):
    '''entry point'''
    setname = sys.argv[1]
    container_info = get_container_info(container_file + "." + setname)
    subs_entries = get_substitution_entries(config_file)
    for entry in subs_entries:
        do_substitution(entry, container_info)


if __name__ == '__main__':
    do_main('/root/substitution.conf', '/root/container_list')
