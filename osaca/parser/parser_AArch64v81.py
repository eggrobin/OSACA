#!/usr/bin/env python3


import pyparsing as pp

from .base_parser import BaseParser


class ParserAArch64v81(BaseParser):
    def __init__(self):
        super().__init__()

    def construct_parser(self):
        # Comment
        symbol_comment = '//'
        self.comment = pp.Literal(symbol_comment) + pp.Group(
            pp.ZeroOrMore(pp.Word(pp.printables))
        ).setResultsName(self.COMMENT_ID)
        # Define ARM assembly identifier
        relocation = pp.Combine(pp.Literal(':') + pp.Word(pp.alphanums + '_') + pp.Literal(':'))
        first = pp.Word(pp.alphas + '_.', exact=1)
        rest = pp.Word(pp.alphanums + '_.')
        identifier = pp.Group(
            pp.Optional(relocation).setResultsName('relocation')
            + pp.Combine(first + pp.Optional(rest)).setResultsName('name')
        ).setResultsName('identifier')
        # Label
        self.label = pp.Group(
            identifier.setResultsName('name') + pp.Literal(':') + pp.Optional(self.comment)
        ).setResultsName(self.LABEL_ID)
        # Directive
        decimal_number = pp.Combine(
            pp.Optional(pp.Literal('-')) + pp.Word(pp.nums)
        ).setResultsName('value')
        hex_number = pp.Combine(pp.Literal('0x') + pp.Word(pp.hexnums)).setResultsName('value')
        directive_option = pp.Combine(
            pp.Word(pp.alphas + '#@.%', exact=1)
            + pp.Optional(pp.Word(pp.printables, excludeChars=','))
        )
        directive_parameter = (
            pp.quotedString | directive_option | identifier | hex_number | decimal_number
        )
        commaSeparatedList = pp.delimitedList(pp.Optional(directive_parameter), delim=',')
        self.directive = pp.Group(
            pp.Literal('.')
            + pp.Word(pp.alphanums + '_').setResultsName('name')
            + commaSeparatedList.setResultsName('parameters')
            + pp.Optional(self.comment)
        ).setResultsName(self.DIRECTIVE_ID)

        ##############################
        # Instructions
        # Mnemonic
        # (?P<instr>[a-zA-Z][a-zA-Z0-9]*)(?P<setflg>S?)(P?<CC>.[a-zA-Z]{2})
        mnemonic = pp.Word(pp.alphanums + '.').setResultsName('mnemonic')
        # Immediate:
        # int: ^-?[0-9]+ | hex: ^0x[0-9a-fA-F]+ | fp: ^[0-9]{1}.[0-9]+[eE]{1}[\+-]{1}[0-9]+[fF]?
        symbol_immediate = '#'
        mantissa = pp.Combine(
            pp.Optional(pp.Literal('-')) + pp.Word(pp.nums) + pp.Literal('.') + pp.Word(pp.nums)
        ).setResultsName('mantissa')
        exponent = (
            pp.CaselessLiteral('e')
            + pp.Word('+-').setResultsName('e_sign')
            + pp.Word(pp.nums).setResultsName('exponent')
        )
        float_ = pp.Group(
            mantissa + pp.Optional(exponent) + pp.CaselessLiteral('f')
        ).setResultsName('float')
        double_ = pp.Group(mantissa + pp.Optional(exponent)).setResultsName('double')
        immediate = pp.Group(
            pp.Optional(pp.Literal(symbol_immediate))
            + (hex_number ^ decimal_number ^ float_ ^ double_)
            | (pp.Optional(pp.Literal(symbol_immediate)) + identifier)
        ).setResultsName(self.IMMEDIATE_ID)
        shift_op = (
            pp.CaselessLiteral('lsl')
            ^ pp.CaselessLiteral('lsr')
            ^ pp.CaselessLiteral('asr')
            ^ pp.CaselessLiteral('ror')
            ^ pp.CaselessLiteral('sxtw')
            ^ pp.CaselessLiteral('uxtw')
        )
        arith_immediate = pp.Group(
            immediate.setResultsName('base_immediate')
            + pp.Suppress(pp.Literal(','))
            + shift_op.setResultsName('shift_op')
            + immediate.setResultsName('shift')
        ).setResultsName(self.IMMEDIATE_ID)
        # Register:
        # scalar: [XWBHSDQ][0-9]{1,2}  |   vector: V[0-9]{1,2}\.[12468]{1,2}[BHSD]()?
        # define SP and ZR register aliases as regex, due to pyparsing does not support
        # proper lookahead
        alias_r31_sp = pp.Regex('(?P<prefix>[a-zA-Z])?(?P<name>(sp|SP))')
        alias_r31_zr = pp.Regex('(?P<prefix>[a-zA-Z])?(?P<name>(zr|ZR))')
        scalar = pp.Word(pp.alphas, exact=1).setResultsName('prefix') + pp.Word(
            pp.nums
        ).setResultsName('name')
        index = pp.Literal('[') + pp.Word(pp.nums).setResultsName('index') + pp.Literal(']')
        vector = (
            pp.CaselessLiteral('v').setResultsName('prefix')
            + pp.Word(pp.nums).setResultsName('name')
            + pp.Literal('.')
            + pp.Optional(pp.Word('12468')).setResultsName('lanes')
            + pp.Word(pp.alphas, exact=1).setResultsName('shape')
            + pp.Optional(index)
        )
        self.list_element = vector ^ scalar
        register_list = (
            pp.Literal('{')
            + (
                pp.delimitedList(pp.Combine(self.list_element), delim=',').setResultsName('list')
                ^ pp.delimitedList(pp.Combine(self.list_element), delim='-').setResultsName(
                    'range'
                )
            )
            + pp.Literal('}')
            + pp.Optional(index)
        )
        register = pp.Group(
            (alias_r31_sp | alias_r31_zr | vector | scalar | register_list)
            + pp.Optional(
                pp.Suppress(pp.Literal(','))
                + shift_op.setResultsName('shift_op')
                + immediate.setResultsName('shift')
            )
        ).setResultsName(self.REGISTER_ID)
        # Memory
        register_index = register.setResultsName('index') + pp.Optional(
            pp.Literal(',') + pp.Word(pp.alphas) + immediate.setResultsName('scale')
        )
        memory = pp.Group(
            pp.Literal('[')
            + pp.Optional(register.setResultsName('base'))
            + pp.Optional(pp.Suppress(pp.Literal(',')))
            + pp.Optional(register_index ^ immediate.setResultsName('offset'))
            + pp.Literal(']')
            + pp.Optional(
                pp.Literal('!').setResultsName('pre-indexed')
                | (pp.Suppress(pp.Literal(',')) + immediate.setResultsName('post-indexed'))
            )
        ).setResultsName(self.MEMORY_ID)
        prefetch_op = pp.Group(
            pp.Group(pp.CaselessLiteral('PLD') ^ pp.CaselessLiteral('PST')).setResultsName('type')
            + pp.Group(
                pp.CaselessLiteral('L1') ^ pp.CaselessLiteral('L2') ^ pp.CaselessLiteral('L3')
            ).setResultsName('target')
            + pp.Group(pp.CaselessLiteral('KEEP') ^ pp.CaselessLiteral('STRM')).setResultsName(
                'policy'
            )
        ).setResultsName('prfop')
        # Combine to instruction form
        operand_first = pp.Group(
            register ^ immediate ^ memory ^ arith_immediate ^ (prefetch_op | identifier)
        )
        operand_rest = pp.Group((register ^ immediate ^ memory ^ arith_immediate) | identifier)
        self.instruction_parser = (
            mnemonic
            + pp.Optional(operand_first.setResultsName('operand1'))
            + pp.Optional(pp.Suppress(pp.Literal(',')))
            + pp.Optional(operand_rest.setResultsName('operand2'))
            + pp.Optional(pp.Suppress(pp.Literal(',')))
            + pp.Optional(operand_rest.setResultsName('operand3'))
            + pp.Optional(pp.Suppress(pp.Literal(',')))
            + pp.Optional(operand_rest.setResultsName('operand4'))
            + pp.Optional(self.comment)
        )
        self.opf = operand_first
        self.opr = operand_rest
        self.mem = memory
        self.reg = register
        self.idf = identifier
        self.prfop = prefetch_op
        self.imd = immediate
        self.aimd = arith_immediate

    def parse_line(self, line, line_number=None):
        """
        Parse line and return instruction form.

        :param str line: line of assembly code
        :param int line_id: default None, identifier of instruction form
        :return: parsed instruction form
        """
        instruction_form = {
            'instruction': None,
            'operands': None,
            'directive': None,
            'comment': None,
            'label': None,
            'line_number': line_number,
        }
        result = None

        # 1. Parse comment
        try:
            result = self._process_operand(self.comment.parseString(line, parseAll=True).asDict())
            instruction_form['comment'] = ' '.join(result[self.COMMENT_ID])
        except pp.ParseException:
            pass

        # 2. Parse label
        if result is None:
            try:
                result = self._process_operand(
                    self.label.parseString(line, parseAll=True).asDict()
                )
                instruction_form['label'] = result[self.LABEL_ID]['name']
                if self.COMMENT_ID in result[self.LABEL_ID]:
                    instruction_form['comment'] = ' '.join(result[self.LABEL_ID][self.COMMENT_ID])
            except pp.ParseException:
                pass

        # 3. Parse directive
        if result is None:
            try:
                result = self._process_operand(
                    self.directive.parseString(line, parseAll=True).asDict()
                )
                instruction_form['directive'] = {
                    'name': result[self.DIRECTIVE_ID]['name'],
                    'parameters': result[self.DIRECTIVE_ID]['parameters'],
                }
                if self.COMMENT_ID in result[self.DIRECTIVE_ID]:
                    instruction_form['comment'] = ' '.join(
                        result[self.DIRECTIVE_ID][self.COMMENT_ID]
                    )
            except pp.ParseException:
                pass

        # 4. Parse instruction
        if result is None:
            try:
                result = self.parse_instruction(line)
            except (pp.ParseException, KeyError):
                print(
                    '\n\n*-*-*-*-*-*-*-*-*-*-\n{}: {}\n*-*-*-*-*-*-*-*-*-*-\n\n'.format(
                        line_number, line
                    )
                )
            instruction_form['instruction'] = result['instruction']
            instruction_form['operands'] = result['operands']
            instruction_form['comment'] = result['comment']

        return instruction_form

    def parse_instruction(self, instruction):
        result = self.instruction_parser.parseString(instruction, parseAll=True).asDict()
        operands = {'source': [], 'destination': []}
        # ARM specific store flags
        is_store = False
        store_ex = False
        if result['mnemonic'].lower().startswith('st'):
            # Store instruction --> swap source and destination
            is_store = True
            if result['mnemonic'].lower().startswith('strex'):
                # Store exclusive --> first reg ist used for return state
                store_ex = True

        # Check from left to right
        # Check first operand
        if 'operand1' in result:
            if is_store and not store_ex:
                operands['source'].append(self._process_operand(result['operand1']))
            else:
                operands['destination'].append(self._process_operand(result['operand1']))
        # Check second operand
        if 'operand2' in result:
            if is_store and 'operand3' not in result:
                # destination
                operands['destination'].append(self._process_operand(result['operand2']))
            else:
                operands['source'].append(self._process_operand(result['operand2']))
        # Check third operand
        if 'operand3' in result:
            if is_store and 'operand4' not in result:
                operands['destination'].append(self._process_operand(result['operand3']))
            else:
                operands['source'].append(self._process_operand(result['operand3']))
        # Check fourth operand
        if 'operand4' in result:
            if is_store:
                operands['destination'].append(self._process_operand(result['operand4']))
            else:
                operands['source'].append(self._process_operand(result['operand4']))

        return_dict = {
            'instruction': result['mnemonic'],
            'operands': operands,
            'comment': ' '.join(result['comment']) if 'comment' in result else None,
        }
        return return_dict

    def _process_operand(self, operand):
        # structure memory addresses
        if 'memory' in operand:
            return self.substitute_memory_address(operand['memory'])
        # structure register lists
        if 'register' in operand and (
            'list' in operand['register'] or 'range' in operand['register']
        ):
            # TODO: discuss if ranges should be converted to lists
            return self.substitute_register_list(operand['register'])
        # add value attribute to floating point immediates without exponent
        if 'immediate' in operand:
            return self.substitute_immediate(operand['immediate'])
        if 'label' in operand:
            return self.substitute_label(operand['label'])
        return operand

    def substitute_memory_address(self, memory_address):
        # Remove unnecessarily created dictionary entries during parsing
        offset = None if 'offset' not in memory_address else memory_address['offset']
        base = None if 'base' not in memory_address else memory_address['base']
        index = None if 'index' not in memory_address else memory_address['index']
        scale = '1'
        valid_shift_ops = ['lsl', 'uxtw', 'sxtw']
        if 'index' in memory_address:
            if 'shift' in memory_address['index']:
                if memory_address['index']['shift_op'].lower() in valid_shift_ops:
                    scale = str(2 ** int(memory_address['index']['shift']['value']))
        new_dict = {'offset': offset, 'base': base, 'index': index, 'scale': scale}
        return {'memory': new_dict}

    def substitute_register_list(self, register_list):
        # Remove unnecessarily created dictionary entries during parsing
        vlist = []
        dict_name = ''
        if 'list' in register_list:
            dict_name = 'list'
        if 'range' in register_list:
            dict_name = 'range'
        for v in register_list[dict_name]:
            vlist.append(self.list_element.parseString(v, parseAll=True).asDict())
        index = None if 'index' not in register_list else register_list['index']
        new_dict = {dict_name: vlist, 'index': index}
        return {'register': new_dict}

    def substitute_immediate(self, immediate):
        dict_name = ''
        if 'identifier' in immediate:
            # actually an identifier, change declaration
            return immediate
        if 'value' in immediate:
            # normal integer value, nothing to do
            return {'immediate': immediate}
        if 'base_immediate' in immediate:
            # arithmetic immediate, nothing to do
            return {'immediate': immediate}
        if 'float' in immediate:
            dict_name = 'float'
        if 'double' in immediate:
            dict_name = 'double'
        if 'exponent' in immediate[dict_name]:
            # nothing to do
            return {'immediate': immediate}
        else:
            # change 'mantissa' key to 'value'
            return {'immediate': {'value': immediate[dict_name]['mantissa']}}

    def substitute_label(self, label):
        # remove duplicated 'name' level due to identifier
        label['name'] = label['name']['name']
        return {'label': label}
