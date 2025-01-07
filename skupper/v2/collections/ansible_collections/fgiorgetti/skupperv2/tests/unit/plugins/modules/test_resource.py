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
---
apiVersion: skupper.io/v2alpha1
kind: RouterAccess
metadata:
  name: access-my-site
spec:
  roles:
    - port: 55671
      name: inter-router
    - port: 45671
      name: edge
  bindHost: 0.0.0.0
  subjectAlternativeNames:
    - my.site.hostname
---
apiVersion: skupper.io/v2alpha1
kind: Listener
metadata:
  name: backend
spec:
  host: 0.0.0.0
  port: 8080
  routingKey: backend
"""


class K8sMock():
    def __init__(self, *args, **kwargs) -> None:
        self._kind = None
        pass

    def load_kube_config(self, *args, **kwargs):
        pass

    def client_resources_get(self, api_version: str, kind: str):
        self._kind = kind
        return self

    def create(self, **kwargs):
        pass

    def get(self, **kwargs):
        pass

    def patch(self, **kwargs):
        pass

    def delete(self, **kwargs):
        pass


class TestResourceModule(TestCase):

    def setUp(self):
        self.store = {}
        self.k8s = K8sMock()
        self.mock_module = patch.multiple(basic.AnsibleModule,
                                          exit_json=exit_json,
                                          fail_json=fail_json,
                                          get_bin_path=get_bin_path)
        self.mock_k8s_config = patch.multiple(
            config, load_kube_config=self.k8s.load_kube_config)
        self.mock_k8s_client = patch.multiple(K8sClient, __init__=self.k8s.__init__,
                                              api=self.k8s.client_resources_get, create=True)
        self.mock_fetch_url = patch('ansible.module_utils.urls.fetch_url', new=self.fetch_url)
        self.mock_module.start()
        self.mock_k8s_config.start()
        self.mock_k8s_client.start()
        self.mock_fetch_url.start()
        self.addCleanup(self.mock_module.stop)
        self.addCleanup(self.mock_k8s_config.stop)
        self.addCleanup(self.mock_k8s_client.stop)
        self.addCleanup(self.mock_fetch_url.stop)

        self.k8s.create = self.k8s_create
        self.k8s.patch = self.k8s_patch
        self.k8s.delete = self.k8s_delete

        # do not use real namespace path
        self.temphome = tempfile.mkdtemp()
        resources_home_mock = lambda ns: os.path.join(self.temphome, ns, "input", "resources")
        self.mock_resources_home = patch('ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common.resources_home', new=resources_home_mock)
        self.mock_resources_home.start()
        self.addCleanup(self.mock_resources_home.stop)

        # resource module must be imported at last, otherwise fetch_url won't be patched
        try:
            from ansible_collections.fgiorgetti.skupperv2.plugins.module_utils.common import resources_home
            from ansible_collections.fgiorgetti.skupperv2.plugins.modules import resource
            self.module = resource
            self.resources_home = resources_home
        except:
            pass

    def test_mutually_exclusive_args(self):
        inputs = [
            {"path": "file.yaml", "def": "resource definition"},
            {"def": "resource definition", "remote": True},
        ]
        for input in inputs:
            with self.assertRaises(AnsibleFailJson) as ex:
                set_module_args(input)
                self.module.main()

    def test_module_fail_when_required_args_missing(self):
        with self.assertRaises(AnsibleFailJson):
            set_module_args({})
            self.module.main()

    def test_module_fail_bad_args(self):
        with self.assertRaises(AnsibleFailJson):
            set_module_args({"namespace": "invalid.name"})
            self.module.main()

    def test_nonkube_path_local_directory(self):

        test_cases = [
            {
                "name": "create new entry using state present",
                "expectChanged": True,
                "storedObjects": 3,
                "state": "present",
            }, {
                "name": "create existing entry using state present",
                "expectChanged": False,
                "storedObjects": 3,
                "state": "present",
            }, {
                "name": "create existing entry using state latest",
                "state": "latest",
                "storedObjects": 3,
                "expectChanged": True,
            }, {
                "name": "deleting all entries using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": True,
            }, {
                "name": "no changes on empty store using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": False,
            }
        ]
        for subdir in [False, True]:
            path = tempfile.mkdtemp()
            store_path = path
            if subdir:
                store_path = os.path.join(path, "subdir")
                os.mkdir(store_path)
            filename = os.path.join(store_path, "resources.yaml")
            with open(filename, "w", encoding='utf-8') as f:
                f.write(sample_site_def)
            for test_case in test_cases:
                set_module_args({
                    'path': path,
                    'state': test_case.get("state", ""),
                    'platform': 'podman',
                })

                with self.assertRaises(AnsibleExitJson) as result:
                    self.module.main()
                self.assertTrue(
                    result.exception.args[0]['changed'] == test_case.get("expectChanged", False),
                    "{} - {}".format(test_case.get("name"), result.exception)
                )
                storedObjects = 0
                for file in ["Site-my-site", "RouterAccess-access-my-site", "Listener-backend"]:
                    filename = os.path.join(self.temphome, "default/input/resources/{}.yaml".format(file))
                    if os.path.isfile(filename):
                        storedObjects += 1
                self.assertEqual(test_case.get("storedObjects"), storedObjects,
                                "{} - {}".format(test_case.get("name"), result.exception))

    def test_kube_path_local_file(self):

        test_cases = [
            {
                "name": "create new entry using state present",
                "expectChanged": True,
                "storedObjects": 3,
                "state": "present",
            }, {
                "name": "create existing entry using state present",
                "expectChanged": False,
                "storedObjects": 3,
                "state": "present",
            }, {
                "name": "create existing entry using state latest",
                "state": "latest",
                "storedObjects": 3,
                "expectChanged": True,
            }, {
                "name": "deleting all entries using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": True,
            }, {
                "name": "no changes on empty store using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": False,
            }
        ]
        fd, fn = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w", encoding='utf-8') as f:
            f.write(sample_site_def)
        for test_case in test_cases:
            set_module_args({
                'path': fn,
                'state': test_case.get("state", "")
            })

            with self.assertRaises(AnsibleExitJson) as result:
                self.module.main()
            self.assertTrue(
                result.exception.args[0]['changed'] == test_case.get("expectChanged", False),
                "{} - {}".format(test_case.get("name"), result.exception)
            )
            self.assertEqual(test_case.get("storedObjects"), len(self.store), "incorrect amount of objects stored")


    def test_kube_path_http_file(self):

        test_cases = [
            {
                "name": "create new entry using state present",
                "expectChanged": True,
                "storedObjects": 3,
                "state": "present",
                "path": "https://my.fake.domain/data.yaml"
            }, {
                "name": "create existing entry using state present",
                "expectChanged": False,
                "storedObjects": 3,
                "state": "present",
                "path": "https://my.fake.domain/data.yaml"
            }, {
                "name": "create existing entry using state latest",
                "state": "latest",
                "storedObjects": 3,
                "expectChanged": True,
                "path": "https://my.fake.domain/data.yaml"
            }, {
                "name": "deleting all entries using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": True,
                "path": "https://my.fake.domain/data.yaml"
            }, {
                "name": "no changes on empty store using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": False,
                "path": "https://my.fake.domain/data.yaml"
            }, {
                "name": "invalid url",
                "state": "present",
                "storedObjects": 0,
                "expectChanged": False,
                "expectFail": True,
                "path": "https://my.fake.domain/data.yaml.bad"
            }
        ]
        for test_case in test_cases:
            set_module_args({
                'path': test_case.get("path", ""),
                'state': test_case.get("state", "")
            })
            expectFailed = test_case.get("expectFail", False)
            if not expectFailed:
                with self.assertRaises(AnsibleExitJson) as result:
                    self.module.main()
            else:
                with self.assertRaises(AnsibleFailJson) as result:
                    self.module.main()
            changed = 'changed' in result.exception.args[0] and result.exception.args[0]['changed']
            self.assertTrue(changed == test_case.get("expectChanged", False),
                "{} - {}".format(test_case.get("name"), result.exception)
            )
            failed = 'failed' in result.exception.args[0] and result.exception.args[0]['failed']
            self.assertTrue(failed == expectFailed, 
                            "{} - {}".format(test_case.get("name"), result.exception))
            self.assertEqual(test_case.get("storedObjects"), len(self.store), "incorrect amount of objects stored")


    def test_kube_def(self):

        test_cases = [
            {
                "name": "create new entry using state present",
                "expectChanged": True,
                "storedObjects": 3,
                "state": "present",
            }, {
                "name": "create existing entry using state present",
                "expectChanged": False,
                "storedObjects": 3,
                "state": "present",
            }, {
                "name": "create existing entry using state latest",
                "state": "latest",
                "storedObjects": 3,
                "expectChanged": True,
            }, {
                "name": "deleting all entries using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": True,
            }, {
                "name": "no changes on empty store using state absent",
                "state": "absent",
                "storedObjects": 0,
                "expectChanged": False,
            }
        ]
        for test_case in test_cases:
            set_module_args({
                'def': sample_site_def,
                'state': test_case.get("state", "")
            })

            with self.assertRaises(AnsibleExitJson) as result:
                self.module.main()
            self.assertTrue(
                result.exception.args[0]['changed'] == test_case.get("expectChanged", False),
                "{} - {}".format(test_case.get("name"), result.exception)
            )
            self.assertEqual(test_case.get("storedObjects"), len(self.store), "incorrect amount of objects stored")

    def k8s_create(self, **kwargs):
        if "body" not in kwargs:
            return
        obj = kwargs.get("body", {})
        _, kind = version_kind(obj)
        name = obj.get("metadata", {}).get("name")
        if not name:
            self.fail("bad name")
        key = "{}-{}".format(kind, name)
        overwrite = True if "overwrite" in kwargs and kwargs.get(
            "overwrite", False) else False
        if key in self.store:
            if not overwrite:
                raise ApiException(reason="Conflict")
        self.store[key] = obj

    def k8s_patch(self, **kwargs):
        self.k8s_create(body=kwargs.get("body"), overwrite=True)

    def k8s_delete(self, **kwargs):
        if "name" not in kwargs:
            return
        name = kwargs.get("name", "")
        kind = self.k8s._kind
        if not name:
            self.fail("bad name")
        key = "{}-{}".format(kind, name)
        if key in self.store:
            del self.store[key]
        else:
            raise ApiException(status=404)

    def fetch_url(self, *args, **kwargs) -> tuple[io.IOBase, dict]:
        url = kwargs.get("url", "")
        if not url or not str(url).endswith(".yaml"):
            return None, {"status": 404, "msg": "resource not found"}
        fd, fn = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w", encoding='utf-8') as f:
            f.write(sample_site_def)
        return open(fn, "r", encoding='utf-8'), {"status": 200}
