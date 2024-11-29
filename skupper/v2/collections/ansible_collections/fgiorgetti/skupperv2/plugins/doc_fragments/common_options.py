# -*- coding: utf-8 -*-

# Common options for all skupper modules

from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment(object):
    DOCUMENTATION = r"""
options:
  platform:
    description:
    - The platform to use when manipulating resources
    type: str
    default: kubernetes
    choices: [ kubernetes, podman, docker, systemd ]
  namespace:
    description:
    - Use to specify an object namespace.
    type: str
  kubeconfig:
    description:
    - Path to an existing Kubernetes config file. If not provided, and no other connection
      options are provided, the Kubernetes client will attempt to load the default
      configuration file from I(~/.kube/config).
    type: str
  context:
    description:
    - The name of a context found in the config file.
    type: str
"""
