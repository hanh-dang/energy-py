import logging

from energypy.common.memories.memory import calculate_returns

from energypy.common.memories.array_memory import ArrayMemory
from energypy.common.memories.deque_memory import DequeMemory

from energypy.common.utils import load_pickle


logger = logging.getLogger(__name__)

memory_register = {
    'array': ArrayMemory,
    'deque': DequeMemory,
}


def make_memory(**kwargs):
    """ makes a memory for an agent to store experience """

    load_path = kwargs.pop('load_path', None)

    if load_path:
        logger.info('Loading memory from pickle at {}'.format(
            load_path))

        return load_pickle(load_path)

    else:
        memory_id = kwargs.pop('memory_id')

        logger.info('Making new {} memory'.format(memory_id))
        [logger.debug('{}: {}'.format(k, v)) for k, v in kwargs.items()]
        memory = memory_register[memory_id]

        return memory(**kwargs)
