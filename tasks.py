"""
The fabric tasks provided by gaefab.
"""

from __future__ import with_statement

import code
import logging
import os
import sys

from fabric.api import env, local, lcd, abort

import utils


@utils.target_required
def deploy(tag=None, export=None):
    """Clones the current project's git HEAD to a temporary directory,
updates its submodules, and deploys from the clone.

Optional arguments:

    :tag -- Deploy the project with the current git revision appended to its
    version string.

    :export -- Deploy the project from a clean checkout instead of from its
    working directory.

Usage:

    # Deploy whatever version is in app.yaml to staging, from the working
    # directory
    fab staging deploy

    # Deploy a version tagged with the current git revision to production,
    # from the working directory
    fab production deploy:tag=1

    # Deploy a clean checkout to staging
    fab staging deploy:export=1

    # Deploy a clean checkout, tagged with the current git revision, to
    # production
    fab production deploy:tag=1,export=1

    """
    # Are we deploying a version tagged with the git revision? If so, update
    # the app's version string accordingly.
    if tag is not None:
        gitversion = local(
            'git rev-parse --short HEAD', capture=True).strip()
        assert gitversion
        env.gae.version = '%s-%s' % (env.gae.version, gitversion)

    dangerous_dirs = (env.cwd, '', '.', '..')

    # Are we making a clean checkout from which to deploy?
    if export is not None:
        # Where are we checking out a clean copy?
        clone_src = os.getcwd()
        deploy_src = local(
            'mktemp -d -t %s' % env.gae.application, capture=True).strip()

        assert deploy_src and deploy_src.strip() not in dangerous_dirs,\
            'Invalid deploy_src: %r' % deploy_src

        # Make the clone, check out and update its submodules, and clean up
        # all the resulting git information (trying to make a clean copy of
        # the source).
        local('git clone %s %s' % (clone_src, deploy_src), capture=False)
        with lcd(deploy_src):
            # Now we can update the submodules and clean up any git info
            local('git submodule update --init --recursive', capture=False)
            local('find . -name ".git*" | xargs rm -rf', capture=False)

    # Otherwise, we're just deploying from the current directory, so we need
    # to move the local secrets file out of the way so we don't overwrite
    # it. The app ID and version will be controlled by the remote target.
    else:
        deploy_src = '.'

    # Deploy the application using appcfg.py
    cmd = 'appcfg.py -A %s -V %s update %s' % (
        env.gae.application, env.gae.version, deploy_src)
    local(cmd, capture=False)

    # Clean up after ourselves if we made a clone of the source code
    if export is not None:
        assert deploy_src not in dangerous_dirs
        local('rm -r %s' % deploy_src, capture=False)


@utils.target_required
def livedeploy(export=None):
    """Deploy the project twice: once tagged with the git version, once on
version 1 (or whatever version is specified in app.yaml).

This supports a policy of keeping the live sites on version 1 while still
having a record of the most recent git version that is deployed.

Optional arguments:

    :export -- Deploy the project from a clean checkout
    """
    deploy(tag=True, export=export)
    # Reset the gae env to the "real" version as specified in app.yaml. This
    # will usually have the effect of deploying to version '1'
    env.gae.version = utils.parse_appcfg().version
    deploy(tag=False, export=export)


def shell(cmd=None, path=None):
    """Launches an interactive shell for this app. If preceded by a deployment
target (e.g. production or staging), a remote_api shell on the given target is
started. Otherwise, a local shell is started.  Uses enhanced ipython or
bpython shells, if available, falling back on the normal Python shell.

Optional arguments:

    :cmd -- A string of valid Python code to be executed on the shell. The
    shell will exit after the code is executed.

    :path -- The path to the remote_api handler on the deployment
    target. Defaults to '/_ah/remote_api'.

Usage:

    # A local shell
    fab shell

    # A remote_api shell on production
    fab production shell

    # Run a command directly on production
    fab production shell:cmd="memcache.flush_all()"
"""

    # Import the modules we want to make available by default
    from google.appengine.api import urlfetch
    from google.appengine.api import memcache
    from google.appengine.ext import deferred
    from google.appengine.ext import db

    # Fix the path
    path = path or utils.REMOTE_API_PATH

    # Build a dict usable as locals() from the modules we want to use
    modname = lambda m: m.__name__.rpartition('.')[-1]
    mods = [db, deferred, memcache, sys, urlfetch]
    mods = dict((modname(m), m) for m in mods)

    # The banner for any kind of shell
    banner = 'Python %s\n\nImported modules: %s\n' % (
        sys.version, ', '.join(sorted(mods)))

    # Are we running a remote shell?
    if hasattr(env, 'gae'):
        # Add more info to the banner
        loc = '%s%s' % (env.gae.host, path)
        banner = '\nApp Engine remote_api shell\n%s\n\n%s' % (loc, banner)
        # Actually prepare the remote shell
        utils.prep_remote_shell(path=path)

    # Otherwise, we're starting a local shell
    else:
        utils.prep_local_shell()

    # Define the kinds of shells we're going to try to run
    def ipython_shell():
        # TODO: Support ipython 0.11.
        import IPython
        shell = IPython.Shell.IPShell(argv=[], user_ns=mods)
        shell.mainloop(banner=banner)

    def bpython_shell():
        from bpython import cli
        cli.main(args=[], banner=banner, locals_=mods)

    def plain_shell():
        sys.ps1 = '>>> '
        sys.ps2 = '... '
        code.interact(banner=banner, local=mods)

    # If we have a command to run, run it.
    if cmd:
        print 'Running remote command: %s' % cmd
        exec cmd in mods

    # Otherwise, start an interactive shell
    else:
        try:
            ipython_shell()
        except:
            try:
                bpython_shell()
            except:
                plain_shell()


@utils.ensure_gae_env
def loaddata(path):
    """Load the specified JSON fixtures.  If preceded by a deployment target,
the fixture data will be loaded onto that target.  Otherwise they will be
loaded into the local datastore.

Arguments:

    :path -- The path to the fixture data to load

Usage:

    # Load data locally
    fab loaddata:groups/fixtures/test_groups.json

    # Load data onto staging
    fab staging loaddata:groups/fixtures/test_groups.json
"""
    import fixtures
    logging.getLogger().setLevel(logging.INFO)
    fixtures.load_fixtures(path)

def dumpjson(kinds):
    """Dumps data from the local or remote datastore in JSON format.

Arguments:

    :kinds -- A comma-separated list of kinds to dump, specified as
              `path.to.module.ModelName `
    """
    import fixtures
    if hasattr(env, 'gae'):
        utils.prep_remote_shell()
    else:
        utils.prep_local_shell()
    for kind in kinds.split(','):
        print fixtures.serialize_entities(kind)


@utils.target_required
def memcache(cmd='stats'):
    """Operate on a remote deployment's memcache by getting its stats or
clearing its data.

Optional arguments:

    :cmd -- The action to take. Defaults to 'stats'. Must be one of 'stats' or
    'flush'.

Usage:

    # Get production memcache's stats
    fab production memcache:stats

    # Same thing (gets stats by defualt)
    fab production memcache

    # Clear staging memcache
    fab staging memcache:flush
"""
    # What kind of commands do we know how to run?
    cmds = {
        'stats': 'print memcache.get_stats()',
        'flush': 'memcache.flush_all()',
        }
    # Aliases
    cmds['clear'] = cmds['flush']

    # Make sure we know what to do with the command
    if not cmd in cmds:
        valid_cmds = ', '.join(cmds)
        abort('Invalid memcache command. Valid commands: %s' % valid_cmds)

    # Run the actual Python code via the shell command
    return shell(cmd=cmds[cmd])


if __name__ == '__main__':
    shell()
