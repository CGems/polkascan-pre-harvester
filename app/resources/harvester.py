#  Polkascan PRE Harvester
#
#  Copyright 2018-2019 openAware BV (NL).
#  This file is part of Polkascan.
#
#  Polkascan is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Polkascan is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Polkascan. If not, see <http://www.gnu.org/licenses/>.
#
#  harvester.py

import datetime
import uuid

import falcon
from celery.result import AsyncResult
from scalecodec import ScaleBytes
from scalecodec.block import RawBabePreDigest
from sqlalchemy.sql.operators import isnot

from app.models.data import Block, BlockTotal, Account, Log
from app.resources.base import BaseResource
from app.processors.converters import PolkascanHarvesterService, BlockAlreadyAdded
from substrateinterface import SubstrateInterface
from app.tasks import start_harvester
from app.settings import SUBSTRATE_RPC_URL, TYPE_REGISTRY


class PolkascanSyncAccounId(BaseResource):
    def on_get(self, req, resp):

        msg = "TODO"
        db_session = self.session
        blocks = Block.query(db_session).filter(Block.account_index.is_(None)).all()

        for block in blocks:
            log = Log.query(db_session).filter(Log.block_id == block.id).filter(Log.type == 'PreRuntime').first()
            if log:
                data = log.data.get("value").get("data")
                if data:
                    res = RawBabePreDigest(ScaleBytes("0x{}".format(data)))
                    print("............", data)
                    if data[0:2] == "01" and len(data) == 34:
                        res.decode()
                        block.account_index = res.value.get("Secondary").get("authorityIndex")
                    else:
                        res.decode(check_remaining=False)
                        block.account_index = res.value.get("Primary").get("authorityIndex")

                    block.save(db_session)
            else:
                resp.status = falcon.HTTP_404
                resp.media = {'result': 'Blocks not found'}

        resp.media = {
            'status': 'success',
            'data': {
                'message': msg
            }
        }


class PolkascanAccountBalance(BaseResource):
    ## POST raw
    def on_post(self, req, resp):

        msg = "TODO"
        if req.media.get('account_id'):
            account = Account.query(self.session).filter(Account.id == req.media.get('account_id')).first()

            if account:
                substrate = SubstrateInterface(SUBSTRATE_RPC_URL)
                balance = substrate.get_storage(
                    block_hash=None,
                    module='Balances',
                    function='FreeBalance',
                    params=account.id,
                    return_scale_type='Balance',
                    hasher='Blake2_256') or 0

                account.balance = balance
                self.session.commit()

                resp.media = {
                    'status': 'success',
                    'data': {
                        'message': msg
                    }
                }
        else:
            resp.status = falcon.HTTP_404
            resp.media = {'result': 'Account not found'}



class PolkascanBacktrackingResource(BaseResource):
    ## POST raw
    def on_post(self, req, resp):

        msg = "TODO"
        if req.media.get('start_hash'):
            block = Block.query(self.session).filter(Block.hash == req.media.get('start_hash')).first()
        else:
            block = Block.query(self.session).order_by(Block.id.asc()).first()

        if block and block.id != 1:
            harvester = PolkascanHarvesterService(self.session, type_registry=TYPE_REGISTRY)
            block_hash = block.parent_hash
            for nr in range(0, block.id - 1):
                try:
                    block = harvester.add_block(block_hash)
                except BlockAlreadyAdded as e:
                    print('Skipping {}'.format(block_hash))
                block_hash = block.parent_hash
                if block.id == 0:
                    break

            self.session.commit()

            resp.media = {
                'status': 'success',
                'data': {
                    'message': msg
                }
            }
        else:
            resp.status = falcon.HTTP_404
            resp.media = {'result': 'Block not found'}




class PolkascanStartHarvesterResource(BaseResource):

    #@validate(load_schema('start_harvester'))
    def on_post(self, req, resp):

        task = start_harvester.delay(check_gaps=True)

        resp.status = falcon.HTTP_201

        resp.media = {
            'status': 'success',
            'data': {
                'task_id': task.id
            }
        }


class PolkascanStopHarvesterResource(BaseResource):

    def on_post(self, req, resp):

        resp.status = falcon.HTTP_404

        resp.media = {
            'status': 'success',
            'data': {
                'message': 'TODO'
            }
        }


class PolkaScanCheckHarvesterTaskResource(BaseResource):

    def on_get(self, req, resp, task_id):

        task_result = AsyncResult(task_id)
        result = {'status': task_result.status, 'result': task_result.result}
        resp.status = falcon.HTTP_200
        resp.media = result


class PolkascanStatusHarvesterResource(BaseResource):

    def on_get(self, req, resp):

        last_known_block = Block.query(self.session).order_by(Block.id.desc()).first()

        if not last_known_block:
            resp.media = {
                'status': 'success',
                'data': {
                    'message': 'Harvester waiting for first run'
                }
            }
        else:

            remaining_sets_result = Block.get_missing_block_ids(self.session)

            resp.status = falcon.HTTP_200

            resp.media = {
                'status': 'success',
                'data': {
                    'harvester_head': last_known_block.id,
                    'block_process_queue': [
                        {'from': block_set['block_from'], 'to': block_set['block_to']}
                        for block_set in remaining_sets_result
                    ]
                }
            }


class PolkascanProcessBlockResource(BaseResource):

    def on_post(self, req, resp):

        block_hash = None

        if req.media.get('block_id'):
            substrate = SubstrateInterface(SUBSTRATE_RPC_URL)
            block_hash = substrate.get_block_hash(req.media.get('block_id'))
        elif req.media.get('block_hash'):
            block_hash = req.media.get('block_hash')
        else:
            resp.status = falcon.HTTP_BAD_REQUEST
            resp.media = {'errors': ['Either block_hash or block_id should be supplied']}

        if block_hash:
            print('Processing {} ...'.format(block_hash))
            harvester = PolkascanHarvesterService(self.session, type_registry=TYPE_REGISTRY)

            block = Block.query(self.session).filter(Block.hash == block_hash).first()

            if block:
                resp.status = falcon.HTTP_200
                resp.media = {'result': 'already exists', 'parentHash': block.parent_hash}
            else:

                amount = req.media.get('amount', 1)

                for nr in range(0, amount):
                    try:
                        block = harvester.add_block(block_hash)
                    except BlockAlreadyAdded as e:
                        print('Skipping {}'.format(block_hash))
                    block_hash = block.parent_hash
                    if block.id == 0:
                        break

                self.session.commit()

                resp.status = falcon.HTTP_201
                resp.media = {'result': 'added', 'parentHash': block.parent_hash}

        else:
            resp.status = falcon.HTTP_404
            resp.media = {'result': 'Block not found'}


class SequenceBlockResource(BaseResource):

    def on_post(self, req, resp):

        block_hash = None

        if 'block_id' in req.media:
            block = Block.query(self.session).filter(Block.id == req.media.get('block_id')).first()
        elif req.media.get('block_hash'):
            block_hash = req.media.get('block_hash')
            block = Block.query(self.session).filter(Block.hash == block_hash).first()
        else:
            block = None
            resp.status = falcon.HTTP_BAD_REQUEST
            resp.media = {'errors': ['Either block_hash or block_id should be supplied']}

        if block:
            print('Sequencing #{} ...'.format(block.id))

            harvester = PolkascanHarvesterService(self.session, type_registry=TYPE_REGISTRY)

            if block.id == 1:
                # Add genesis block
                parent_block = harvester.add_block(block.parent_hash)

            block_total = BlockTotal.query(self.session).filter_by(id=block.id).first()
            parent_block = Block.query(self.session).filter(Block.id == block.id - 1).first()
            parent_block_total = BlockTotal.query(self.session).filter_by(id=block.id - 1).first()

            if block_total:
                resp.status = falcon.HTTP_200
                resp.media = {'result': 'already exists', 'blockId': block.id}
            else:

                if parent_block_total:
                    parent_block_total = parent_block_total.asdict()

                if parent_block:
                    parent_block = parent_block.asdict()

                harvester.sequence_block(block, parent_block, parent_block_total)

                self.session.commit()

                resp.status = falcon.HTTP_201
                resp.media = {'result': 'added', 'parentHash': block.parent_hash}

        else:
            resp.status = falcon.HTTP_404
            resp.media = {'result': 'Block not found'}

