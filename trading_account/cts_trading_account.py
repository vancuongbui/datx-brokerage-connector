from .base_trading_account import BaseTradingAccount
import logging
from datetime import datetime, date
from .errors import WrongCredentialError, WrongTradingAccountID
from json import dumps
from uuid import uuid4
from .datatypes import StockAllocation, Portfolio, Order
from cachetools import cached, TTLCache

logger = logging.getLogger(__name__)

# Unlike BSC's, CTS's access_token expires in few minutes since login. So this class will automatically execute the login method before execute other method

def code_2_status(code):
    if code in [1, 7, 8]:
        return 'rejected'
    if code == 5:
        return 'matched'
    return 'placing'

class CTSTradingAccount(BaseTradingAccount):
    def __init__(self, username, password, pin, trading_account_id) -> None:
        super().__init__(username, password, pin, trading_account_id)
        self.access_token = None
        self.refresh_token = None
        self.trading_server = 'https://api-cts.datxasia.com'
        self.auth_server = 'https://uaa-cts.datxasia.com'

        self.deviceId = "bbe4a4e8032295d5" # required but doesn't matter
        self.deviceInfo = "{\"name\":\"SM-N985F\",\"model\":\"SM-N985F\",\"systemVersion\":\"11\"}" # required but doesn't matter
        
    @property
    def today(self):
        return datetime.now().strftime('%Y%m%d')
    
    def login(self, smart_otp=False):
        res = self.request(
            'POST',
            f"{self.auth_server}/api/third-party/login",
            headers={'subAccoNo': self.trading_account_id, 'Content-Type': 'application/x-www-form-urlencoded'}, 
            data='username=' + self.username + '&password=' + self.password, 
            verify=False
        )
        if res.status_code != 200:
            raise WrongCredentialError
        # assert res.status_code == 200, "Login failed with error code " + str(res.status_code)
        res = res.json()
        if res['errorCode'] == 401 and 'MSG3092' in res['message']:
            raise WrongTradingAccountID

        self.access_token = res['data']['access_token']
        self.refresh_token = res['data']['refresh_token']
        self.session_state = res['data']['session_state']
        self.session.headers = {
            'subAccoNo': self.trading_account_id, 
            'Authorization': 'Bearer ' + self.access_token, 
            'Content-Type': 'application/json'
        }
        self.gen_smart_otp()

    def gen_smart_otp(self):
        res = self.request(
            'POST',
            f"{self.trading_server}/api/generateSmartOtp",
            data=dumps({
                "custNo": self.username, 
                "sessionId": self.session_state, 
                "deviceId": self.deviceId, 
                "deviceInfo": self.deviceInfo,
                "requestId": str(uuid4()), 
                "pinCd": self.pin
            }), 
            verify=False
        )
        assert res.status_code == 200, "Smart OTP failed with error code " + str(res.status_code)
        res = res.json()
        self.smart_otp = res['data']['otp']

    # def place_order(self, tradeType, secCd, orderType, order_qty, order_price=0):
    def place_order(self, order: Order) -> Order:
        self.login()
        if order.trade_type == 'buy':
            trade_type = 2
        else:
            trade_type = 1
        res = self.request(
            'POST',
            f"{self.trading_server}/api/submitOrder",
            data=dumps({
                "subAccoNo": self.trading_account_id,
                "tradeType": trade_type, # 1-sell, 2-buy
                "secCd": order.symbol,
                "order_type": order.order_type, # LO, ATO, ATC
                "order_price": order.price,
                "order_qty": order.quantity,
                "sessionId": self.session_state,
                "deviceId": self.deviceId,
                "otp": self.smart_otp,
                "deviceInfo": self.deviceInfo,
                "requestId": str(uuid4())
            }),
            verify=False
        )
        assert res.status_code == 200, "Place order failed with error code " + str(res.status_code)
        res = res.json()

        if 'statusCode' in res:
            if res['statusCode'] == 0:
                order.id = res['data']['orgOrderNo']
                return order

        logger.info(res['message'])
        order.status = 'rejected'
        return order
    
    def cancel_order(self, order: Order) -> Order:
        self.login()
        res = self.request(
            'POST',
            f"{self.trading_server}/api/cancelOrder",
            headers={
            'subAccoNo': self.trading_account_id, 
            'Authorization': 'Bearer ' + self.access_token, 
            'Content-Type': 'application/json'
            },
            data=dumps({
                "tradeDate": int(self.today),
                "orgOrderNo": order.id,
                "otp": self.smart_otp,
                "sessionId": self.session_state,
                "deviceId": self.deviceId,
                "deviceInfo": self.deviceInfo,
                "requestId": str(uuid4())
            }), 
            verify=False
        )
        assert res.status_code == 200, "Cancel order failed"
        res = res.json()

        if 'statusCode' in res:
            if res['statusCode'] == 0:
                # order.status = 'cancelled'
                return True

        logger.error(f"Cancel Order from CTS got error {res}")
        return False
    
    def get_orders(self, start_date:date, ticker=''):
        self.login()

        orders = []

        if start_date is None:
            start_date = self.today

        tt = 'sell'
        for tradeType in ['1', '2']: # seperate request for buy and sell orders

            url = "https://api-cts.datxasia.com/api/findOrderByFilter?requestId=" + str(uuid4()) + "&tradeType=" + tradeType + "&secCd=" + ticker + "&extStatus&fromDate=" + start_date.strftime("%Y%m%d") + "&toDate=" + self.today

            res = self.request(
                'GET',
                url,
                # headers={'subAccoNo': self.trading_account_id, 'Authorization':  'Bearer ' + self.access_token},
                data={},
                verify=False
            )
            assert res.status_code == 200, "Get orders failed with error code " + str(res.status_code)
            res = res.json()

            assert 'statusCode' in res, "Get orders failed: " + res['message']
            assert res['statusCode'] == 0, "Get orders failed: statusCode " + str(res['statusCode']) + ' ' + res['message']

            if tradeType == '2':
                tt = 'buy'
            if res['data'] is not None:
                for _r in res['data']:
                    proportion = _r['matQty'] * _r['matPriceAvg'] / self.get_current_portfolio().total_assets
                    order = Order(
                        symbol=_r['secCd'], 
                        quantity=_r['ordQty'], 
                        trade_type=tt, 
                        order_type=_r['ordType'], 
                        price=_r['ordPrice'], 
                        id=_r['orgOrderNo'],
                        avg_matched_price=_r['matPriceAvg'],
                        matched_quantity=_r['matQty'],
                        created_at=datetime.fromtimestamp(_r['regDateTime'] / 1000),
                        matched_at=datetime.fromtimestamp(_r['updDateTime'] / 1000),
                        type='market',
                        status=code_2_status(_r['extStatus']),
                        portfolio_proportion=proportion,
                        trading_account_id=self.trading_account_id
                    )
                    orders.append(order)
        return orders

    def get_current_orders(self, start_date: date):
        return self.get_orders(start_date)
    
    @cached(cache=TTLCache(maxsize=1024, ttl=120))
    def get_current_portfolio(self):
        logger.info("Getting current portfolio from CTS")
        self.login()
        url = "https://api-cts.datxasia.com/api/inquiryAccountCashSec?subAccoNo=" + self.trading_account_id + "&requestId=" + str(uuid4())
        res = self.request(
            'GET',
            url,
            headers={'subAccoNo': self.trading_account_id, 'Authorization':  'Bearer ' + self.access_token},
            verify=False
        )
        assert res.status_code == 200, "Portfolio inquiry failed"
        res = res.json()

        assert 'statusCode' in res, "Get portfolio failed: " + res['message']
        assert res['statusCode'] == 0, "Get portfolio failed: statusCode " + str(res['statusCode']) + ' ' + res['message']

        res = res['data']
        print(res)
        
        stock_total_val = 0
        if res['secBalanceData2'] is not None:
            stock_allocations = []
            for stock in res['secBalanceData2']:

                quantity = stock['total'] + stock['pendingReceive']
                current_value = stock['currentPrice']/1000 * quantity
                stock_total_val += current_value

                stock_allocations.append(StockAllocation(
                    symbol=stock['secCode'],
                    quantity=quantity,
                    available_quantity=stock['availSale'],
                    avg_buy_price=0,
                    current_value=current_value,
                ))
        else:
            stock_allocations = []
        
        return Portfolio(
            total_cash=(res['casAmt'] - res['paymentTotal'])/1000,
            total_loan=0,
            available_cash=(res['buyingPower'])/1000,
            stock_allocations=stock_allocations
        )
