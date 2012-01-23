"""
Deployment targets -- These can be used to specify which deployment the the
tasks you run should apply to.
"""

import utils

@utils.with_appcfg
def staging(version=None):
    """Sets the deployment target to staging, with an optional non-default
    version.
    """
    version = 'staging' if version is None else 'staging-' + version
    return utils.deployment_target(version=version)

@utils.with_appcfg
def production(version=None):
    """Sets the deployment target to production, with an optional non-default
    version.
    """
    return utils.deployment_target(version=version)
