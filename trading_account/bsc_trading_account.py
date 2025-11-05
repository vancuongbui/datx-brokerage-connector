from trading_account.datatypes import Order
from .base_trading_account import BaseTradingAccount
import os
from sqlalchemy import create_engine, text
import re
from .datatypes import StockAllocation, Portfolio, Order
from .errors import WrongCredentialError
from datetime import datetime, timedelta, date
import logging
from cachetools import TTLCache, cached
import pandas as pd
from urllib.parse import quote
import json
from common.database_connector import factory

## API Document https://www.bsc.com.vn/Download/OpenApiDetail.html

logger = logging.getLogger(__name__)
uri = f'mysql+mysqlconnector://{os.environ["TOKEN_DB_USERNAME"]}:{quote(os.environ["TOKEN_DB_PASSWORD"])}@{os.environ["TOKEN_DB_HOST"]}/portfolioDataDb'


class BSCTradingAccount(BaseTradingAccount):
    def __init__(
        self,
        username,
        password=None,
        pin=None,
        trading_account_id=None,
        mode="prod",
        client_id=None,
        client_secret=None,
        url_callback=None,
        access_token=None,
        refresh_token=None,
    ) -> None:
        super().__init__(username, password, pin, trading_account_id)
        self.mode = mode
        self.access_token = access_token
        self.refresh_token = refresh_token
        if self.mode == "uat":
            self.sso_server = "https://apiuat.bsc.com.vn/sso"
            self.trading_server = "https://apiuat.bsc.com.vn/trading"
        else:
            self.sso_server = "https://api.bsc.com.vn/sso"
            self.trading_server = "https://api.bsc.com.vn"
        if client_id:
            self.client_id = client_id
        else:
            self.client_id = os.environ["BSC_CLIENT_ID"]

        if url_callback:
            self.url_callback = url_callback
        else:
            self.url_callback = os.environ["BSC_URL_CALLBACK"]

        if client_secret:
            self.client_secret = client_secret
        else:
            self.client_secret = os.environ["BSC_CLIENT_SECRET"]
        self.get_bsc_token()

    def login(self, smart_otp=False):
        endpoint = f"""{self.sso_server}/oauth/authorize?client_id={self.client_id}&response_type=code&redirect_uri={self.url_callback}&scope=general&ui_locales=en"""
        account_session = self.create_session()
        resp = account_session.get(endpoint, timeout=10)
        login_payload = {"username": self.username, "password": self.password}
        resp = account_session.post(resp.url, data=login_payload)
        transaction_id_pattern = 'name="transactionID" value="(.+)"'
        try:
            transaction_id = re.findall(transaction_id_pattern, resp.text)[0]
        except Exception as error:
            raise WrongCredentialError
        token_id_pattern = 'name="tokenID" value="(.+)"'
        token_id = re.findall(token_id_pattern, resp.text)[0]
        signed_base64 = "undefined"
        if (self.pin is None) or smart_otp:
            self.pin = input("Enter Smart OTP:")
        verification_payload = {
            "code": self.pin,
            "transactionID": transaction_id,
            "tokenID": token_id,
            "signedBase64": signed_base64,
        }
        resp = account_session.post(resp.url, data=verification_payload)
        permission_transaction_id_pattern = 'name="transaction_id" .+value="(.+)"'
        try:
            permission_transaction_id = re.findall(
                permission_transaction_id_pattern, resp.text
            )[0]
        except Exception as error:
            raise WrongCredentialError

        endpoint = f"{self.sso_server}/oauth/authorize/decision"
        resp = account_session.post(
            endpoint,
            data={"transaction_id": permission_transaction_id},
            allow_redirects=False,
        )

        self.consent_code = resp.headers["Location"].split("=")[-1]
        endpoint = f"{self.sso_server}/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "redirect_uri": self.url_callback,
            "code": str(self.consent_code),
        }
        resp = self.session.post(endpoint, data=payload)
        self.access_token = resp.json()["access_token"]
        self.refresh_token = resp.json()["refresh_token"]
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})
        self.update_bsc_token()
        # return resp

    def get_trading_accounts(self):
        endpoint = f"{self.trading_server}/accounts"
        resp = self.request("GET", url=endpoint)
        return resp.json()["d"]

    @cached(cache=TTLCache(maxsize=1024, ttl=120))
    def get_current_portfolio(self):
        state_endpoint = (
            f"{self.trading_server}/accounts/{self.trading_account_id}/state"
        )
        state_data = self.request("GET", url=state_endpoint).json()["d"]
        # Calculate total assets:
        available_cash = state_data["balance"] / 1000
        coming_cash = state_data["amData"][2][0][0] / 1000
        loan = state_data["amData"][1][0][0] / 1000
        total_cash = available_cash + coming_cash
        allocation_endpoint = (
            f"{self.trading_server}/accounts/{self.trading_account_id}/positions"
        )
        allocation_data = self.request("GET", url=allocation_endpoint).json()["d"]
        stock_allocations = []
        for record in allocation_data:
            symbol = record["instrument"]
            quantity = record["qty"]
            available_quantity = record["qty"]
            for _r in record["customFields"]:
                if _r["id"] == "1000":
                    quantity += _r["value"]
            avg_buy_price = record["avgPrice"] / 1000
            current_value = record["unrealizedPl"] / 1000 + quantity * avg_buy_price
            stock_allocation = StockAllocation(
                symbol=symbol,
                quantity=quantity,
                available_quantity=available_quantity,
                avg_buy_price=avg_buy_price,
                current_value=current_value,
            )
            stock_allocations.append(stock_allocation)
        portfolio = Portfolio(
            total_loan=loan,
            available_cash=available_cash,
            total_cash=total_cash,
            stock_allocations=stock_allocations,
        )
        return portfolio

    @cached(cache=TTLCache(maxsize=1024, ttl=120))
    def get_current_orders(self, start_date: date):
        endpoint = f"{self.trading_server}/accounts/{self.trading_account_id}/ordersHistory?maxCount=200"
        resp = self.request("GET", url=endpoint)
        data = resp.json()["d"]
        orders = []
        _status_mapping = {
            "filled": "matched",
            "placing": "placing",
            "cancelled": "cancelled",
        }
        _type_mapping = {"market": "market", "limit": "limit"}
        for r in data:
            status = _status_mapping[r["status"]]
            type = _type_mapping[r["type"]]
            order_created_at = datetime.fromtimestamp(r["lastModified"])
            if order_created_at.date() < start_date:
                continue
            matched_quantity = 0
            matched_at = None
            if status == "matched":
                matched_quantity = r["qty"]
                matched_at = order_created_at
            proportion = (
                matched_quantity
                * r["avgPrice"]
                / 1000
                / self.get_current_portfolio().total_assets
            )

            order = Order(
                id=r["id"],
                symbol=r["instrument"],
                quantity=r["qty"],
                type=type,
                status=status,
                avg_matched_price=r["avgPrice"] / 1000,
                created_at=order_created_at,
                trade_type=r["side"],
                matched_at=matched_at,
                matched_quantity=matched_quantity,
                trading_account_id=self.trading_account_id,
                portfolio_proportion=proportion,
            )
            orders.append(order)
        return orders

    def place_order(self, order: Order, *args, **kwargs) -> Order:
        endpoint = f"{self.trading_server}/accounts/{self.trading_account_id}/orders"
        logger.info(f"Placing order: {order}")
        logger.info(
            json.dumps(
                {
                    "instrument": order.symbol,
                    "qty": order.quantity,
                    "side": order.trade_type,
                    "type": order.order_type,
                    "limitPrice": order.price * 1000,
                    "stopPrice": order.price * 1000,
                }
            )
        )
        resp = self.request(
            "POST",
            url=endpoint,
            data={
                "instrument": order.symbol,
                "qty": order.quantity,
                "side": order.trade_type,
                "type": "limit",
                "limitPrice": order.price * 1000,
                "stopPrice": order.price * 1000,
            },
        ).json()

        if resp["s"] == "error":
            order.status = "rejected"
            logger.error(f"Error placing order from bsc {resp['errmsg']}")
            return order

        print(resp)
        order.id = resp["d"]["orderid"]
        return order

    def cancel_order(self, order: Order, *args, **kwargs) -> Order:
        endpoint = f"{self.trading_server}/accounts/{self.trading_account_id}/orders/{order.id}"
        logger.info(f"Canceling order: {order}")

        resp = self.request("DELETE", url=endpoint).json()

        if resp["s"] == "error":
            logger.error(f"Error canceling order from bsc {resp['errmsg']}")
            return False

        return True

    def update_bsc_token(self, is_valid: bool = True):
        logger.info(f"START UPDATE BSC TOKEN IN SQL TABLE FOR ACCOUNT {self.username}")
        if is_valid:
            all_trading_accounts = self.get_trading_accounts()
            all_trading_account_ids = [r['id'] for r in all_trading_accounts]
            account_id_str = "','".join(all_trading_account_ids)
            logger.info(f"START UPDATE BSC TOKEN IN SQL TABLE FOR ACCOUNT {self.username}")
            sql = f'''
            UPDATE bscTokenTable set access_token='{self.access_token}',
            refresh_token='{self.refresh_token}',is_valid=1,
            Time=now()
            where account_id in ('{account_id_str}')
            ;
            '''

        else:
            sql = f"""
            UPDATE bscTokenTable SET is_valid=false,
            Time=now()
            where bsc_account='{self.username}'; 
            """

        logger.info(sql)

        # dest_engine = create_engine('mysql+mysqlconnector://ubuntu:Invoice%402019@136.186.108.164/portfolioDataDb')
        dest_engine = create_engine(uri)
        with dest_engine.connect() as conn:
            conn.execute(text(sql))
            conn.commit()
        logger.info(f"BSC TOKEN IN SQL TABLE FOR ACCOUNT {self.username}")

    def get_bsc_token(self):
        logger.info(f"START GETTING BSC TOKEN IN SQL TABLE FOR ACCOUNT {self.username}")
        sql = f"""
        Select access_token from bscTokenTable where bsc_account='{self.username}' order by Time desc limit 1;
        """
        return
        # dest_engine = create_engine('mysql+mysqlconnector://ubuntu:Invoice%402019@136.186.108.164/portfolioDataDb')
        # dest_engine = create_engine(uri)

        # with dest_engine.connect() as conn:
        #     df = pd.read_sql(text(sql), con=conn)
        # if not df.empty:
        #     self.access_token = df["access_token"].values[0]
        #     self.session.headers.update(
        #         {"Authorization": f"Bearer {self.access_token}"}
        #     )
        #     logger.info("DONE GET TOKEN")
        # else:
        #     logger.warning("NOT FOUND TOKEN FROM MYSQL DB")

    def refresh_access_token(self):
        current_refresh_token = self.refresh_token

        url = "https://api.bsc.com.vn/sso/oauth/token"

        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": current_refresh_token,
        }
        logger.warning(f"Refresh BSC access token for {self.username} {payload=}")
        session = self.create_session()
        try:
            resp = session.request("POST", url, json=payload, timeout=5)
            logger.info(f"Refresh Token Resp {resp.json()=}")
            self.access_token = resp.json()["access_token"]
            self.refresh_token = resp.json()["refresh_token"]
            self.session.headers.update({"Authorization":f"Bearer {self.access_token}"})
            self.update_bsc_token(is_valid=True)
        except Exception as e:
            logger.error(repr(e))
            # self.update_bsc_token(is_valid=False)
            raise

        return {"access_token": self.access_token, "refresh_token": self.refresh_token}
