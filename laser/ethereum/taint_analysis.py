import logging, copy
import laser.ethereum.helper as helper

class TaintRecord:
    """
    TaintRecord contains tainting information for a specific (state, node)
    the information specifies the taint status before executing the operation belonging to the state
    """

    def __init__(self):
        """ Builds a taint record """
        self.stack = []
        self.memory = {}
        self.storage = {}
        self.states = []

    def stack_tainted(self, index):
        """ Returns if stack element with index is tainted """
        if index < len(self.stack):
            return self.stack[index]
        return None

    def memory_tainted(self, index):
        if index in self.memory.keys():
            return self.memory[index]
        return False

    def storage_tainted(self, index):
        if index in self.storage.keys():
            return self.storage[index]
        return False

    def add_state(self, state):
        self.states.append(state)

    def clone(self):
        clone = TaintRecord()
        clone.stack = copy.deepcopy(self.stack)
        return clone

class TaintResult:
    """ Taint analysis result obtained after having ran the taint runner"""

    def __init__(self):
        self.records = []

    def check(self, state, stack_index):
        """
        Checks if stack variable is tainted, before executing the instruction
        :param state: state to check variable in
        :param stack_index: index of stack variable
        :return: tainted
        """
        record = self._try_get_record(state)
        if record is None:
            return None
        return record.stack_tainted(stack_index)

    def add_records(self, records):
        self.records += records

    def _try_get_record(self, state):
        for record in self.records:
            if state in record.states:
                return record
        return None


class TaintRunner:
    """
    Taint runner, is able to run taint analysis on symbolic execution result
    """

    @staticmethod
    def execute(statespace, node, state, initial_stack=[]):
        """
        Runs taint analysis on the statespace
        :param statespace: symbolic statespace to run taint analysis on
        :param node: taint introduction node
        :param state: taint introduction state
        :param stack_indexes: stack indexes to introduce taint
        :return: TaintResult object containing analysis results
        """
        result = TaintResult()

        # Build initial current_node
        init_record = TaintRecord()
        init_record.stack = initial_stack

        state_index = node.states.index(state)

        # List of (Node, TaintRecord, index)
        current_nodes = [(node, init_record, state_index)]

        for node, record, index in current_nodes:
            records = TaintRunner.execute_node(node, record, index)
            result.add_records(records)

            children = [statespace.nodes[edge.node_to] for edge in statespace.edges if edge.node_from == node.uid]
            for child in children:
                current_nodes.append((child, records[-1], 0))
        return result

    @staticmethod
    def execute_node(node, last_record, state_index=0):
        """
        Runs taint analysis on a given node
        :param node: node to analyse
        :param last_record: last taint record to work from
        :param state_index: state index to start from
        :return: List of taint records linked to the states in this node
        """
        records = [last_record]
        for index in range(state_index, len(node.states)):
            current_state = node.states[index]
            records.append(TaintRunner.execute_state(records[-1], current_state))
        return records[1:]

    @staticmethod
    def execute_state(record, state):
        """ Runs taint analysis on a state """
        record.add_state(state)
        new_record = record.clone()

        # Apply Change
        op = state.get_current_instruction()['opcode']
        if op in TaintRunner.stack_taint_table.keys():
            mutator = TaintRunner.stack_taint_table[op]
            TaintRunner.mutate_stack(new_record, mutator)

        return new_record

    @staticmethod
    def mutate_stack(record, mutator):
        pop, push = mutator

        values = []
        for i in range(pop):
            values.append(record.stack.pop())

        taint = any(values)

        for i in range(push):
            record.stack.append(taint)

    #TODO: CALLDATACOPY, CODECOPY,'CALL', 'CALLCODE', 'DELEGATECALL', 'STATICCALL', mstore8


    stack_taint_table = {
        # instruction: (taint source, taint target)
        'PUSH': (0, 1),
        'POP': (1, 0),
        'ADD': (2, 1),
        'MUL': (2, 1),
        'SUB': (2, 1),
        'AND': (2, 1),
        'OR':  (2, 1),
        'NOT': (2, 1),
        'BYTE': (2, 1),
        'DIV': (2, 1),
        'MOD': (2, 1),
        'SDIV': (2, 1),
        'SMOD': (2, 1),
        'ADDMOD': (2, 1),
        'MULMOD': (2, 1),
        'EXP': (2, 1),
        'SIGNEXTEND': (2, 1),
        'LT': (2, 1),
        'GT': (2, 1),
        'SLT': (2, 1),
        'SGT': (2, 1),
        'EQ': (2, 1),
        'ISZERO': (1, 1),
        'CALLVALUE': (0, 1),
        'CALLDATALOAD': (1, 1),
        'CALLDATASIZE': (0, 1),
        'ADDRESS': (0, 1),
        'BALANCE': (1, 1),
        'ORIGIN': (0, 1),
        'CALLER': (0, 1),
        'CODESIZE': (0, 1),
        'SHA3': (2, 1),
        'GASPRICE': (0, 1),
        'EXTCODESIZE': (1, 1),
        'BLOCKHASH': (1, 1),
        'COINBASE': (0, 1),
        'TIMESTAMP': (0, 1),
        'NUMBER': (0, 1),
        'DIFFICULTY': (0, 1),
        'GASLIMIT': (0, 1),
        'JUMP': (1, 0),
        'JUMPI': (2, 0),
        'PC': (0, 1),
        'MSIZE': (0, 1),
        'GAS': (0, 1),
        'CREATE': (3, 1)
    }

    def mutate_dup(self, op, record):
        depth = int(op[3:])
        index = len(record.stack) - depth
        record.append(record.stack[index])

    def mutate_swap(self, op, record):
        depth = int(op[3:])
        l = len(record.stack) - 1
        i = l - depth
        record.stack[l], record.stack[i] = record.stack[i], record.stack[l]

    def mutate_mload(self, record, op0):
        _ = record.stack.pop()
        try:
            index = helper.get_concrete_int(op0)
        except AttributeError:
            logging.debug("Can't MLOAD taint track symbolically")
            record.stack.append(False)
            return

        record.stack.append(record.memory_tainted(index))

    def mutate_mstore(self, record, op0):
        _, value_taint = record.stack.pop(), self.stack.pop()
        try:
            index = helper.get_concrete_int(op0)
        except AttributeError:
            logging.debug("Can't mstore taint track symbolically")
            return

        record.memory[index] = value_taint

    def mutate_sload(self, record, op0):
        _ = record.stack.pop()
        try:
            index = helper.get_concrete_int(op0)
        except AttributeError:
            logging.debug("Can't MLOAD taint track symbolically")
            record.stack.append(False)
            return

        record.stack.append(record.storage_tainted(index))

    def mutate_sstore(self, record, op0):
        _, value_taint = record.stack.pop(), self.stack.pop()
        try:
            index = helper.get_concrete_int(op0)
        except AttributeError:
            logging.debug("Can't mstore taint track symbolically")
            return

        record.storage[index] = value_taint

    def mutate_log(self, record, op):
        depth = int(op[3:])
        for _ in range(depth + 2):
            record.stack.pop()
