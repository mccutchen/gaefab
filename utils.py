import functools
import getpass
import logging
import os
import sys

try:
    from google.appengine.api import appinfo
except ImportError:
    import google
    sdk_path = os.path.abspath(
        os.path.dirname(
            os.path.dirname(
                os.path.realpath(google.__file__))))
    extra_libs = ['antlr3', 'django', 'webob', 'ipaddr', 'protorpc',
                  'yaml/lib', 'fancy_urllib', 'simplejson', 'graphy']
    extra_paths = [os.path.join(sdk_path, 'lib', lib) for lib in extra_libs]
    sys.path = extra_paths + sys.path
    from google.appengine.api import appinfo
from google.appengine.ext.remote_api import remote_api_stub
from google.appengine.tools import dev_appserver, dev_appserver_main

from fabric.api import env, abort


PROJECT_ROOT = os.getcwd()

# Optional remote_api credentials file
CREDENTIALS = '.remote_api_creds'

# Where is the remote_api endpoint? The default is the path when the builtin
# config is used in app.yaml.
REMOTE_API_PATH = '/_ah/remote_api'


def with_appcfg(func):
    """Decorator that ensures that the current Fabric env has GAE info
    attached to it at `env.gae`.  Available attributes:

     - env.gae.application:  The app's application id (e.g., key-auth)
     - env.gae.version: The app's version
    """
    @functools.wraps(func)
    def decorated_func(*args, **kwargs):
        if not hasattr(env, 'gae') or not env.gae:
            # We have to attach a dummy object to the environment, because we
            # need to attach more info to it than is supported by the AppInfo
            # object (e.g., a host attribute).
            appcfg = parse_appcfg()
            env.gae = type('GaeInfo', (), {})
            env.gae.application = appcfg.application
            env.gae.version = appcfg.version
        return func(*args, **kwargs)
    return decorated_func

@with_appcfg
def deployment_target(version=None):
    """A base modifier for specifying the deployment target. Knows how to
    adjust the app's version and the gae_host string if a particular version
    is requested.
    """
    if version:
        env.gae.version = version
        env.gae.host = '%s.latest.%s.appspot.com' % (
            env.gae.version, env.gae.application)
    else:
        env.gae.host = '%s.appspot.com' % env.gae.application

def target_required(func):
    """Requires that a deployment target is specified before the given task is
    run."""
    @functools.wraps(func)
    def decorated_func(*args, **kwargs):
        if not hasattr(env, 'gae') or not env.gae:
            abort('A deployment target must be specified.')
        return func(*args, **kwargs)
    return decorated_func

def ensure_gae_env(func):
    """Ensures that a suitable GAE env is set up, either locally or remotely,
    before running the given task. If a deployment target is given, that
    environment is used, otherwise a local environment will be prepared.
    """
    @functools.wraps(func)
    def decorated_func(*args, **kwargs):
        if hasattr(env, 'gae'):
            prep_remote_shell()
        else:
            prep_local_shell()
        return func(*args, **kwargs)
    return decorated_func

@with_appcfg
def prep_local_shell():
    """Prepares a local shell by setting up the appropriate stubs."""
    args = dev_appserver_main.DEFAULT_ARGS.copy()
    dev_appserver.SetupStubs(env.gae.application, **args)

@with_appcfg
def prep_remote_shell(path=REMOTE_API_PATH):
    """Prepares a remote shell using remote_api located at the given path."""
    auth_func = make_auth_func()
    # We pass None instead of the app.yaml application ID because that will
    # break on HRD apps (whose app IDs in production are prepended with "s~"
    # for some reason). See comment #9 on this bug for more info:
    # http://code.google.com/p/googleappengine/issues/detail?id=4374#c9
    remote_api_stub.ConfigureRemoteApi(
        None, path, auth_func, servername=env.gae.host)
    remote_api_stub.MaybeInvokeAuthentication()
    os.environ['SERVER_SOFTWARE'] = 'Development (remote_api_shell)/1.0'

def make_auth_func():
    """Creates an appropriate auth_func for the remote_api_stub. If a file
    named .remote_api_creds (or whatever the value of CREDENTIALS is) in the
    project root or ~, the credentials will be drawn from that
    file. Otherwise, you will be prompted for them.
    """
    paths = [os.path.join(PROJECT_ROOT, CREDENTIALS),
             os.path.expanduser('~/%s' % CREDENTIALS)]
    for path in paths:
        if os.path.exists(path):
            try:
                username, password = open(path).read().strip().split('\n')
            except:
                continue
            else:
                print 'Using credentials from %s...' % path
                return lambda: (username, password)
    return lambda: (raw_input('Email: '), getpass.getpass('Password: '))

def parse_appcfg():
    """Parses the current project's app.yaml config into an AppInfo object."""
    yamlpath = os.path.join(PROJECT_ROOT, 'app.yaml')
    return appinfo.LoadSingleAppInfo(open(yamlpath))

def make_test_command(*modules, **kwargs):
    """Creates a fabric command, test, to run the tests for the given
    modules.

    Example usage, in a fabfile.py:

        test = utils.make_test_command('api', 'store')

    Now, running `fab test` will execute the unit tests in the api.tests and
    store.tests modules.
    """

    def test(coverage=None, verbose=None, loglevel='WARN'):
        # The docstring will be added after this function is defined, so it
        # can be dynamically updated to include the modules that will be
        # tested.
        import unittest

        # Set up logging
        level = getattr(logging, loglevel.upper(), logging.WARN)
        logging.getLogger().setLevel(level)

        # TODO: Support alternate test runners?
        verbosity = 1 if verbose is None else 2
        runner = unittest.TextTestRunner(verbosity=verbosity)

        # If test coverage is requested, try to create a coverage object. If
        # coverage cannot be imported, the tests will still be run.
        if coverage is not None:
            try:
                import coverage
            except ImportError, e:
                logging.warn('Could not import coverage, no test coverage '
                             'info will be generated.')
                cov = None
            else:
                cov = coverage.coverage()
        else:
            cov = None

        # Start test coverage before importing any of the tests
        if cov is not None:
            cov.start()

        suite = unittest.TestSuite()
        loader = unittest.TestLoader()
        for mod in modules:
            test_mod = '%s.tests' % mod
            try:
                suite.addTest(loader.loadTestsFromName(test_mod))
            except (AttributeError, ImportError), e:
                logging.error(
                    'Could not load test module %s: %s', test_mod, e)

        # Run the tests
        headers = [
            'Running tests for module(s):',
            '\n'.join(modules),
            'Test runner:   %s\nCode coverage? %s' % (
                runner_cls.__name__, cov is not None),
            ]
        print header(*headers)
        result = runner.run(suite)

        # If we have a coverage object, turn off coverage and save the results
        if cov is not None:
            cov.stop()
            logging.info('Saving coverage info...')
            cov.save()

        # Exit with non-zero code if there were any test failures
        if not result.wasSuccessful():
            sys.exit(1)

    # Add the docstring to the test command we just created, so that fab can
    # show appropriate help.
    test.__doc__ = """Runs the following modules' tests: %s

Optional arguments:

    :coverage -- Turn on code coverage monitoring and reporting.

    :verbose -- Turn on verbose test output, which reports each test's name
    and module as it is running.

    :loglevel -- Control the amount of logging done by the tests. Should be
    one of the levels specified by the logging module (case insensitive).
""" % ', '.join(modules)

    return test

def header(*strings):
    underline = '=' * max(len(s) for s in strings)
    heds = []
    for s in strings:
        heds.extend([s, underline])
    return '\n' + '\n'.join(heds)
