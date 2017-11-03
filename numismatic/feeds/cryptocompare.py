import math
import logging
import abc
import time
from datetime import timedelta
from dateutil.parser import parse
from itertools import product

import attr

from .base import Feed, RestClient
from ..events import PriceUpdate, Ticker
from ..libs.utils import date_range, make_list_str, to_datetime, \
    dates_and_frequencies


logger = logging.getLogger(__name__)


@attr.s
class CryptoCompareRestClient(RestClient):
    '''Low level API for CryptoCompare.com

    TODO:
      * This should use the json api to automatically generate the methods
    '''

    exchange = 'CryptoCompare'
    base_url = 'https://www.cryptocompare.com/api/data/'
    api_url = 'https://min-api.cryptocompare.com/data'

    def get_coinlist(self):
        api_url = f'{self.base_url}/coinlist'
        coinlist = self._make_request(api_url)
        return coinlist

    # FIXME: rename to get_price
    def get_latest_price(self, fsym, tsyms):
        api_url = f'{self.api_url}/price'
        tsyms = make_list_str(tsyms)
        query_str = f'{api_call}?fsym={fsym}&tsyms={tsyms}'
        return self._make_request(api_url, query_str)

    # FIXME: rename to get_price_multi
    def get_latest_price_multi(self, fsyms, tsyms):
        api_url = f'{self.api_url}/pricemulti'
        params = dict(fsyms=make_list_str(fsyms), tsyms=make_list_str(tsyms))
        return self._make_request(api_url, params)

    # FIXME: rename to get_price_multi_full
    def get_price_multi_full(self, fsyms, tsyms, raw=False):
        api_url = f'{self.api_url}/pricemultifull'
        params = dict(fsyms=make_list_str(fsyms), tsyms=make_list_str(tsyms))
        return self._make_request(api_url, params, raw=raw)

    def get_historical_price(self, fsym, tsyms, ts, markets=None):
        api_url = f'{self.api_url}/pricehistorical'
        tsyms = make_list_str(tsyms)
        params = dict(fsym=fsym, tsyms=tsyms, ts=ts, markets=markets)
        return self._make_request(api_url, params)

    def get_historical_day(self, fsym, tsym, e=None, limit=30, toTs=None,
                           allData=False):
        api_url = f'{self.api_url}/histoday'
        params = dict(fsym=fsym, tsym=tsym, e=e, limit=limit, toTs=toTs)
        return self._make_request(api_url, params)

    def get_historical_hour(self, fsym, tsym, e=None, limit=30, toTs=None):
        api_url = f'{self.api_url}/histohour'
        params = dict(fsym=fsym, tsym=tsym, e=e, limit=limit, toTs=toTs)
        return self._make_request(api_url, params)

    def get_historical_minute(self, fsym, tsym, e=None, limit=30, toTs=None):
        api_url = f'{self.api_url}/histominute'
        params = dict(fsym=fsym, tsym=tsym, e=e, limit=limit, toTs=toTs)
        return self._make_request(api_url, params)

    def _make_request(self, api_url, params=None, raw=False):
        data = super()._make_request(api_url, params, raw=raw)
        if 'Data' in data and not raw:
            data = data['Data']
        return data


@attr.s
class CryptoCompareFeed(Feed):

    _interval_limit = 2000
    _rest_client_class = CryptoCompareRestClient

    def get_list(self):
        return self.rest_client.get_coinlist()
        return coinlist.keys()

    def get_info(self, assets):
        assets = self._validate_parameter('assets', assets)
        coinlist = self.rest_client.get_coinlist()
        assets_info = [coinlist[a] for a in assets]
        return assets_info

    def get_prices(self, assets, currencies, raw=False):
        assets = self._validate_parameter('assets', assets)
        currencies = self._validate_parameter('currencies', currencies)
        # FIXME: SHouldn't use caching
        data = self.rest_client.get_latest_price_multi(assets, currencies)
        prices = [{'asset':asset, 'currency':currency, 'price':price}
                  for asset, asset_prices in data.items()
                  for currency, price in asset_prices.items()]
        if not raw:
            prices = [self.parse_price(msg) for msg in prices]
        return prices

    @staticmethod
    def parse_price(msg):
        if isinstance(msg, dict) and len(msg)==3 and \
                set(msg)=={'asset', 'currency', 'price'}:
            event = PriceUpdate(exchange='CryptoCompare',
                                symbol=msg['asset']+msg['currency'],
                                price=msg['price'])
            return event

    def get_tickers(self, assets, currencies, raw=False):
        assets = self._validate_parameter('assets', assets)
        currencies = self._validate_parameter('currencies', currencies)
        # FIXME: SHouldn't use caching
        data = self.rest_client.get_price_multi_full(assets, currencies)
        tickers = [msg if raw else self.parse_ticker(msg)
                  for asset, asset_updates in data['RAW'].items()
                  for currency, msg in asset_updates.items()]
        return tickers

    @staticmethod
    def parse_ticker(msg):
        if isinstance(msg, dict) and \
                {'PRICE', 'VOLUME24HOUR', 'VOLUME24HOURTO', 'OPEN24HOUR',
                 'HIGH24HOUR', 'LOW24HOUR'} <= set(msg):
            symbol = msg['FROMSYMBOL']+msg['TOSYMBOL']
            event = Ticker(exchange=msg['MARKET'],
                        symbol=symbol, price=msg['PRICE'],
                        volume_24h=msg['VOLUME24HOUR'],
                        value_24h=msg['VOLUME24HOURTO'],
                        open_24h=msg['OPEN24HOUR'],
                        high_24h=msg['HIGH24HOUR'],
                        low_24h=msg['LOW24HOUR'],
                        )
            return event

    def get_historical_data(self, assets, currencies, freq='d', end_date=None,
                            start_date=-30, exchange=None):
        assets = self._validate_parameter('assets', assets)
        currencies = self._validate_parameter('currencies', currencies)
        start_date, end_date, freqstr, intervals = \
            dates_and_frequencies(start_date, end_date, freq)
        limit = min(intervals, self._interval_limit)
        dates = date_range(start_date, end_date, **{freqstr:limit})

        data = []
        for asset, currency, (start, end) in \
                product(assets, currencies, zip(dates[:-1], dates[1:])):
            asset = asset.upper()
            currency = currency.upper()
            toTs = math.ceil(end.timestamp())
            limit = math.ceil((end-start)/timedelta(**{freqstr:1}))
            logger.debug(f'Getting {asset}/{currency} for {limit}{freqstr} to {end}')
            time.sleep(1/4)   # max 4 requests per second
            if freq.startswith('m'):
                chunk = self.rest_client.get_historical_minute(
                    fsym=asset, tsym=currency, e=exchange, limit=limit,
                    toTs=toTs)
            elif freq.startswith('h'):
                chunk = self.rest_client.get_historical_hour(
                    fsym=asset, tsym=currency, e=exchange, limit=limit,
                    toTs=toTs)
            elif freq.startswith('d'):
                chunk = self.rest_client.get_historical_day(
                    fsym=asset, tsym=currency, e=exchange, limit=limit,
                    toTs=toTs)
            else:
                raise NotImplementedError(f'freq={freq}')
            annotated_chunk = [{**{'asset':asset, 'currency':currency},
                                **item} for item in chunk]
            data.extend(annotated_chunk)
        return data
