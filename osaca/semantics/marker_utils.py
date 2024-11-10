#!/usr/bin/env python3
from collections import OrderedDict
from enum import Enum
from functools import partial

from osaca.parser import ParserAArch64, ParserX86ATT, get_parser
from osaca.parser.instruction_form import InstructionForm
from osaca.parser.directive import DirectiveOperand
from osaca.parser.identifier import IdentifierOperand
from osaca.parser.immediate import ImmediateOperand
from osaca.parser.register import RegisterOperand

COMMENT_MARKER = {"start": "OSACA-BEGIN", "end": "OSACA-END"}

class Matching(Enum):
    No = 0
    Partial = 1
    Full = 2


def reduce_to_section(kernel, parser):
    """
    Finds OSACA markers in given kernel and returns marked section

    :param list kernel: kernel to check
    :param BaseParser parser: parser used to produce the kernel
    :returns: `list` -- marked section of kernel as list of instruction forms
    """
    start, end = find_marked_section(kernel, parser, COMMENT_MARKER)
    if start == -1:
        start = 0
    if end == -1:
        end = len(kernel)
    return kernel[start:end]


def get_marker(isa, syntax, comment=""):
    """Return tuple of start and end marker lines."""
    isa = isa.lower()
    if isa == "x86":
        if syntax == "ATT":
            start_marker_raw = (
                "movl      $111, %ebx # OSACA START MARKER\n"
                ".byte     100        # OSACA START MARKER\n"
                ".byte     103        # OSACA START MARKER\n"
                ".byte     144        # OSACA START MARKER\n"
            )
            if comment:
                start_marker_raw += "# {}\n".format(comment)
            end_marker_raw = (
                "movl      $222, %ebx # OSACA END MARKER\n"
                ".byte     100        # OSACA END MARKER\n"
                ".byte     103        # OSACA END MARKER\n"
                ".byte     144        # OSACA END MARKER\n"
            )
        elif syntax == "INTEL":
            raise NotImplementedError
    elif isa == "aarch64":
        start_marker_raw = (
            "mov       x1, #111    // OSACA START MARKER\n"
            ".byte     213,3,32,31 // OSACA START MARKER\n"
        )
        if comment:
            start_marker_raw += "// {}\n".format(comment)
        # After loop
        end_marker_raw = (
            "mov       x1, #222    // OSACA END MARKER\n"
            ".byte     213,3,32,31 // OSACA END MARKER\n"
        )

    parser = get_parser(isa, syntax)
    start_marker = parser.parse_file(start_marker_raw)
    end_marker = parser.parse_file(end_marker_raw)

    return start_marker, end_marker


def find_marked_section(lines, parser, comments=None):
    """
    Return indexes of marked section

    :param list lines: kernel
    :param parser: parser to use for checking
    :type parser: :class:`~parser.BaseParser`
    :param comments: dictionary with start and end markers in comment format, defaults to None
    :type comments: dict, optional
    :returns: `tuple of int` -- start and end line of marked section
    """
    # TODO match to instructions returned by get_marker
    index_start = -1
    index_end = -1
    for i, line in enumerate(lines):
        try:
            if line.mnemonic is None and comments is not None and line.comment is not None:
                if comments["start"] == line.comment:
                    index_start = i + 1
                elif comments["end"] == line.comment:
                    index_end = i
            elif index_start == -1:
                start_marker = parser.start_marker()
                matches, length = match_lines(parser, lines, i, start_marker)
                if matches:
                    # return first line after the marker
                    index_start = i + length
            else:
                end_marker = parser.end_marker()
                matches, length = match_lines(parser, lines, i, end_marker)
                if matches:
                    index_end = i
        except TypeError as e:
            print(i, e, line)
        if index_start != -1 and index_end != -1:
            break
    return index_start, index_end


# This function and the following ones traverse the syntactic tree produced by the parser and try to
# match it to the marker.  This is necessary because the IACA marker are significantly different on
# MSVC x86 than on other ISA/compilers.  Therefore, simple string matching is not sufficient.  Also,
# the syntax of numeric literals depends on the parser and should not be known to this class.
# The matching only checks for a limited number of properties (and the marker doesn't specify the
# rest).
def match_lines(parser, lines, index, marker):
    """
    Returns True iff the lines starting at `index` match the `marker`.

    :param list of `IntructionForm` lines: parsed assembly code.
    :param index: first line to try to match in `lines`.
    :param list of `InstructioForm` marker: pattern to match against the `lines`.
    :return: tuple bool, int: whether a match was found and the length of the match in the parsed
                              code.
    """
    length = 0
    marker_index = 0
    while marker_index < len(marker):
        line = lines[index + length]
        marker_line = marker[marker_index]
        if isinstance(marker_line, list):
            # No support for partial matching in lists.
            for i in range(len(marker_line)):
                matching = match_line(parser, line, marker_line[i])
                if matching == Matching.Full:
                    break
            else:
                return False, None
            marker_index += 1
        else:
            matching = match_line(parser, line, marker_line)
            if matching == Matching.No:
                return False, None
            elif matching == Matching.Partial:
                # Try the same marker line again.  The call to `match_line` consumed some of the
                # directive parameters.
                pass
            elif matching == Matching.Full:
                # Move to the next marker line, the current one has been fully matched.
                marker_index += 1
        length += 1
    return True, length

def match_line(parser, line, marker_line):
    """
    Returns whether `line` matches `marker_line`.

    :param `IntructionForm` line: parsed assembly code.
    :param marker_line `InstructioForm` marker: pattern to match against `line`.
    :return: Matching. In case of partial match, `marker_line` is modified and should be reused for
                       matching the next line in the parsed assembly code.
    """
    if (
        line.mnemonic
        and marker_line.mnemonic
        and line.mnemonic == marker_line.mnemonic
        and match_operands(line.operands, marker_line.operands)
    ):
        return Matching.Full
    if (
        line.directive
        and marker_line.directive
        and line.directive.name == marker_line.directive.name
    ):
        return match_parameters(parser, line.directive.parameters, marker_line.directive.parameters)
    else:
        return Matching.No

def match_operands(line_operands, marker_line_operands):
    if len(line_operands) != len(marker_line_operands):
        return False
    for i in range(len(line_operands)):
        if not match_operand(line_operands[i], marker_line_operands[i]):
            return False
    return True

def match_operand(line_operand, marker_line_operand):
    if (
        isinstance(line_operand, ImmediateOperand)
        and isinstance(marker_line_operand, ImmediateOperand)
        and line_operand.value == marker_line_operand.value
    ):
        return True
    if (
        isinstance(line_operand, RegisterOperand)
        and isinstance(marker_line_operand, RegisterOperand)
        and line_operand.name.lower() == marker_line_operand.name.lower()
    ):
        return True
    return False

def match_parameters(parser, line_parameters, marker_line_parameters):
    """
    Returns whether `line_parameters` matches `marker_line_parameters`.

    :param list of strings line_parameters: parameters of a directive in the parsed assembly code.
    :param list of strings marker_line_parameters: parameters of a directive in the marker.
    :return: Matching. In case of partial match, `marker_line_parameters` is modified and should be
                       reused for matching the next line in the parsed assembly code.
    """
    line_parameter_count = len(line_parameters)
    marker_line_parameter_count = len(marker_line_parameters)

    # The elements of `marker_line_parameters` are consumed as they are matched.
    for i in range(min(line_parameter_count, marker_line_parameter_count)):
        line_parameter = line_parameters[i]
        marker_line_parameter = marker_line_parameters[0]
        if not match_parameter(line_parameter, marker_line_parameter):
            # If the parameters don't match verbatim, check if they represent the same immediate
            # value.
            line_immediate = ImmediateOperand(value=line_parameter)
            marker_line_immediate = ImmediateOperand(value=marker_line_parameter)
            if parser.normalize_imd(line_immediate) != parser.normalize_imd(marker_line_immediate):
                return Matching.No
        marker_line_parameters.pop(0)
    if len(marker_line_parameters) == 0:
        return Matching.Full
    else:
        return Matching.Partial

def match_parameter(line_parameter, marker_line_parameter):
    return line_parameter.lower() == marker_line_parameter.lower()


def match_bytes(lines, index, byte_list):
    """Match bytes directives of markers"""
    # either all bytes are in one line or in separate ones
    extracted_bytes = []
    line_count = 0
    while (
        index < len(lines)
        and lines[index].directive is not None
        and lines[index].directive.name == "byte"
    ):
        line_count += 1
        extracted_bytes += [int(x, 0) for x in lines[index].directive.parameters]
        index += 1
    if extracted_bytes[0 : len(byte_list)] == byte_list:
        return True, line_count
    return False, -1


def find_jump_labels(lines):
    """
    Find and return all labels which are followed by instructions until the next label

    :return: OrderedDict of mapping from label name to associated line index
    """
    # 1. Identify labels and instructions until next label
    labels = OrderedDict()
    current_label = None
    for i, line in enumerate(lines):
        if line.label is not None:
            # When a new label is found, add to blocks dict
            labels[line.label] = (i,)
            # End previous block at previous line
            if current_label is not None:
                labels[current_label] = (labels[current_label][0], i)
            # Update current block name
            current_label = line.label
        elif current_label is None:
            # If no block has been started, skip end detection
            continue
    # Set to last line if no end was for last label found
    if current_label is not None and len(labels[current_label]) == 1:
        labels[current_label] = (labels[current_label][0], len(lines))

    # 2. Identify and remove labels which contain only dot-instructions (e.g., .text)
    for label in list(labels):
        if all(
            [
                line.mnemonic.startswith(".")
                for line in lines[labels[label][0] : labels[label][1]]
                if line.mnemonic is not None
            ]
        ):
            del labels[label]

    return OrderedDict([(label, v[0]) for label, v in labels.items()])


def find_basic_blocks(lines):
    """
    Find and return basic blocks (asm sections which can only be executed as complete block).

    Blocks always start at a label and end at the next jump/break possibility.

    :return: OrderedDict with labels as keys and list of lines as value
    """
    valid_jump_labels = find_jump_labels(lines)

    # Identify blocks, as they are started with a valid jump label and terminated by a label or
    # an instruction referencing a valid jump label
    blocks = OrderedDict()
    for label, label_line_idx in valid_jump_labels.items():
        blocks[label] = [lines[label_line_idx]]
        for line in lines[label_line_idx + 1 :]:
            terminate = False
            blocks[label].append(line)
            # Find end of block by searching for references to valid jump labels
            if line.mnemonic is not None and line.operands != []:
                for operand in [o for o in line.operands if isinstance(o, IdentifierOperand)]:
                    if operand.name in valid_jump_labels:
                        terminate = True
            elif line.label is not None:
                terminate = True
            if terminate:
                break

    return blocks


def find_basic_loop_bodies(lines):
    """
    Find and return basic loop bodies (asm section which loop back on itself with no other egress).

    :return: OrderedDict with labels as keys and list of lines as value
    """
    valid_jump_labels = find_jump_labels(lines)

    # Identify blocks, as they are started with a valid jump label and terminated by
    # an instruction referencing a valid jump label
    loop_bodies = OrderedDict()
    for label, label_line_idx in valid_jump_labels.items():
        current_block = [lines[label_line_idx]]
        for line in lines[label_line_idx + 1 :]:
            terminate = False
            current_block.append(line)
            # Find end of block by searching for references to valid jump labels
            if line.mnemonic is not None and line.operands != []:
                # Ignore `b.none` instructions (relevant von ARM SVE code)
                # This branch instruction is often present _within_ inner loop blocks, but usually
                # do not terminate
                if line.mnemonic == "b.none":
                    continue
                for operand in [o for o in line.operands if isinstance(o, IdentifierOperand)]:
                    if operand.name in valid_jump_labels:
                        if operand.name == label:
                            loop_bodies[label] = current_block
                        terminate = True
                        break
            if terminate:
                break

    return loop_bodies
