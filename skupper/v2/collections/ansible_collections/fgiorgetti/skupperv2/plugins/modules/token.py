#!/usr/bin/python

from __future__ import (absolute_import, division, print_function)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.k8s import (
    create_or_patch,
    delete as k8s_delete,
    get as k8s_get,
    has_condition
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.resource import (
    load,
    dump,
    delete as resource_delete
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.args import (
    add_fact,
    common_args
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common import (
    is_non_kube,
    namespace_home,
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.exceptions import (
    K8sException,
    RuntimeException
)
from ansible.module_utils.urls import fetch_url
from ansible.module_utils.basic import AnsibleModule
import time
import yaml
import os
import glob
import copy
__metaclass__ = type

DOCUMENTATION = r'''
---
module: token

short_description: Issue or retrieve access tokens and static links

version_added: "2.0.0"

description: |
    Manage Skupper Access Tokens and static links.

    * Generate and AccessGrant and return a corresponding AccessToken (kubernetes platform only)
    * Returns an AccessToken for an existing AccessGrant (kubernetes platform only)
    * Retrieves a static Link based on provided subject alternative name or host (podman, docker and systemd platforms)

options:
    name:
        description:
        - Name of the AccessGrant (to be generated or consumed) and AccessToken (kubernetes platform only)
        - Name of a RouterAccess (podman, docker or systemd platforms)
        type: str
    redemptionsAllowed:
        description:
        - The number of claims the generated AccessGrant is valid for
        type: int
    expirationWindow:
        description:
        - Duration of the generated AccessGrant
        - Samples: "10m", "2h"
        type: str
    host:
        description:
        - Static link hostname (podman, docker or systemd platforms)

extends_documentation_fragment:
  - fgiorgetti.skupperv2.common_options

requirements:
  - "python >= 3.9"
  - "kubernetes >= 24.2.0"
  - "PyYAML >= 3.11"

author:
    - Fernando Giorgetti (@fgiorgetti)
'''

RETURN = r"""
token:
  description:
  - AccessToken resource (yaml)
  - Link and Secret (yaml)
  returned: success
  type: str
"""

EXAMPLES = r'''
# Retrieving or issue a token (if my-grant does not exist or can be redeemed)
- name: Retrieve token
  fgiorgetti.skupperv2.token:
    name: my-grant
    platform: kubernetes
    namespace: west

# Retrieving an accesstoken for any valid accessgrant
- name: Retrieve token
  fgiorgetti.skupperv2.token:
    platform: kubernetes
    namespace: west

# Retrieve a static Link for host my.nonkube.host
- name: Retrieve a static link
  fgiorgetti.skupperv2.token:
    host: my.nonkube.host
    platform: podman
'''


def argspec():
    spec = copy.deepcopy(common_args())
    spec["name"] = dict(type="str", default=None, required=False)
    spec["host"] = dict(type="str", default=None, required=False)
    spec["redemptionsAllowed"] = dict(type="int", required=False)
    spec["expirationWindow"] = dict(type="str", required=False)
    return spec


def mutualexc():
    return []


class TokenModule:
    def __init__(self, module: AnsibleModule):
        self.module = module
        self._max_attempts = 6
        self._retry_delay = 5

    def run(self):
        result = dict(
            changed=False,
        )
        if self.module.check_mode:
            self.module.exit_json(**result)

        # TODO disable debug mode
        self.module._debug = True

        platform = self.params.get("platform", "kubernetes")
        name = self.params.get("name")
        host = self.params.get("host")
        namespace = self.params.get("namespace")
        redemptionsAllowed = self.params.get("redemptionsAllowed") or 1
        expirationWindow = self.params.get("expirationWindow") or "15m"

        changed = False

        token_link = ""
        if is_non_kube(platform):
            token_link = self.load_static_link(namespace, name, host)
        else:
            try:
                token_link = self.load_from_grant(namespace, name)
            except RuntimeException as runtimeEx:
                self.module.fail_json(runtimeEx.msg)
            if not token_link:
                grant_name = name or "ansible-grant-%d" % (int(time.time()))
                try:
                    if not self.generate_grant(namespace, grant_name, redemptionsAllowed, expirationWindow):
                        self.module.fail_json("unable to create AccessGrant: '%s'" %(grant_name))
                except Exception as ex:
                        raise RuntimeException("error creating AccessGrant: '%s'" %(grant_name))
                changed = True
                try:
                    token_link = self.load_from_grant(namespace, grant_name)
                except RuntimeException as runtimeEx:
                    self.module.fail_json(runtimeEx.msg)

        # adding return values
        if token_link:
            result['token'] = token_link

        result['changed'] = changed

        self.module.exit_json(**result)

    def load_static_link(self, namespace, name, host):
        home = namespace_home(namespace)
        links_path = os.path.join(home, "runtime", "links")
        links_search = os.path.join(
            links_path, "link-%s-%s.yaml" % (name or "*", host or "*"))
        links_found = glob.glob(links_search)
        for link in links_found:
            with open(link) as f:
                link_content = f.read()
                return link_content
        return ""

    def is_grant_ready(self, access_grant: dict) -> bool:
        for condition in access_grant.get("status", {}).get("conditions", []):
            if condition.get("type", "") == "Ready" and condition.get("status", "False") == "True":
                return True
                break
        return False

    def can_be_redeemed(self, access_grant: dict) -> bool:
        allowed = access_grant.get("spec", {}).get("redemptionsAllowed", 0)
        redeemed = access_grant.get("status", {}).get("redeemed", 0)
        return redeemed < allowed

    def load_from_grant(self, namespace, name):
        kubeconfig = self.params.get("kubeconfig") or os.path.join(
            os.getenv("HOME"), ".kube", "config")
        context = self.params.get("context")
        namespace = self.params.get("namespace")
        try:
            access_grant = {}
            for attempt in range(self._max_attempts):
                self.module.debug("retrieving accessgrants attempt %d/%d" %(attempt, self._max_attempts))
                access_grants = k8s_get(kubeconfig, context, namespace, "skupper.io/v2alpha1", "AccessGrant", name)
                if len(access_grants) == 0:
                    break
                match access_grants:
                    case dict():
                         if has_condition(access_grants, "Ready"):
                            access_grant = access_grants
                            break
                    case list():
                        all_ready = True
                        for access_grant_it in access_grants:
                            if has_condition(access_grant_it, "Ready"):
                                if self.can_be_redeemed(access_grant_it):
                                    access_grant = access_grant_it
                                    break
                            else:
                                all_ready = False
                        if all_ready:
                            break
                time.sleep(self._retry_delay)

            if name:
                if not has_condition(access_grant, "Ready") or not self.can_be_redeemed(access_grant):
                    raise RuntimeException(msg="accessgrant '%s' cannot be redeemed" % (name))

            if len(access_grant) == 0:
                return ""

            access_token_name = "token-%s" % (
                access_grant.get("metadata").get("name"))
            access_token_code = access_grant.get("status").get("code")
            access_token_url = access_grant.get("status").get("url")
            access_token_ca = access_grant.get("status").get("ca")
            access_token = {
                "apiVersion": "skupper.io/v2alpha1",
                "kind": "AccessToken",
                "metadata": {
                    "name": access_token_name,
                },
                "spec": {
                    "code": access_token_code,
                    "url": access_token_url,
                    "ca": access_token_ca,
                }
            }
            return yaml.safe_dump(access_token, indent=2)
        except K8sException as ex:
            if ex.status != 404:
                raise (ex)

    def generate_grant(self, namespace, name, redemptionsAllowed, expirationWindow):
        kubeconfig = self.params.get("kubeconfig") or os.path.join(
            os.getenv("HOME"), ".kube", "config")
        context = self.params.get("context")
        namespace = self.params.get("namespace")
        access_grant_dict = {
            "apiVersion": "skupper.io/v2alpha1",
            "kind": "AccessGrant",
            "metadata": {
                    "name": name,
            },
            "spec": {
                "redemptionsAllowed": redemptionsAllowed,
                "expirationWindow": expirationWindow,
            }
        }
        access_grant_def = yaml.safe_dump(access_grant_dict, indent=2)
        return create_or_patch(kubeconfig, context, namespace, access_grant_def, False)

    @property
    def params(self):
        return self.module.params


def main():
    module = AnsibleModule(
        argument_spec=argspec(),
        mutually_exclusive=mutualexc(),
        supports_check_mode=True
    )
    resource = TokenModule(module)
    resource.run()


if __name__ == '__main__':
    main()