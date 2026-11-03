"""业务异常：message 会原样返回给前端"""


class BizError(Exception):
    def __init__(self, message: str, code: int = 400):
        self.message = message
        self.code = code
        super().__init__(message)
