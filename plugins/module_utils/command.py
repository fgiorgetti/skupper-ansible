from __future__ import (absolute_import, division, print_function)
__metaclass__ = type


import typing as t
from ansible.module_utils.basic import AnsibleModule


def run_command(module: AnsibleModule, command: list) -> t.Tuple[int, str, str]:
    try:
        module.debug("running command: %s" % (command))
        code, out, err = module.run_command(command, handle_exceptions=False)
        module.debug("code: %d" % (code))
        module.debug("stdout: %s" % (out))
        module.debug("stderr: %s" % (err))
        return code, out, err
    except Exception as ex:
        module.debug("exception running command %s: %s" % (command, str(ex)))
        return 1, "", str(ex)
