class RuntimeException(Exception):
    def __init__(self, msg="") -> None:
        super().__init__(msg)
        self.msg = msg


class ResourceException(Exception):
    def __init__(self, msg="") -> None:
        super().__init__(msg)
        self.msg = msg


class K8sException(Exception):
    def __init__(self, msg="", status=0) -> None:
        super().__init__(msg)
        self.msg = msg
        self.status = status
