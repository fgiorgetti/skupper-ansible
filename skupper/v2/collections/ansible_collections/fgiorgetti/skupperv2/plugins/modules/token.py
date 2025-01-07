#!/usr/bin/python

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import time
import os
import glob
import copy
import yaml

from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.k8s import (
    K8sClient,
    has_condition
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.args import (
    common_args,
    is_valid_name,
    is_valid_host_ip
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common import (
    is_non_kube,
    namespace_home,
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.exceptions import (
    K8sException,
    RuntimeException
)
from ansible.module_utils.basic import AnsibleModule


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
    redemptions_allowed:
        description:
        - The number of claims the generated AccessGrant is valid for
        type: int
    expiration_window:
        description:
        - Duration of the generated AccessGrant
        - Sample values: 10m, 2h
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
    spec["redemptions_allowed"] = dict(type="int", default=1)
    spec["expiration_window"] = dict(type="str", default="15m")
    return spec


def mutualexc():
    return []


class TokenModule:
    max_attempts = 6
    retry_delay = 5

    def __init__(self, module: AnsibleModule):
        self.module = module
        self.name = self.params.get("name")
        self.host = self.params.get("host")
        self.platform = self.params.get("platform", "kubernetes")
        self.kubeconfig = self.params.get("kubeconfig") or \
            os.path.join(os.getenv("HOME"), ".kube", "config")
        self.context = self.params.get("context")
        self.namespace = self.params.get("namespace")
        if self.name and not is_valid_name(self.name):
            self.module.fail_json("invalid name (rfc1123): {}".format(self.name))
        if self.namespace and not is_valid_name(self.namespace):
            self.module.fail_json("invalid namespace (rfc1123): {}".format(self.namespace))
        if self.host and not is_valid_host_ip(self.host):
            self.module.fail_json("invalid host: {}".format(self.host))

    def run(self):
        result = dict(
            changed=False,
        )
        if self.module.check_mode:
            self.module.exit_json(**result)
        # self.module._debug = True

        changed = False
        token_link = ""

        if is_non_kube(self.platform):
            token_link = self.load_static_link()
        else:
            try:
                token_link = self.load_from_grant(self.name)
            except RuntimeException as runtime_ex:
                self.module.fail_json(runtime_ex.msg)
            except K8sException as k8s_ex:
                self.module.fail_json(k8s_ex.msg)
            if not token_link:
                grant_name = self.name or "ansible-grant-%d" % (
                    int(time.time()))
                try:
                    if not self.generate_grant(grant_name):
                        self.module.fail_json(
                            "unable to create AccessGrant: '%s'" % (grant_name))
                except Exception as ex:
                    self.module.fail_json(
                        "error creating AccessGrant: '%s' - reason: %s" % (grant_name, ex))
                changed = True
                try:
                    token_link = self.load_from_grant(grant_name)
                except RuntimeException as runtime_ex:
                    self.module.fail_json(runtime_ex.msg)
                except K8sException as k8s_ex:
                    self.module.fail_json(k8s_ex.msg)

        # adding return values
        if token_link:
            result['token'] = token_link

        result['changed'] = changed

        self.module.exit_json(**result)

    def load_static_link(self):
        home = namespace_home(self.namespace)
        links_path = os.path.join(home, "runtime", "links")
        links_search = os.path.join(
            links_path, "link-%s-%s.yaml" % (self.name or "*", self.host or "*"))
        links_found = glob.glob(links_search)
        for link in links_found:
            with open(link, "r", encoding='utf-8') as f:
                link_content = f.read()
                return link_content
        return ""

    def can_be_redeemed(self, access_grant: dict) -> bool:
        allowed = access_grant.get("spec", {}).get("redemptionsAllowed", 0)
        redeemed = access_grant.get("status", {}).get("redemptions", 0)
        return redeemed < allowed

    def load_from_grant(self, name: str) -> str:
        k8s = K8sClient(self.kubeconfig, self.context)
        self.wait_site_ready(k8s)
        access_grant = {}
        found_not_ready = False
        for attempt in range(self.max_attempts):
            self.module.debug("retrieving accessgrants attempt %d/%d"
                                % (attempt, self.max_attempts))
            access_grants = None
            try:
                access_grants = k8s.get(self.namespace, "skupper.io/v2alpha1", "AccessGrant", name)
            except K8sException as ex:
                if ex.status != 404:
                    raise ex
            if not access_grants or len(access_grants) == 0:
                break
            # give them a chance to be ready
            if isinstance(access_grants, dict):
                if has_condition(access_grants, "Ready"):
                    found_not_ready = False
                    access_grant = access_grants
                    break
                found_not_ready = True
            if isinstance(access_grants, list):
                access_grant, all_ready = self._load_from_list(access_grants)
                if all_ready:
                    break
            time.sleep(self.retry_delay)

        if found_not_ready:
            raise RuntimeException(
                msg="accessgrant '%s' is not ready" % (name))

        if len(access_grant) == 0:
            return ""

        if name:
            if not has_condition(access_grant, "Ready") or \
                not self.can_be_redeemed(access_grant):
                raise RuntimeException(
                    msg="accessgrant '%s' cannot be redeemed" % (name))

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

    def wait_site_ready(self, k8s):
        site_ready = False
        for attempt in range(self.max_attempts):
            try:
                sites = k8s.get(self.namespace, "skupper.io/v2alpha1", "Site", "")
                if not sites:
                    raise RuntimeException('no sites found on namespace "{}"'.format(self.namespace or "default"))
                for site in sites:
                    if has_condition(site, "Ready"):
                        site_ready = True
                        break
            except K8sException as ex:
                    if ex.status != 404:
                        raise ex
            if site_ready:
                break
            time.sleep(self.retry_delay)
        if not site_ready:
            raise RuntimeException('no ready sites found on namespace "{}"'.format(self.namespace or "default"))

    def _load_from_list(self, access_grants) -> tuple[dict, bool]:
        all_ready = True
        access_grant = {}
        for access_grant_it in access_grants:
            if not has_condition(access_grant_it, "Ready"):
                all_ready = False
                continue
            if not access_grant and self.can_be_redeemed(access_grant_it):
                access_grant = access_grant_it
        return access_grant, all_ready

    def generate_grant(self, name: str):
        k8s = K8sClient(self.kubeconfig, self.context)
        access_grant_dict = {
            "apiVersion": "skupper.io/v2alpha1",
            "kind": "AccessGrant",
            "metadata": {
                    "name": name,
            },
            "spec": {
                "redemptionsAllowed": self.params.get("redemptions_allowed"),
                "expirationWindow": self.params.get("expiration_window"),
            }
        }
        access_grant_def = yaml.safe_dump(access_grant_dict, indent=2)
        return k8s.create_or_patch(self.namespace, access_grant_def, False)

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
