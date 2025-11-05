from .base_trading_account import BaseTradingAccount
from .bsc_trading_account import BSCTradingAccount
from .cts_trading_account  import CTSTradingAccount

class TradingAccountFactory:
    def __init__(self):
        self._creators = {}
    
    def register_brokerage(self, brokerage, creator):
        self._creators[brokerage] = creator

    def get_trading_account(self, brokerage: str, *args, **kwargs) -> BaseTradingAccount:
        if brokerage not in self._creators:
            raise ValueError(f"Brokerage {brokerage} is not supported yet!")
        return self._creators[brokerage](*args, **kwargs)
    
trading_account_factory = TradingAccountFactory()
trading_account_factory.register_brokerage('BSC', BSCTradingAccount)
trading_account_factory.register_brokerage("CTS", CTSTradingAccount)