from dataclasses import dataclass, field
from typing import List, Literal
from datetime import datetime

@dataclass
class StockAllocation:
    symbol: str
    quantity: float
    available_quantity: float
    avg_buy_price: float # ĐVT: Nghìn đồng
    current_value: float # ĐVT: Nghìn đồng: Giá trị hiện tại của số cổ phiêu đang nắm giữ

@dataclass
class Portfolio:
    total_assets: float = field(init=False) # ĐVT: Nghìn đồng
    total_cash: float # ĐVT: Nghìn đồng
    total_loan: float # ĐVT: Nghìn đồng
    available_cash: float # ĐVT: Nghìn đồng
    stock_allocations: List[StockAllocation]
    total_stock_value: float = field(init=False) # ĐVT: Nghìn đồng

    def __post_init__(self):
        self.total_stock_value = sum([allocation.current_value for allocation in self.stock_allocations]) if self.stock_allocations else 0
        self.total_assets = self.total_cash + self.total_stock_value

@dataclass
class Order:
    __table_name__ = 'copy_trading_order'
    symbol: str
    quantity: float
    trading_account_id: str
    portfolio_proportion: float=0
    trade_type: Literal['buy', 'sell'] = 'sell' # buy or sell
    order_type: Literal['LO', 'MP', 'ATO', 'ATC'] = 'LO' # types of order
    price: float = 0 
    id: str = None
    copy_from_order_id: str = None
    avg_matched_price: float = 0
    matched_quantity: float = 0 # matched quantity
    created_at: datetime = datetime.now()
    matched_at: datetime = None
    type: Literal['market', 'limit'] = 'market'
    status: Literal['placing', 'matched', 'cancelled', 'rejected'] = 'placing'
    revived: bool = False
    
    def upsert(self):
        print(f"Upsert order {self} to table {self.__table_name__}")
        pass

    def create_table(self):
        pass
