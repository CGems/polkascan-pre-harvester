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
#  tasks.py

import os
from time import sleep

import celery
from scalecodec import ScaleBytes
from scalecodec.block import RawBabePreDigest

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.sql import func

from app.models.data import Extrinsic, Block, BlockTotal, Log
from app.processors.converters import PolkascanHarvesterService, HarvesterCouldNotAddBlock, BlockAlreadyAdded
from substrateinterface import SubstrateInterface

from app.settings import DB_CONNECTION, DEBUG, SUBSTRATE_RPC_URL, TYPE_REGISTRY

CELERY_BROKER = os.environ.get('CELERY_BROKER')
CELERY_BACKEND = os.environ.get('CELERY_BACKEND')

app = celery.Celery('tasks', broker=CELERY_BROKER, backend=CELERY_BACKEND)

app.conf.beat_schedule = {
    'check-head-10-seconds': {
        'task': 'app.tasks.start_harvester',
        'schedule': 10.0,
        'args': ()
    },
}

app.conf.timezone = 'UTC'


class BaseTask(celery.Task):

    def __init__(self):
        self.metadata_store = {}

    def __call__(self, *args, **kwargs):
        self.engine = create_engine(DB_CONNECTION, echo=DEBUG, isolation_level="READ_UNCOMMITTED")
        session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.session = scoped_session(session_factory)

        return super().__call__(*args, **kwargs)

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        if hasattr(self, 'session'):
            self.session.remove()
        if hasattr(self, 'engine'):
            self.engine.engine.dispose()


@app.task(base=BaseTask, bind=True)
def accumulate_block_recursive(self, block_hash, end_block_hash=None):

    harvester = PolkascanHarvesterService(self.session, type_registry=TYPE_REGISTRY)
    harvester.metadata_store = self.metadata_store

    # If metadata store isn't initialized yet, perform some tests
    if not harvester.metadata_store:
        print('Init: create entrypoints')
        # Check if blocks exists
        max_block_id = self.session.query(func.max(Block.id)).one()[0]

        if not max_block_id:
            # Speed up accumulating by creating several entry points
            substrate = SubstrateInterface(SUBSTRATE_RPC_URL)
            block_nr = substrate.get_block_number(block_hash)
            if block_nr > 100:
                for entry_point in range(0, block_nr, block_nr // 4)[1:-1]:
                    entry_point_hash = substrate.get_block_hash(entry_point)
                    accumulate_block_recursive.delay(entry_point_hash)

    block = None
    max_sequenced_block_id = False

    add_count = 0

    try:

        for nr in range(0, 10):
            if not block or block.id > 0:
                # Process block
                block = harvester.add_block(block_hash)

                print('+ Added {} '.format(block_hash))

                add_count += 1

                self.session.commit()

                # Break loop if targeted end block hash is reached
                if block_hash == end_block_hash or block.id == 0:
                    break

                # Continue with parent block hash
                block_hash = block.parent_hash

        # Update persistent metadata store in Celery task
        self.metadata_store = harvester.metadata_store

        if block_hash != end_block_hash and block and block.id > 0:
            accumulate_block_recursive.delay(block.parent_hash, end_block_hash)

    except BlockAlreadyAdded as e:
        print('. Skipped {} '.format(block_hash))
        start_sequencer.delay()
    except IntegrityError as e:
        print('. Skipped duplicate {} '.format(block_hash))
    except Exception as exc:
        print('! ERROR adding {}'.format(block_hash))
        raise HarvesterCouldNotAddBlock(block_hash) from exc

    return {
        'result': '{} blocks added'.format(add_count),
        'lastAddedBlockHash': block_hash,
        'sequencerStartedFrom': max_sequenced_block_id
    }


@app.task(base=BaseTask, bind=True)
def start_sequencer(self):
    # Start sequencer
    max_sequenced_block_id = self.session.query(func.max(BlockTotal.id)).one()[0]
    if max_sequenced_block_id is not None:
        sequencer_parent_block = BlockTotal.query(self.session).filter_by(id=max_sequenced_block_id).first()
        parent_block = Block.query(self.session).filter_by(id=max_sequenced_block_id).first()

        sequence_block_recursive.delay(
            parent_block_data=parent_block.asdict(),
            parent_sequenced_block_data=sequencer_parent_block.asdict()
        )

    else:
        sequence_block_recursive.delay(parent_block_data=None)


@app.task(base=BaseTask, bind=True)
def start_harvester(self, check_gaps=False):

    print("---------- {}".format(check_gaps))
    substrate = SubstrateInterface(SUBSTRATE_RPC_URL)

    block_sets = []

    if check_gaps:
        # Check for gaps between already harvested blocks and try to fill them first
        remaining_sets_result = Block.get_missing_block_ids(self.session)

        for block_set in remaining_sets_result:

            # Get start and end block hash
            end_block_hash = substrate.get_block_hash(int(block_set['block_from']))
            start_block_hash = substrate.get_block_hash(int(block_set['block_to']))

            # Start processing task
            accumulate_block_recursive.delay(start_block_hash, end_block_hash)

            block_sets.append({
                'start_block_hash': start_block_hash,
                'end_block_hash': end_block_hash
            })

        # Start sequencer
        start_sequencer.delay()

    # Continue from current finalised head

    start_block_hash = substrate.get_chain_head()
    end_block_hash = None

    accumulate_block_recursive.delay(start_block_hash, end_block_hash)

    block_sets.append({
        'start_block_hash': start_block_hash,
        'end_block_hash': end_block_hash
    })

    return {
        'result': 'Harvester job started',
        'block_sets': block_sets
    }


@app.task(base=BaseTask, bind=True)
def sequence_block_recursive(self, parent_block_data, parent_sequenced_block_data=None):

    harvester = PolkascanHarvesterService(self.session, type_registry=TYPE_REGISTRY)
    harvester.metadata_store = self.metadata_store
    for nr in range(0, 10):
        if not parent_sequenced_block_data:
            # No block ever sequenced, check if chain is at genesis state

            block = Block.query(self.session).order_by('id').first()

            if block.id == 1:
                # Add genesis block
                block = harvester.add_block(block.parent_hash)

            if block.id != 0:
                return {'error': 'Chain not at genesis'}

            harvester.process_genesis(block)
            block_id = 0
        else:
            block_id = parent_sequenced_block_data['id'] + 1

            block = Block.query(self.session).get(block_id)

        if block:
            try:
                sequenced_block = harvester.sequence_block(block, parent_block_data, parent_sequenced_block_data)
                self.session.commit()

                parent_block_data = block.asdict()
                parent_sequenced_block_data = sequenced_block.asdict()

                if nr == 9 or not sequenced_block:

                    if sequenced_block:
                        if nr == 9:
                            sequence_block_recursive.delay(parent_block_data, parent_sequenced_block_data)

                    return {'processedBlockId': block.id, 'amount': nr + 1}

            except IntegrityError as e:
                return {'error': 'Sequencer already started', 'exception': str(e)}
        else:
            return {'error': 'Block {} not found'.format(block_id)}


@app.task(base=BaseTask, bind=True)
def sync_block_account_id(self):

    db_session = self.session
    blocks = Block.query(db_session).filter(Block.account_index.is_(None)).all()

    for block in blocks:
        log = Log.query(db_session).filter(Log.block_id == block.id).filter(Log.type == 'PreRuntime').first()
        if log:
            data = log.data.get("value").get("data")
            if data:
                if data[0:2] != "01" and data[0:2] != "00":
                    continue

                res = RawBabePreDigest(ScaleBytes("0x{}".format(data)))
                if data[0:2] == "01" and len(data) == 34:
                    res.decode()
                    block.account_index = res.value.get("Secondary").get("authorityIndex")
                elif data[0:2] == "00":
                    res.decode(check_remaining=False)
                    block.account_index = res.value.get("Primary").get("authorityIndex")
                else:
                    raise "error log data ".format(data)

                block.save(db_session)
                print("...................", block.id, block.account_index)
        else:
            print("...................", "Blocks not found")

    db_session.commit()
