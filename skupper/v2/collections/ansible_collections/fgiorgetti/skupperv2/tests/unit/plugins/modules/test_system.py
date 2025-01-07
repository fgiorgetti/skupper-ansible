import base64
import os
import shutil
import tempfile
from unittest import TestCase
from unittest.mock import patch
from ansible.module_utils import basic
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

sample_link_template = """---
apiVersion: skupper.io/v2alpha1
kind: Link
metadata:
  name: link-my-site
spec:
  endpoints:
  - host: HOST
    name: inter-router
    port: "55671"
  - host: HOST
    name: edge
    port: "45671"
"""


class TestSystemModule(TestCase):

    def setUp(self):
        self._run_commands = []
        self._create_service_ns = ""
        self._create_service_ret = True
        self._create_delete_ns = ""
        self._start_service_ns = ""
        self._stop_service_ns = ""
        self.mock_module = patch.multiple(basic.AnsibleModule,
                                          exit_json=exit_json,
                                          fail_json=fail_json,
                                          get_bin_path=get_bin_path)
        self.mock_module.start()
        self.addCleanup(self.mock_module.stop)

        # do not use real namespace path
        self.temphome = tempfile.mkdtemp()
        def data_home_mock(): return self.temphome
        self.mock_data_home = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common.data_home', new=data_home_mock)
        self.mock_run_command = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.command.run_command', new=self.run_command)
        self.mock_create_service = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.create_service', new=self.create_service)
        self.mock_delete_service = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.delete_service', new=self.delete_service)
        self.mock_start_service = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.start_service', new=self.start_service)
        self.mock_stop_service = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.stop_service', new=self.stop_service)
        self.mock_runas = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.runas', new=self.runas)
        self.mock_userns = patch(
            'ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.system.userns', new=self.userns)
        self.mock_data_home.start()
        self.mock_run_command.start()
        self.mock_create_service.start()
        self.mock_delete_service.start()
        self.mock_start_service.start()
        self.mock_stop_service.start()
        self.mock_runas.start()
        self.mock_userns.start()
        self.addCleanup(self.mock_data_home.stop)
        self.addCleanup(self.mock_run_command.stop)
        self.addCleanup(self.mock_create_service.stop)
        self.addCleanup(self.mock_delete_service.stop)
        self.addCleanup(self.mock_start_service.stop)
        self.addCleanup(self.mock_stop_service.stop)
        self.addCleanup(self.mock_runas.stop)
        self.addCleanup(self.mock_userns.stop)
        try:
            from ansible_collections.fgiorgetti.skupperv2.plugins.modules import system
            self.module = system
        except:
            pass

    def clean_temp_home(self):
        shutil.rmtree(os.path.join(self.temphome, "namespaces"),
                      ignore_errors=True)
        shutil.rmtree(os.path.join(self.temphome, "bundles"),
                      ignore_errors=True)

    def run_command(self, module, args) -> tuple[int, str, str]:
        self._run_commands.append(args)
        if "-b" in args:
            bundles_home = os.path.join(self.temphome, "bundles")
            os.makedirs(bundles_home, exist_ok=True)
            if "bundle" in args:
                bundle = os.path.join(
                    bundles_home, "skupper-install-my-site.sh")
                with open(bundle, "w", encoding='utf-8') as f:
                    f.write("sample bundle script content")
            else:
                bundle = os.path.join(
                    bundles_home, "skupper-install-my-site.tar.gz")
                with open(bundle, "w", encoding='utf-8') as f:
                    f.write("sample bundle tarball content")
        else:
            # create some fake static links
            namespace = "default"
            for i, arg in enumerate(args):
                if arg == "-n":
                    namespace = args[i+1]
                    break
            links_home = os.path.join(
                self.temphome, "namespaces", namespace, "runtime", "links")
            os.makedirs(links_home, exist_ok=True)
            ra_name = "my-router-access"
            for host in ["0.0.0.0", "my.fake.domain"]:
                link_file = os.path.join(
                    links_home, "link-{}-{}.yaml".format(ra_name, host))
                with open(link_file, "w", encoding='utf-8') as f:
                    f.write(sample_link_template.replace("HOST", host))
        return 0, "", ""

    def create_service(self, module, namespace) -> bool:
        self._create_service_ns = namespace
        return self._create_service_ret

    def delete_service(self, module, namespace) -> bool:
        self._delete_service_ns = namespace
        return True

    def start_service(self, module, namespace) -> bool:
        if self._start_service_ns == namespace:
            return False
        self._start_service_ns = namespace
        return True

    def stop_service(self, module, namespace) -> bool:
        if self._stop_service_ns == namespace:
            return False
        self._stop_service_ns = namespace
        return True

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
        self.assertTrue(str(ex.exception.__str__()).__contains__(
            "no resources found"), ex.exception.msg)

    def test_state_setup_already_exists(self):
        for ns in ["default", "west"]:
            os.makedirs(os.path.join(self.temphome,
                        "namespaces", ns, "runtime"))
            with self.assertRaises(AnsibleExitJson) as exit:
                set_module_args({"namespace": ns})
                self.module.main()
        self.assertFalse(exit.exception.changed)

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
            }, {
                "name": "setup-east-docker",
                "input": {
                    "namespace": "west",
                    "platform": "docker",
                    "image": "quay.io/skupper/cli:latest",
                },
            },
        ]

        for tc in test_cases:
            self.clean_temp_home()
            self._run_commands = []
            self._create_service_ns = ""
            input = tc.get("input", {})
            namespace = input.get("namespace", "default")
            platform = input.get("platform", "podman")
            image = input.get("image", "quay.io/skupper/cli:v2-latest")
            self.create_resources(namespace)
            with self.assertRaises(AnsibleExitJson) as exit:
                set_module_args(input)
                self.module.main()
            self.assertTrue(exit.exception.changed)
            self.assertEqual(exit.exception.path, os.path.join(
                self.temphome, "namespaces", namespace))
            self.assertTrue(len(exit.exception.links)
                            > 0, exit.exception.links)
            expectedEngine = tc.get("input", {}).get("engine", "podman")
            if platform == "docker":
                expectedEngine = platform
            self.assertEqual(1, len(self._run_commands), self._run_commands)
            first_command = self._run_commands[0]
            self.assertEqual(expectedEngine, first_command[0])
            self.assertIn(image, first_command)
            self.assertEqual(["-n", namespace, "system", "setup"],
                             first_command[len(first_command)-4:])
            self.assertIn("SKUPPER_PLATFORM={}".format(
                platform), first_command)
            expectedRunAs = "1000:1000" if expectedEngine != "docker" else "1000:1001"
            self.assertIn(expectedRunAs, first_command)
            expectedUserns = "keep-id" if expectedEngine != "docker" else "host"
            self.assertIn("--userns={}".format(expectedUserns), first_command)
            self.assertIn("{}:/output:z".format(self.temphome), first_command)
            self.assertIn(
                "{}/namespaces/{}/input/resources:/input:z".format(self.temphome, namespace), first_command)
            self.assertNotIn("-f", first_command)
            self.assertNotIn("-b", first_command)
            self.assertEqual(namespace, self._create_service_ns)

    def test_state_reload(self):
        for existing in [False, True]:
            self._run_commands = []
            if existing:
                os.makedirs(os.path.join(self.temphome, "namespaces",
                            "default", "runtime"), exist_ok=True)
            self.create_resources("default")
            with self.assertRaises(AnsibleExitJson) as exit:
                set_module_args({"state": "reload"})
                self.module.main()
            self.assertTrue(exit.exception.changed)
            self.assertEqual(exit.exception.path, os.path.join(
                self.temphome, "namespaces", "default"))
            self.assertTrue(len(exit.exception.links)
                            > 0, exit.exception.links)
            expectedEngine = "podman"
            self.assertEqual(1, len(self._run_commands), self._run_commands)
            first_command = self._run_commands[0]
            self.assertEqual(expectedEngine, first_command[0])
            self.assertIn("quay.io/skupper/cli:v2-latest", first_command)
            self.assertEqual(["-n", "default", "system", "setup",
                             "-f"], first_command[len(first_command)-5:])
            self.assertIn("SKUPPER_PLATFORM=podman", first_command)
            self.assertIn("1000:1000", first_command)
            self.assertIn("--userns=keep-id", first_command)
            self.assertIn("{}:/output:z".format(self.temphome), first_command)
            self.assertIn(
                "{}/namespaces/default/input/resources:/input:z".format(self.temphome), first_command)
            self.assertNotIn("-b", first_command)
            self.assertEqual("default", self._create_service_ns)

    def test_state_bundle_tarball(self):
        for strategy in ["bundle", "tarball"]:
            self._run_commands = []
            self.create_resources("default")
            with self.assertRaises(AnsibleExitJson) as exit:
                set_module_args({"state": strategy})
                self.module.main()
            self.assertTrue(exit.exception.changed)
            expectedEngine = "podman"
            self.assertEqual(1, len(self._run_commands), self._run_commands)
            first_command = self._run_commands[0]
            self.assertEqual(expectedEngine, first_command[0])
            self.assertIn("quay.io/skupper/cli:v2-latest", first_command)
            self.assertEqual(["-n", "default", "system", "setup",
                             "-b", strategy], first_command[len(first_command)-6:])
            self.assertIn("SKUPPER_PLATFORM=podman", first_command)
            self.assertIn("1000:1000", first_command)
            self.assertIn("--userns=keep-id", first_command)
            self.assertIn("{}:/output:z".format(self.temphome), first_command)
            self.assertIn(
                "{}/namespaces/default/input/resources:/input:z".format(self.temphome), first_command)
            self.assertNotIn("-f", first_command)
            self.assertEqual("", self._create_service_ns)
            expectedBundleContent = "sample bundle script content"
            if strategy == "tarball":
                expectedBundleContent = "sample bundle tarball content"
            self.assertEqual(exit.exception.bundle.encode(),
                             base64.b64encode(expectedBundleContent.encode()))

    def test_state_teardown(self):
        test_cases = [{
            "name": "not_found",
        }, {
            "name": "removed_default",
            "expectChanged": True,
        }, {
            "name": "removed_default_docker",
            "expectChanged": True,
            "platform": "docker",
        }, {
            "name": "removed_default_systemd",
            "expectChanged": True,
            "platform": "systemd",
        }]
        for tc in test_cases:
            self._run_commands = []
            expect_changed = tc.get("expectChanged", False)
            namespace = tc.get("namespace", "default")
            platform = tc.get("platform", "podman")
            runtime_dir = os.path.join(
                self.temphome, "namespaces", namespace, "runtime")
            if expect_changed:
                os.makedirs(runtime_dir)
                with open(os.path.join(runtime_dir, "platform.yaml"), "w", encoding="utf-8") as f:
                    f.write("platform: {}".format(platform))
            with self.assertRaises(AnsibleExitJson) as exit:
                input = {
                    "state": "teardown",
                    "namespace": namespace,
                    "platform": platform,
                }
                set_module_args(input)
                self.module.main()
            self.assertEqual(exit.exception.changed, expect_changed)
            if not expect_changed:
                continue
            self.assertFalse(os.path.isdir(runtime_dir))
            if platform in ["podman", "docker"]:
                expected_command = [platform, "rm", "-f",
                                    "{}-skupper-router".format(namespace)]
                first_command = self._run_commands[0]
                self.assertEqual(expected_command,
                                 first_command, first_command)

    def test_state_start(self):
        test_cases = [{
            "namespace": "default",
            "expectChanged": True,
        }, {
            "namespace": "default",
            "expectChanged": False,
        }, {
            "namespace": "west",
            "expectChanged": True,
        }, {
            "namespace": "west",
            "expectChanged": False,
        }]
        for tc in test_cases:
            namespace = tc.get("namespace", "default")
            expect_changed = tc.get("expectChanged", False)
            with self.assertRaises(AnsibleExitJson) as exit:
                input = {
                    "state": "start",
                    "namespace": namespace,
                }
                set_module_args(input)
                self.module.main()
            self.assertEqual(expect_changed, exit.exception.changed)

    def test_state_stop(self):
        test_cases = [{
            "namespace": "default",
            "expectChanged": True,
        }, {
            "namespace": "default",
            "expectChanged": False,
        }, {
            "namespace": "west",
            "expectChanged": True,
        }, {
            "namespace": "west",
            "expectChanged": False,
        }]
        for tc in test_cases:
            namespace = tc.get("namespace", "default")
            expect_changed = tc.get("expectChanged", False)
            with self.assertRaises(AnsibleExitJson) as exit:
                input = {
                    "state": "stop",
                    "namespace": namespace,
                }
                set_module_args(input)
                self.module.main()
            self.assertEqual(expect_changed, exit.exception.changed)
