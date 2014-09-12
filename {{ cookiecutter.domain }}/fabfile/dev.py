from __future__ import print_function, unicode_literals

from multiprocessing import Process
import os
import socket

from fabric.api import env, task

from fabfile.config import local


def _service_processes():
    jobs = []
    try:
        socket.create_connection(('localhost', 5432), timeout=0.1).close()
    except socket.error:
        jobs.append(lambda: local('postgres'))
    try:
        socket.create_connection(('localhost', 6379), timeout=0.1).close()
    except socket.error:
        jobs.append(lambda: local('redis-server'))
    return jobs


@task(default=True)
def dev():
    jobs = [
        lambda: local('venv/bin/python -Wall manage.py runserver'),
    ]

    if os.path.exists('%(box_sass)s/bower.json' % env):
        jobs.append(lambda: local('cd %(box_sass)s && grunt'))
    elif os.path.exists('%(box_sass)s/config.rb' % env):
        jobs.append(lambda: local('bundle exec compass watch %(box_sass)s'))

    jobs.extend(_service_processes())
    jobs = [Process(target=j) for j in jobs]
    [j.start() for j in jobs]
    [j.join() for j in jobs]


@task
def services():
    jobs = _service_processes()
    jobs = [Process(target=j) for j in jobs]
    [j.start() for j in jobs]
    [j.join() for j in jobs]


@task
def makemessages():
    local(
        'venv/bin/python manage.py makemessages -a'
        ' -i bower_components'
        ' -i node_modules'
        ' -i venv')
