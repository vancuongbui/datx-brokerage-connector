import requests
from typing import List
from requests.adapters import HTTPAdapter, Retry
from .datatypes import Portfolio, Order
from datetime import date, datetime, timedelta
from urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

DEFAULT_HEADERS = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36',
        'sec-ch-ua': '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"macOS"'
        }

class BaseTradingAccount:
    def __init__(self, username, password, pin, trading_account_id) -> None:
        self.username = username 
        self.password = password
        self.pin = pin
        self.trading_account_id = trading_account_id # Mã tiểu khoản sử dụng để giao dịch
        self.session = self.create_session() # For DatX interaction with Brokerage purposes        

    
    def login(self, smart_otp=False):
        raise NotImplementedError
    
    def place_order(self, order:Order, *args, **kwargs) -> Order:
        raise NotImplementedError
    
    def cancel_order(self, *args, **kwargs) -> bool:
        raise NotImplementedError
    
    def get_current_orders(self, start_date: date=(datetime.now() - timedelta(days=1)).date()) -> List[Order]:
        # Get today order of trading account
        raise NotImplementedError
    
    def get_current_portfolio(self) -> Portfolio:
        raise NotImplementedError
    
    def create_session(self) -> requests.Session:
        session = requests.Session()
        retries = Retry(total=5,
                        backoff_factor=0.1,
                        status_forcelist=[ 500, 502, 503, 504 ])
        session.mount('https://', HTTPAdapter(max_retries=retries))
        session.headers.update(DEFAULT_HEADERS)
        return session

    def request(self, *args, **kwargs) -> requests.Response:
        ## Sử dụng cho việc tự đăng nhập lại khi token hết hạn
        retried = kwargs.pop("retried",False)
        resp = self.session.request(*args, **kwargs)
        if resp.status_code == 401 and not retried:
            self.login()
            return self.request(*args, **kwargs, retried=True)
        return resp
        
