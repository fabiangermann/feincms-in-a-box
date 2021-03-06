from __future__ import unicode_literals

from datetime import datetime
from io import StringIO
import os

from fabric.api import env, execute, hide, prompt, put, settings, task
from fabric.colors import green, red
from fabric.utils import abort, puts

from fabfile import confirm, run_local, cd, require_env, run
from fabfile.utils import default_env, get_random_string


@task
@require_env
def setup():
    """Sets up the server from a git repository"""
    execute('server.clone_repository')
    execute('server.create_virtualenv')
    execute('server.create_database_and_dotenv')
    execute('server.nginx_vhost_and_supervisor')
    execute('deploy.styles')
    execute('server.create_sso_user')


@task
@require_env
def clone_repository():
    puts(green('We need the repository to initialize the server.'))
    with hide('running'):
        output = run_local('git config remote.origin.url', capture=True)
    repo = prompt('Repository', default=output)

    if not repo:
        puts(red('Cannot continue without a repository.'))
        return 1

    env.box_repository_url = repo

    run('git clone -b %(box_branch)s %(box_repository_url)s %(box_domain)s')
    execute('git.add_remote')


@task
@require_env
def create_virtualenv():
    with cd('%(box_domain)s'):
        run('virtualenv --python python2.7'
            ' --prompt "(venv:%(box_domain)s)" venv')
        run('venv/bin/pip install -U virtualenv pip wheel'
            ' --find-links file:///home/www-data/tmp/wheel/wheelhouse/')
        run('venv/bin/pip install -U setuptools'
            ' --find-links file:///home/www-data/tmp/wheel/wheelhouse/')
        run('venv/bin/pip install -r requirements/production.txt'
            ' --find-links file:///home/www-data/tmp/wheel/wheelhouse/')


@task
@require_env
def create_database_and_dotenv():
    env.box_sentry_dsn = prompt('Sentry DSN')
    env.box_oauth2_client_id = prompt('Google OAuth2 Client ID')
    env.box_oauth2_client_secret = prompt('Google OAuth2 Client Secret')

    env.box_database_pw = get_random_string(
        20, chars='abcdefghijklmopqrstuvwx01234567890')
    env.box_secret_key = get_random_string(50)

    run('psql -c "CREATE ROLE %(box_database)s WITH'
        ' ENCRYPTED PASSWORD \'%(box_database_pw)s\''
        ' LOGIN NOCREATEDB NOCREATEROLE NOSUPERUSER"')
    run('psql -c "GRANT %(box_database)s TO admin"')
    run('psql -c "CREATE DATABASE %(box_database)s WITH'
        ' OWNER %(box_database)s'
        ' TEMPLATE template0'
        ' ENCODING \'UTF8\'"')

    with cd('%(box_domain)s'):

        put(StringIO('''\
DATABASE_URL=postgres://%(box_database)s:%(box_database_pw)s\
@localhost:5432/%(box_database)s
CACHE_URL=hiredis://localhost:6379/1/%(box_database)s
SECRET_KEY=%(box_secret_key)s
SENTRY_DSN=%(box_sentry_dsn)s
DJANGO_ADMIN_SSO_OAUTH_CLIENT_ID=%(box_oauth2_client_id)s
DJANGO_ADMIN_SSO_OAUTH_CLIENT_SECRET=%(box_oauth2_client_secret)s
ALLOWED_HOSTS=['%(box_domain)s', '.%(box_domain)s', '.%(host_string_host)s']

# Do not forget to allow robots to index the site when going live!
# - %(box_project_name)s/templates/base.html: Change "noindex" to "index"
# - htdocs/robots.txt: Remove the "Disallow: /" line
# FORCE_DOMAIN = www.%(box_domain)s
''' % dict(env, host_string_host=env.host_string.split('@')[-1])), '.env')

        run('venv/bin/python manage.py migrate --noinput')


@task
@require_env
def nginx_vhost_and_supervisor():
    run('sudo nine-manage-vhosts virtual-host create %(box_domain)s'
        ' --template=feinheit --relative-path=htdocs')

    with cd('%(box_domain)s'):
        run('mkdir -p media tmp')

    run('supervisor-create-conf %(box_domain)s wsgi'
        ' > supervisor/conf.d/%(box_domain)s.conf')
    run('sctl reload')


@task
@require_env
def create_sso_user():
    env.box_sso_domain = prompt(
        'SSO Domain (leave empty to skip)',
        default=default_env('SSO_DOMAIN') or '')
    if not env.box_sso_domain:
        puts(red('Cannot continue without a SSO Domain.'))
        return 1

    run("psql %(box_database)s -c \"INSERT INTO auth_user"
        " (username, email, password, is_active, is_staff, is_superuser,"
        " first_name, last_name, date_joined, last_login) VALUES"
        " ('admin', '', '', TRUE, TRUE, TRUE, '', '', NOW(), NOW())\"")
    run("psql %(box_database)s -c \""
        "INSERT INTO admin_sso_assignment"
        " (username_mode, username, domain, copy, weight, user_id)"
        " SELECT 0, '', '%(box_sso_domain)s', FALSE, 10, id"
        " FROM auth_user WHERE username='admin'\"")


@task
@require_env
def copy_data_from(environment=None):
    if env.get('box_hardwired_environment'):
        abort(red('Cannot continue with a hardwired environment.'))
    if environment not in env.box_environments:
        abort(red('Invalid environment %s.' % environment))

    source = env.box_environments[environment]
    target = env.box_environments[env.get('box_environment')]
    if source == target:
        abort(red(
            'Source environment %s must not equal target environment %s.'
            % (environment, env.get('box_environment'))))

    if source['server'] != target['server']:
        abort(red('The environments have to be on the same server, sorry!'))

    if not confirm(
            'Completely replace the remote database'
            ' "%(box_database)s" (if it exists)?', default=False):
        return

    for key, value in source.items():
        env['source_%s' % key] = value

    with settings(warn_only=True):
        run('dropdb %(box_database)s')
    run(
        'createdb %(box_database)s --encoding=UTF8 --template=template0'
        ' --owner=%(box_database)s')
    run(
        'pg_dump %(source_database)s'
        ' --no-privileges --no-owner --no-reconnect'
        ' | psql %(box_database)s')
    run(
        'psql %(box_database)s -c "REASSIGN OWNED BY admin '
        ' TO %(box_database)s"')

    with cd(env.box_domain):
        run('cp -al ~/%(source_domain)s/media/* media/')
        run('sctl restart %(box_domain)s:*')


@task
@require_env
def remove_host():
    if not confirm(
            'Really remove the host "%(box_domain)s" and all associated data?',
            default=False):
        return

    run('sudo nine-manage-vhosts virtual-host remove %(box_domain)s')
    run('rm supervisor/conf.d/%(box_domain)s.conf')
    run('sctl reload')
    with cd(env.box_domain):
        env.box_datetime = datetime.now().strftime('%Y-%m-%d-%s')
        run(
            'pg_dump %(box_database)s'
            ' --no-privileges --no-owner --no-reconnect'
            ' > %(box_database)s-%(box_environment)s-%(box_datetime)s.sql')
    run('dropdb %(box_database)s')
    run('dropuser %(box_database)s')

    puts(red(
        'The folder ~/%(box_domain)s on the server has not been removed. The'
        ' "tmp" subfolder also contains a fresh database dump.' % env))


@task
@require_env
def dump_db():
    """Dumps the database into the tmp/ folder"""
    env.box_datetime = datetime.now().strftime('%Y-%m-%d-%s')
    env.box_dump_filename = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'tmp',
        '%(box_database)s-%(box_environment)s-%(box_datetime)s.sql' % env,
    )

    run_local(
        'ssh %(host_string)s "source .profile &&'
        ' pg_dump %(box_database)s'
        ' --no-privileges --no-owner --no-reconnect"'
        ' > %(box_dump_filename)s')
    puts(green('\nWrote a dump to %(box_dump_filename)s' % env))


@task
@require_env
def load_db(filename=None):
    """Loads a dump into the database"""
    env.box_dump_filename = filename

    if not filename:
        abort(red('Dump missing. "fab server.load_db:filename"', bold=True))

    if not os.path.exists(filename):
        abort(red('"%(box_dump_filename)s" does not exist.' % env, bold=True))

    if not confirm(
            'Completely replace the remote database'
            ' "%(box_database)s" (if it exists)?', default=False):
        return

    run(
        'psql -c "DROP DATABASE IF EXISTS %(box_database)s"')
    run(
        'createdb %(box_database)s --encoding=UTF8 --template=template0'
        ' --owner=%(box_database)s')
    run_local(
        'cat %(box_dump_filename)s |'
        'ssh %(host_string)s "source .profile && psql %(box_database)s"')
    run(
        'psql %(box_database)s -c "REASSIGN OWNED BY admin '
        ' TO %(box_database)s"')


@task
@require_env
def dbshell():
    run('psql %(box_database)s')
