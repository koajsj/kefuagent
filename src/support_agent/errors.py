class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def missing() -> AppError:
    return AppError(404, "resource_not_found", "Resource not found in the current tenant")


def forbidden() -> AppError:
    return AppError(403, "permission_denied", "Active membership and required role are necessary")
