"""Errors returned by the account client and Creator."""


class OpenMCPError(Exception):
    def __init__(self, code, message, status=400, retryable=False):
        self.code, self.message, self.status, self.retryable = code, message, status, retryable
        super().__init__(message)

    def as_dict(self):
        return {"code": self.code, "message": self.message, "retryable": self.retryable}
