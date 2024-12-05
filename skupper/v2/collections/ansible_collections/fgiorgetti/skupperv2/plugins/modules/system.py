#!/usr/bin/python

from __future__ import (absolute_import, division, print_function)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.args import (
    common_args
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common import (
    is_non_kube,
    data_home,
    namespace_home,
    service_dir,
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.resource import (
    load,
    version_kind
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system import (
    mounts,
    env,
    runas,
    userns,
    create_service,
    start_service,
    stop_service
)
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.command import (
    run_command
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
import base64
import copy
__metaclass__ = type

DOCUMENTATION = r'''
---
module: system

short_description: Manages the lifecycle of non-kube namespaces

version_added: "2.0.0"

description: |
    Manages the lifecycle of non-kube namespaces.

    * Controls the state of a non-kube site running on a given namespace
    * It can be used to setup, reload, start, stop and teardown a namespace definition
    * It has the ability to produce a self-extracting or a tarball bundle
    * Runs with podman (default) or docker binaries
    * Only valid for platforms: podman, docker and systemd

options:
    state:
        description:
        - The state of a given namespace
        - setup: a new site is initialized and started (no-op if namespace is already initialized)
        - reload: a site is created or re-initialized (Certificate Authorities are preserved)
        - start: components are started
        - stop: components are stopped
        - teardown: stops and removes a site definition
        - bundle: generates a self-extracting bundle
        - tarball: generates a tarball bundle
        type: str
        choices: ["setup", "reload", "start", "stop", "teardown", "bundle", "tarball"]
        default: setup
    image:
        description:
        - The image used to initialize your site or bundle
        type: str
        default: quay.io/skupper/bootstrap:v2-latest
    engine:
        description:
        - The container engine used to manage a namespace or produce a bundle
        - It is only used when the platform is set to systemd or when state is bundle or tarball (otherwise the platform value is used)
        type: str
        default: podman
        choices: ["podman", "docker"]
extends_documentation_fragment:
  - fgiorgetti.skupperv2.common_options

requirements:
  - "python >= 3.9"
  - "PyYAML >= 3.11"

author:
    - Fernando Giorgetti (@fgiorgetti)
'''

RETURN = r"""
path:
  description:
  - Path to the generated namespace or to a produced site bundle
  returned: success
  type: str
bundle:
  description:
  - Base 64 encoded content of the generated bundle or tarball
  - Only populated when state is bundle or tarball
  returned: success
  type: str
"""

EXAMPLES = r'''
# Initializes the default namespace based on existing resources
- name: Initialize the default namespace using podman
  fgiorgetti.skupperv2.system:

# Initializes the west namespace using docker
- name: Initialize the west namespace using docker
  fgiorgetti.skupperv2.system:
    platform: docker
    namespace: west

# Reloads the definitions for the west namespace
- name: Initialize the west namespace
  fgiorgetti.skupperv2.system:
    state: reload
    namespace: west

# Removes a site definition from the west namespace
- name: Removes the west namespace
  fgiorgetti.skupperv2.system:
    state: teardown
    namespace: west

# Stops the skupper components on a given namespace
- name: Stops the components on the east namespace
  fgiorgetti.skupperv2.system:
    state: stop
    namespace: east

# Starts the skupper components on a given namespace
- name: Starts the components on the east namespace
  fgiorgetti.skupperv2.system:
    state: start
    namespace: east

# Produces a self-extracting site bundle based on the default namespace definitions
- name: Generate a self-extracting site bundle
  fgiorgetti.skupperv2.system:
    state: bundle
    register: result

# Produces a tarball bundle based on the west namespace definitions
- name: Generate a tarball bundle based on west namespace definitions
  fgiorgetti.skupperv2.system:
    state: tarball
    namespace: west
    register: result
'''


def argspec():
    spec = copy.deepcopy(common_args())
    spec["state"] = dict(type="str", default="setup",
                         choices=["setup", "reload", "teardown",
                                  "stop", "start", "bundle", "tarball"])
    spec["image"] = dict(type="str",
                         default="quay.io/skupper/bootstrap:v2-latest")
    spec["engine"] = dict(type="str", default="podman",
                          choices=["podman", "docker"])
    return spec


class SystemModule:
    def __init__(self, module: AnsibleModule):
        self.module = module
        self._state = self.params.get("state")
        self._image = self.params.get("image")
        self._engine = self.params.get("engine")

    def run(self):
        result = dict(
            changed=False,
        )
        if self.module.check_mode:
            self.module.exit_json(**result)

        # TODO disable debug mode
        self.module._debug = True

        platform = self.params.get("platform") or "podman"
        namespace = self.params.get("namespace") or "default"

        if not is_non_kube(platform):
            platform = "podman"

        changed = False
        path = namespace_home(namespace)
        match self._state:
            case "setup":
                changed = self.setup(platform, namespace)
            case "reload":
                changed = self.setup(platform, namespace, force=True)
            case "teardown":
                changed = self.teardown(namespace)
            case "start":
                changed = start_service(self.module, namespace)
            case "stop":
                changed = stop_service(self.module, namespace)
            case "bundle":
                changed = self.setup(platform, namespace, strategy="bundle")
            case "tarball":
                changed = self.setup(platform, namespace, strategy="tarball")

        # handling bundle return
        if self._state in ("bundle", "tarball"):
            site_name = self._read_site_name(platform, namespace)
            path = ""
            if site_name:
                ext = "sh" if self._state == "bundle" else "tar.gz"
                file_name = "skupper-install-%s.%s" % (site_name, ext)
                path = os.path.join(data_home(), "bundles", file_name)
                with open(path, 'rb') as bundle:
                    bundle_encoded = base64.b64encode(bundle.read())
                    result['bundle'] = bundle_encoded.decode('utf-8')

        # preparing response
        result["path"] = path
        result['changed'] = changed
        self.module.exit_json(**result)

    @property
    def params(self):
        return self.module.params

    def setup(self, platform: str, namespace: str = "default", force: bool = False, strategy: str = "") -> bool:
        self.module.debug("namespace: %s" %(namespace))
        runtime_dir = os.path.join(namespace_home(namespace), "runtime")
        if not strategy and os.path.isdir(runtime_dir) and not force:
            self.module.warn("namespace '%s' already exists" % (namespace))
            return False
        try:
            os.makedirs(data_home(), exist_ok=True)
        except OSError as ex:
            self.module.fail_json(
                "unable to create skupper base directory '%s': %s" % (data_home(), ex))

        volume_mounts = mounts(platform, self._engine)
        env_vars = env(platform, self._engine)

        command = [
            self._engine, "run", "--rm", "--name",
            "skupper-setup-%d" % (int(time.time())),
            "--network", "host", "--security-opt", "label=disable", "-u",
            runas(self._engine), "--userns=%s" % (userns(self._engine))
        ]
        for source, dest in volume_mounts.items():
            command.extend(["-v", "%s:%s:z" % (source, dest)])
        for var, val in env_vars.items():
            command.extend(["-e", "%s=%s" % (var, val)])
        command.append(self._image)
        command.extend(["/app/bootstrap", "-n", namespace])
        if strategy:
            command.extend(["-b", strategy])
        elif force:
            command.append("-f")

        code, out, err = run_command(self.module, command)
        if code != 0:
            msg = "error setting up '%s' namespace: %s" % (namespace, out or err)
            self.module.fail_json(msg)
            return False

        if not strategy:
            create_service(self.module, namespace)

        return True
    
    def _read_site_name(self, platform: str, namespace: str = "default") -> str:
        home = namespace_home(namespace)
        resources_path = os.path.join(home, "input", "resources")
        resources_str = load(resources_path, platform)
        site_name = ""
        for res in yaml.safe_load_all(resources_str):
            if not res or type(res) != dict:
                continue
            _, kind = version_kind(res)
            if kind != "Site":
                continue
            site_name = res.get("metadata", {}).get("name", "")
            break
        if not site_name:
            self.module.warn(
                "unable to identify site name on namespace: '%s'" % (namespace))
        return site_name


def main():
    module = AnsibleModule(
        argument_spec=argspec(),
        mutually_exclusive=[],
        supports_check_mode=True
    )
    resource = SystemModule(module)
    resource.run()


if __name__ == '__main__':
    main()
