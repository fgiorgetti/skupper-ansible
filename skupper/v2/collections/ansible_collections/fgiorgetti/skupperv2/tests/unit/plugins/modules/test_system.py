import io
import os
import tempfile
import yaml
from unittest import TestCase
from unittest.mock import MagicMock, patch, call
from kubernetes import client, config, dynamic
from kubernetes.dynamic.exceptions import ApiException
from ansible.module_utils import basic
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.k8s import K8sClient
from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.resource import (
    version_kind
)
from ansible_collections.fgiorgetti.skupperv2.tests.unit.utils.ansible_module_mock import (
    set_module_args,
    AnsibleExitJson,
    AnsibleFailJson,
    exit_json,
    fail_json,
    get_bin_path,
)


sample_site_def = """---
apiVersion: skupper.io/v2alpha1
kind: Site
metadata:
  name: my-site
spec:
  linkAccess: default
  settings:
    name: my-site
"""


class TestSystemModule(TestCase):

    def setUp(self):
        self._run_commands = []
        self._create_service_ns = ""
        self._create_service_ret = True
        self.mock_module = patch.multiple(basic.AnsibleModule,
                                          exit_json=exit_json,
                                          fail_json=fail_json,
                                          get_bin_path=get_bin_path)
        self.mock_module.start()
        self.addCleanup(self.mock_module.stop)

        # do not use real namespace path
        self.temphome = tempfile.mkdtemp()
        data_home_mock = lambda: self.temphome
        self.mock_data_home = patch('ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common.data_home', new=data_home_mock)
        self.mock_run_command = patch('ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.command.run_command', new=self.run_command)
        self.mock_create_service = patch('ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.create_service', new=self.create_service)
        self.mock_runas = patch('ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.runas', new=self.runas)
        self.mock_userns = patch('ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.userns', new=self.userns)
        self.mock_data_home.start()
        self.mock_run_command.start()
        self.mock_create_service.start()
        self.mock_runas.start()
        self.mock_userns.start()
        self.addCleanup(self.mock_data_home.stop)
        self.addCleanup(self.mock_run_command.stop)
        self.addCleanup(self.mock_create_service.stop)
        self.addCleanup(self.mock_runas.stop)
        self.addCleanup(self.mock_userns.stop)
        try:
            from ansible_collections.fgiorgetti.skupperv2.plugins.modules import system
            self.module = system
        except:
            pass

    def run_command(self, module, args) -> tuple[int, str, str]:
        self._run_commands.append(args)
        return 0, "", ""

    def create_service(self, module, namespace) -> bool:
        self._create_service_ns = namespace
        return self._create_service_ret

    def runas(self, engine) -> str:
        if engine == "podman":
            return "1000:1000"
        else:
            return "1000:1001"

    def userns(self, engine) -> str:
        if engine == "podman":
            return "keep-id"
        else:
            return "host"

    def create_resources(self, namespace: str):
        from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common import resources_home
        ns_home = resources_home(namespace)
        os.makedirs(ns_home, exist_ok=True)
        with open(os.path.join(ns_home, "resources.yaml"), "w", encoding="utf-8") as f:
            f.write(sample_site_def)

    def test_invalid_namespace(self):
        inputs = [
            {"namespace": "bad.namespace"},
        ]
        for input in inputs:
            with self.assertRaises(AnsibleFailJson) as ex:
                set_module_args(input)
                self.module.main()

    def test_state_setup_no_resources(self):
        with self.assertRaises(AnsibleFailJson) as ex:
            set_module_args({})
            self.module.main()
        self.assertTrue(str(ex.exception.__str__()).__contains__("no resources found"), ex.exception.msg)

    def test_state_setup_already_exists(self):
        pass

    def test_state_setup(self):
        test_cases = [
            {
                "name": "setup-minimal",
            }, {
                "name": "setup-default",
                "input": {
                    "namespace": "default",
                },
            }, {
                "name": "setup-default-docker",
                "input": {
                    "namespace": "default",
                    "platform": "docker",
                },
            }, {
                "name": "setup-west-podman",
                "input": {
                    "namespace": "west",
                    "engine": "podman",
                },
            }, {
                "name": "setup-west-systemd",
                "input": {
                    "namespace": "west",
                    "platform": "systemd",
                },
            },
        ]

        for i, tc in enumerate(test_cases):
            self._run_commands = []
            input = tc.get("input", {})
            namespace = input.get("namespace", "default")
            platform = input.get("platform", "podman")
            image = input.get("image", "quay.io/skupper/cli:v2-latest")
            self.create_resources(namespace)
            expectedExit = AnsibleExitJson
            if tc.get("expectFail", False):
                expectedExit = AnsibleFailJson
            with self.assertRaises(expectedExit) as exit:
                set_module_args(input)
                self.module.main()
            expectedEngine = tc.get("input", {}).get("engine", "podman")
            if platform == "docker":
                expectedEngine = platform
            self.assertEqual(1, len(self._run_commands), self._run_commands)
            first_command = self._run_commands[0]
            self.assertEqual(expectedEngine, first_command[0])
            self.assertIn(image, first_command)
            self.assertEqual(["-n", namespace, "system", "setup"], first_command[len(first_command)-4:])
            self.assertIn("SKUPPER_PLATFORM={}".format(platform), first_command)
            expectedRunAs = "1000:1000" if expectedEngine != "docker" else "1000:1001"
            self.assertIn(expectedRunAs, first_command)
            expectedUserns = "keep-id" if expectedEngine != "docker" else "host"
            self.assertIn("--userns={}".format(expectedUserns), first_command)
            self.assertIn("{}:/output:z".format(self.temphome), first_command)
            self.assertIn("{}/namespaces/{}/input/resources:/input:z".format(self.temphome, namespace), first_command)
            self.assertNotIn("-f", first_command)
            self.assertNotIn("-b", first_command)
            self.assertEqual(namespace, self._create_service_ns)

        # test cases
        # engine (podman and docker)
        # validations
        # -b not passed
        # -f not passed
        # assert create service called


    def test_state_reload(self):
        pass

    def test_state_teardown(self):
        pass

    def test_state_start(self):
        pass

    def test_state_stop(self):
        pass

    def test_state_bundle(self):
        pass

    def test_state_tarball(self):
        pass
