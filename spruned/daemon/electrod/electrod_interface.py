import asyncio
import binascii
from typing import Dict
from spruned.application import settings
from spruned.daemon import exceptions
from spruned.application.tools import blockheader_to_blockhash, deserialize_header, serialize_header
from spruned.daemon.electrod.electrod_connection import ElectrodConnectionPool


class ElectrodInterface:
    def __init__(self, connectionpool: ElectrodConnectionPool):
        self.pool = connectionpool
        self.pool.add_header_observer(self)
        self._checkpoints = settings.CHECKPOINTS

    def _parse_header(self, electrum_header: Dict):
        header_hex = serialize_header(electrum_header)
        blockhash_from_header = blockheader_to_blockhash(header_hex)
        if electrum_header['block_height'] in self._checkpoints:
            if self._checkpoints[electrum_header['block_height']] != blockhash_from_header:
                raise exceptions.NetworkHeadersInconsistencyException
        header_data = deserialize_header(header_hex)
        return {
            'block_hash': blockhash_from_header,
            'block_height': electrum_header['block_height'],
            'header_bytes': binascii.unhexlify(header_hex),
            'prev_block_hash': header_data['prev_block_hash'],
            'timestamp': header_data['timestamp']
        }

    def add_header_subscribe_callback(self, callback):
        self.pool.add_header_observer(callback)

    async def get_header(self, height: int, fail_silent_out_of_range=False):
        try:
            response = await self.pool.call('blockchain.block.get_header', height)
        except exceptions.NoQuorumOnResponsesException:
            if fail_silent_out_of_range:
                return
            raise
        return self._parse_header(response)

    async def handle_peer_error(self, peer):
        await self.pool.on_peer_error(peer)

    async def getrawtransaction(self, height: str, verbose=False):
        return await self.pool.call('blockchain.block.get_header', height, verbose)

    async def listunspents(self, address: str):
        return await self.pool.call('blockchain.address.listunspent', address)

    async def getaddresshistory(self, scripthash: str):
        return await self.pool.call('blockchain.address.get_history', scripthash)

    async def get_chunk(self, chunks_index: int):
        return await self.pool.call('blockchain.block.get_chunk', chunks_index)

    async def get_headers_in_range_from_chunks(self, starts_from: int, ends_to: int):
        futures = []
        for chunk_index in range(starts_from, ends_to):
            futures.append(self.get_headers_from_chunk(chunk_index))
        headers = []
        for _headers in await asyncio.gather(*futures):
            _headers and headers.extend(_headers)
        return headers

    async def get_headers_in_range(self, starts_from: int, ends_to: int):
        chunks_range = [x for x in range(starts_from, ends_to)]
        futures = []
        for i in chunks_range:
            futures.append(self.get_header(i))
        return await asyncio.gather(*futures)

    async def estimatefee(self, blocks: int):
        return await self.pool.call('blockchain.estimatefee', blocks)

    async def get_headers_from_chunk(self, chunk_index: int):
        chunk = await self.get_chunk(chunk_index)
        if not chunk:
            return
        hex_headers = [chunk[i:i + 160] for i in range(0, len(chunk), 160)]
        headers = []
        for i, header_hex in enumerate(hex_headers):
            header = deserialize_header(header_hex)
            header['block_height'] = int(chunk_index * 2016 + i)
            header['header_bytes'] = binascii.unhexlify(header_hex)
            header['block_hash'] = header.pop('hash')
            headers.append(header)
        return headers
