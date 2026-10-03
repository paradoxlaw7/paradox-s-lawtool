class UserError(Exception):
    def __init__(self, message, status=400, code='invalid_request', request_id=None):
        super().__init__(message)
        self.status, self.code, self.request_id = status, code, request_id
