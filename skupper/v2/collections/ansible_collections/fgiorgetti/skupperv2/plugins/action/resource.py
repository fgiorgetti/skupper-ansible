#!/usr/bin/python
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.plugins.action import ActionBase
from ansible.utils.display import Display
from ..module_utils.resource import load


display = Display()


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = {}

        result = super(ActionModule, self).run(tmp, task_vars)
        module_args = self._task.args.copy()
        platform = module_args.get("platform")

        # resources must be loaded and provided as part of arguments
        if "path" in module_args:
            if "remote" not in module_args or module_args["remote"] is False:
                # Load resources and pass them through "definition" argument
                if not module_args.get("path", "").startswith(("http://", "https://")):
                    module_args["def"] = load(module_args["path"], platform)
                    del module_args["path"]

        module_return = self._execute_module(module_name='fgiorgetti.skupperv2.resource',
                                             module_args=module_args,
                                             task_vars=task_vars, tmp=tmp)
        result.update(module_return)
        return result
