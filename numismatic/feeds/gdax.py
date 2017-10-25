import logging
import json
import time
from datetime import datetime

from streamz import Stream
import attr
import websockets

from .base import Feed, WebsocketClient
from ..libs.events import Heartbeat, Trade, LimitOrder, CancelOrder

logger = logging.getLogger(__name__)


class GDAXFeed(Feed):

    def __init__(self, **kwargs):
        self.rest_client = None
        self.websocket_client = GDAXWebsocketClient(**{a.name:kwargs[a.name] for a 
                                          in attr.fields(GDAXWebsocketClient)
                                          if a.name in kwargs})

    def get_list(self):
        raise NotImplemented()

    def get_info(self, assets):
        raise NotImplemented()
 
    def get_prices(self, assets, currencies):
        raise NotImplemented()       


@attr.s
class GDAXWebsocketClient(WebsocketClient):
    '''Websocket client for the GDAX WebsocketClient

    This currently opens a separate socket for every symbol that we listen to.
    This could probably be handled by having just one socket.
    '''

    wss_url = 'wss://ws-feed.gdax.com'
    exchange = 'GDAX'

    async def _subscribe(self, symbol, channel, wss_url=None):
        subscription = await super()._subscribe(symbol, channel, wss_url)
        msg = dict(type='subscribe', product_ids=symbol.split(','),
                   channels=channel.split(','))
        packet = json.dumps(msg)
        logger.info(packet)
        await self.websocket.send(packet)
        # FIXME: move this into a packet handler
        while True:
            packet = await self.websocket.recv()
            msg = self._handle_packet(packet, subscription)
            if isinstance(msg, dict) and 'type' in msg and \
                    msg['type']=='subscriptions':
                channel_info = msg
                logger.info(channel_info)
                break
        subscription.channel_info.update(channel_info)
        return subscription

    async def _unsubscribe(self, subscription):
        channel_info = subscription.channel_info
        symbols = {symbol for channel in channel_info['channels'] 
                   for symbol in channel['product_ids']}
        channels = [channel['name'] for channel in channel_info['channels']]
        msg = dict(type='unsubscribe', product_ids=list(symbols),
                   channels=channels)
        packet = json.dumps(msg)
        logger.info(msg)
        await self.websocket.send(msg)
        while True:
            packet = await self.websocket.recv()
            msg = self._handle_packet(packet, subscription)
            break
        return msg

    @staticmethod
    def handle_heartbeat(msg, subscription):
        if 'type' in msg and msg['type']=='heartbeat':
            event = Heartbeat(exchange=subscription.exchange, 
                              symbol=subscription, timestamp=timestamp)
            subscription.event_stream.emit(event)

    @staticmethod
    def handle_trade(msg, subscription):
        if 'type' in msg and msg['type']=='ticker' and 'trade_id' in msg:
            if 'product_id' in msg:
                symbol = msg['product_id'].replace('-', '')
            if 'time' in msg:
                dt = datetime.strptime(msg['time'], '%Y-%m-%dT%H:%M:%S.%fZ')
                timestamp = dt.timestamp()
            sign = -1 if ('side' in msg and msg['side']=='sell') else 1
            price = msg['price']
            volume = sign * msg['last_size'] if 'last_size' in msg else 0
            trade_id = msg['trade_id']
            msg = Trade(exchange=subscription.exchange, symbol=symbol, 
                        timestamp=timestamp, price=price, volume=volume,
                        id=trade_id)
            subscription.event_stream.emit(msg)


if __name__=='__main__':
    # Simple example of how these should be used
    # Test with: python -m numismatic.exchanges.bitfinex
    logging.basicConfig(level=logging.INFO)
    import asyncio
    from streamz import Stream
    output_stream = Stream()
    printer = output_stream.map(print)

    bfx = GDAXWebsocketClient(output_stream=output_stream)
    bfx_btc = bfx.listen('BTC-USD', 'ticker,heartbeat')

    loop = asyncio.get_event_loop()
    future = asyncio.wait([bfx_btc], timeout=15)
    completed, pending = loop.run_until_complete(future)
    for task in pending:
        task.cancel()
