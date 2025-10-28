import json
import re

from ansible.module_utils import basic
from ansible.module_utils.common.text.converters import to_bytes


def set_module_args(args):
    """prepare arguments so that they will be picked up during module creation"""
    args = json.dumps({'ANSIBLE_MODULE_ARGS': args})
    basic._ANSIBLE_ARGS = to_bytes(args)
    basic._ANSIBLE_PROFILE = "legacy"


class AnsibleExitJson(Exception):
    """Exception class to be raised by module.exit_json and caught by the test case"""
    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.__dict__.update(*args)


class AnsibleFailJson(Exception):
    """Exception class to be raised by module.fail_json and caught by the test case"""
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args)
        self.msg = kwargs.get('msg')
        self.__dict__.update(*args)
    pass


def exit_json(*args, **kwargs):
    """function to patch over exit_json; package return data into an exception"""
    if 'changed' not in kwargs:
        kwargs['changed'] = False
    raise AnsibleExitJson(kwargs)


def fail_json(*args, **kwargs):
    """function to patch over fail_json; package return data into an exception"""
    kwargs['failed'] = True
    if args:
        kwargs['msg'] = args
    raise AnsibleFailJson(kwargs)


def execute_module(*args, **kwargs):
    return kwargs


def action_module_run(*args):
    return {}


def get_bin_path(self, arg, required=False):
    """Mock AnsibleModule.get_bin_path"""
    if arg.endswith('my_command'):
        return '/usr/bin/my_command'
    else:
        if required:
            fail_json(msg='%r not found !' % arg)


def self_client(*args, **kwargs):
    print("self.client called")
    pass


class CommandArgs(object):
    def __init__(self, args: list, prefix: bool = False):
        self.args = args
        self.prefix = prefix
        self._matched: int = 0

    def __eq__(self, value):
        return self.args == value.args and self.prefix == value.prefix

    def __hash__(self):
        return hash("{}-{}".format(self.prefix, self.args))

    def __repr__(self):
        return f"CommandArgs(args={self.args},prefix={self.prefix})"

    def matches(self, args: list) -> bool:
        result = False
        if self.prefix:
            result = self.args == args[:len(self.args)]
        else:
            result = self.args == args
        if result:
            self._matched += 1
        return result

    def matched(self) -> bool:
        return self._matched > 0


class CommandResponse(object):
    def __init__(self, code=0, out="", err=""):
        self.code: int = code
        self.out : str = out
        self.err : str = err

class RegexMatcher:
    def __init__(self, pattern):
        self.pattern = pattern

    def __eq__(self, other):
        return re.match(self.pattern, other) is not None
