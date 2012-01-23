A set of Fabric commands that I've found useful for my App Engine
applications.


Getting Started
===============

Simply drop this directory into your App Engine project and create a
`fabfile.py` in your project's root. See `fabfile.example.py` for more
information..


A Note on Deployment Targets
============================

There are two deployment target modifiers, production and staging, which
adjust the deployments to which the other commands apply. Each takes an
optional version modifier, if it should target a non-default version.

Deploys to production will generally use the version identifier as found in a
project's app.yaml (ie, "production" generally means "as currently specified
in app.yaml").

Deploys to staging, on the other hand, will use a special 'staging' version
instead of the version specified in app.yaml. It is expected that your
application recognizes this 'staging' version string and alters its behavior
accordingly (e.g. writing to a different datastore).

For example, to run the shell command on the default production deployment:

    fab production shell

To run the shell command on a specific version of the staging deployment:

    fab staging:1-908ca6a shell

And to get a local shell, you just leave off the deployment target:

    fab shell
