import os
import tempfile
import yaml
from unittest import TestCase
from unittest.mock import patch

from ansible_collections.fgiorgetti.skupperv2.tests.unit.utils.ansible_module_mock import (
    action_module_run,
    execute_module,
)


site = """apiVersion: skupper.io/v1alpha1
kind: Site
metadata:
  name: west
  namespace: west
spec:
  linkAccess: default
"""

listener = """apiVersion: skupper.io/v1alpha1
kind: Listener
metadata:
  name: backend
  namespace: west
spec:
  port: 8080
  host: backend
  routingKey: backend
"""

combined = "{}---\n{}".format(site, listener)

class TestResourceActionModule(TestCase):
    def setUp(self):
        self.mock_module = patch.multiple('ansible.plugins.action.ActionBase',
                                          _execute_module=execute_module,
                                          run=action_module_run)
        self.mock_module.start()
        self.addCleanup(self.mock_module.stop)

        self.temphome = tempfile.mkdtemp()

        try:
            from ansible_collections.fgiorgetti.skupperv2.plugins.action.resource import ActionModule
            self.module_class = ActionModule
        except:
            pass
    
    def test_no_args(self):
        module = init_action_module(self.module_class, {})
        result = module.run()
        self.assertEqual(len(result['module_args']), 0, result)

    def test_http_https_paths(self):
        for path_prefix in ["http", "https"]:
            path = "{}://sample.domain/resources.yaml".format(path_prefix)
            module = init_action_module(self.module_class, {
                "path": path,
            })
            result = module.run()
        self.assertEqual(len(result['module_args']), 1, result)
        self.assertEqual(result['module_args']['path'], path, result['module_args'])

    def test_remote_path(self):
        module = init_action_module(self.module_class, {
            "remote": "true",
            "path": "/some/remote/path/",
        })
        result = module.run()
        self.assertEqual(len(result['module_args']), 2, result)
        self.assertEqual(result['module_args']['path'], "/some/remote/path/", result['module_args'])

    def test_local_path_single_file(self):
        resource_file = os.path.join(self.temphome, "resources.yaml")
        with open(resource_file, "w") as f:
            f.write(combined)
        module = init_action_module(self.module_class, {
            "path": resource_file,
        })
        result = module.run()
        self._validate_local_definition(result)

    def test_local_path_multiple_files(self):
        files = {"site.yaml": site, "listener.yaml": listener}
        for file in files:
            res_file = os.path.join(self.temphome, file)
            with open(res_file, "w") as f:
                f.write(files[file])
        module = init_action_module(self.module_class, {
            "path": self.temphome,
        })
        result = module.run()
        self._validate_local_definition(result)
        
    def _validate_local_definition(self, result):
        self.assertEqual(len(result['module_args']), 1, result['module_args'])
        self.assertTrue('def' in result['module_args'], result['module_args'])
        self.assertTrue('path' not in result['module_args'])
        res_list = list(yaml.safe_load_all(result['module_args']['def']))
        self.assertEqual(2, len(res_list))
        for res in res_list:
            if res['kind'] == 'Site':
                self.assertEqual('west', res['metadata']['name'])
                self.assertEqual('default', res['spec']['linkAccess'])
            if res['kind'] == 'Listener':
                self.assertEqual('backend', res['metadata']['name'])
                self.assertEqual('8080', str(res['spec']['port']))
                self.assertEqual('backend', res['spec']['host'])
                self.assertEqual('backend', res['spec']['routingKey'])

class Task:
    def __init__(self, args: dict):
        self.args = args
        pass


def init_action_module(cls, args: dict):
    return cls(Task(args), None, None, None, None, None)
