class WrongCredentialError(Exception):
    "Raise when account credential is invalid!"
    def __init__(self, message="The given credential is invalid!"):
        super().__init__(message)


class WrongTradingAccountID(Exception):
    "Raise when trading account id is invalid!"
    def __init__(self, message="The given trading account id is invalid!"):
        super().__init__(message)
