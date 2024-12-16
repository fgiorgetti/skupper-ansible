#!/usr/bin/python

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os
import copy

from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.k8s import (
    K8sClient
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.resource import (
    load,
    dump,
    delete as resource_delete
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common import (
    is_non_kube
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.exceptions import (
    RuntimeException
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.args import (
    common_args,
    is_valid_name
)
from ansible.module_utils.urls import fetch_url
from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r'''
---
module: resource

short_description: Place skupper resources (yaml) in the provided namespace

version_added: "2.0.0"

description: >-
    Place skupper resources (yaml) in the provided namespace. If platform is
    kubernetes (default) the resources are applied to the respective namespace.
    In case a different platform is used, the resources will be placed into the
    correct location for the namespace on the file system.

options:
    path:
        description:
        - Path where resources are located (yaml and yml files).
        - Path can be a directory, a file or an http URL.
        - If remote is true (default: false), the resources will not be copied from the control node.
        - URLs are always fetch from the inventory host.
        - Mutually exclusive with def
        type: str
    def:
        description:
        - YAML representation of a custom resource.
        - It can contain multiple YAML documents.
        type: str
        aliases: [ definition ]
    remote:
        description:
        - Determines if the resources are located at the inventory host instead of the control node.
        type: str
    state:
        description:
        - V(present) means that if the resource does not exist, it will be created. If it exists, no change is made.
        - V(latest) means that if the resource does not exist it will be created or updated with the latest provided definition.
        - V(absent) means that the resource will be removed.
        type: str
        default: "present"
        choices: ["present", "latest", "absent"]

extends_documentation_fragment:
  - fgiorgetti.skupperv2.common_options

requirements:
  - "python >= 3.9"
  - "kubernetes >= 24.2.0"
  - "PyYAML >= 3.11"

author:
    - Fernando Giorgetti (@fgiorgetti)
'''

EXAMPLES = r'''
# Applying resources to a kubernetes cluster
- name: Apply Skupper Resources
  fgiorgetti.skupperv2.resource:
    path: /home/user/west/crs
    platform: kubernetes
    namespace: west

# Applying remote resources to a kubernetes cluster
- name: Apply Skupper Resources
  fgiorgetti.skupperv2.resource:
    path: /remote/home/user/west/crs
    remote: true
    platform: kubernetes
    namespace: west

# Applying resources to a non-kube namespace
- name: Apply Skupper Resources
  fgiorgetti.skupperv2.resource:
    path: /home/user/west/crs
    platform: podman
    namespace: west

# Define a single resource
- name: Define resources for west site
  fgiorgetti.skupperv2.resource:
    def: >-
      ---
      apiVersion: skupper.io/v2alpha1
      kind: Site
      metadata:
        name: west
      spec:
        linkAccess: default
      ---
      apiVersion: skupper.io/v2alpha1
      kind: Listener
      metadata:
        name: backend
      spec:
        host: backend
        port: 8080
        routingKey: backend
'''


def argspec():
    spec = copy.deepcopy(common_args())
    spec["path"] = dict(type="str", default=None, required=False)
    spec["def"] = dict(type="str", default=None,
                       required=False, aliases=["definition"])
    spec["remote"] = dict(type="bool", default=False, required=False)
    spec["state"] = dict(type="str", default="present", required=False, choices=[
                         "present", "latest", "absent"])
    return spec


def mutualexc():
    return [
        ("path", "def"),
        ("def", "remote"),
    ]


class ResourceModule:
    def __init__(self, module: AnsibleModule):
        self.module = module

    def run(self):
        result = dict(
            changed=False,
        )
        if self.module.check_mode:
            self.module.exit_json(**result)

        definition_found = False
        definitions = ""

        # self.module._debug = True

        platform = self.params["platform"]
        if "path" in self.params and self.params["path"]:
            try:
                definitions, definition_found = self.load_from_path(platform)
            except RuntimeException as ex:
                self.module.fail_json(ex.msg)
        elif "def" in self.params and self.params["def"]:
            definition_found = True
            definitions = self.params["def"]

        if not definition_found:
            self.module.fail_json("no resource definition or path provided")

        changed = False
        state = self.params.get("state", "present")
        overwrite = state == "latest"
        try:
            if is_non_kube(platform):
                namespace = self.params["namespace"] or "default"
                if not is_valid_name(namespace):
                    self.module.fail_json("invalid namespace (rfc1123): {}".format(namespace))

                if state == "absent":
                    changed = resource_delete(definitions, namespace)
                else:
                    changed = dump(definitions, namespace, overwrite)
            else:
                kubeconfig = self.params.get("kubeconfig")
                context = self.params.get("context")
                k8s_client = K8sClient(kubeconfig, context)
                namespace = self.params.get("namespace")
                if state == "absent":
                    changed = k8s_client.delete(namespace, definitions)
                else:
                    changed = k8s_client.create_or_patch(
                        namespace, definitions, overwrite)
        except Exception as ex:
            self.module.fail_json(ex.args)

        result['changed'] = changed

        self.module.exit_json(**result)

    def load_from_path(self, platform) -> tuple[str, bool]:
        if self.params["path"].startswith(("http://", "https://")):
            try:
                fetch_res, fetch_info = fetch_url(
                    self.module, url=self.params["path"])
                if fetch_info['status'] != 200:
                    self.module.fail_json(msg="failed to fetch url %s , error was: %s" % (
                        self.params["path"], fetch_info['msg']))
                return fetch_res.read(), True
            except Exception as ex:
                raise RuntimeException("error fetching url %s: %s"
                                       % (self.params["path"], ex)) from ex
        else:
            return load(self.params["path"], platform), True

    @property
    def params(self):
        return self.module.params


def main():
    module = AnsibleModule(
        argument_spec=argspec(),
        mutually_exclusive=mutualexc(),
        supports_check_mode=True
    )
    resource = ResourceModule(module)
    resource.run()


if __name__ == '__main__':
    main()
