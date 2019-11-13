#!/usr/bin/env python3
"""
Unit tests for IACA/OSACA marker utilities
"""
import os
import unittest
from collections import OrderedDict

from osaca.semantics import reduce_to_section, find_basic_blocks, find_jump_labels, \
    find_basic_loop_bodies
from osaca.parser import ParserAArch64v81, ParserX86ATT


class TestMarkerUtils(unittest.TestCase):
    @classmethod
    def setUpClass(self):
        self.parser_AArch = ParserAArch64v81()
        self.parser_x86 = ParserX86ATT()
        with open(self._find_file('triad-arm-iaca.s')) as f:
            triad_code_arm = f.read()
        with open(self._find_file('triad-x86-iaca.s')) as f:
            triad_code_x86 = f.read()
        self.parsed_AArch = self.parser_AArch.parse_file(triad_code_arm)
        self.parsed_x86 = self.parser_x86.parse_file(triad_code_x86)

    #################
    # Test
    #################

    def test_marker_detection_AArch64(self):
        kernel = reduce_to_section(self.parsed_AArch, 'AArch64')
        self.assertEqual(len(kernel), 138)
        self.assertEqual(kernel[0].line_number, 307)
        self.assertEqual(kernel[-1].line_number, 444)

    def test_marker_detection_x86(self):
        kernel = reduce_to_section(self.parsed_x86, 'x86')
        self.assertEqual(len(kernel), 9)
        self.assertEqual(kernel[0].line_number, 146)
        self.assertEqual(kernel[-1].line_number, 154)

    def test_marker_matching_AArch64(self):
        # preparation
        bytes_1_line = '.byte     213,3,32,31\n'
        bytes_2_lines_1 = '.byte     213,3,32\n' + '.byte 31\n'
        bytes_2_lines_2 = '.byte     213,3\n' + '.byte 32,31\n'
        bytes_2_lines_3 = '.byte     213\n' + '.byte 3,32,31\n'
        bytes_3_lines_1 = '.byte     213,3\n' + '.byte     32\n' + '.byte     31\n'
        bytes_3_lines_2 = '.byte     213\n' + '.byte     3,32\n' + '.byte     31\n'
        bytes_3_lines_3 = '.byte     213\n' + '.byte     3\n' + '.byte     32,31\n'
        bytes_4_lines = '.byte     213\n' + '.byte     3\n' + '.byte     32\n' + '.byte     31\n'
        mov_start_1 = 'mov      x1, #111\n'
        mov_start_2 = 'mov      x1, 111  // should work as well\n'
        mov_end_1 = 'mov      x1, #222 // preferred way\n'
        mov_end_2 = 'mov      x1, 222\n'
        prologue = (
            'mov x12, xzr\n'
            + '\tldp x9, x10, [sp, #16]      // 8-byte Folded Reload\n'
            + '     .p2align    6\n'
        )
        kernel = (
            '.LBB0_28:\n'
            + 'fmul    v7.2d, v7.2d, v19.2d\n'
            + 'stp q0, q1, [x10, #-32]\n'
            + 'b.ne    .LBB0_28\n'
        )
        epilogue = '.LBB0_29:   //   Parent Loop BB0_20 Depth=1\n' + 'bl    dummy\n'
        kernel_length = len(list(filter(None, kernel.split('\n'))))

        bytes_variations = [
            bytes_1_line,
            bytes_2_lines_1,
            bytes_2_lines_2,
            bytes_2_lines_3,
            bytes_3_lines_1,
            bytes_3_lines_2,
            bytes_3_lines_3,
            bytes_4_lines,
        ]
        mov_start_variations = [mov_start_1, mov_start_2]
        mov_end_variations = [mov_end_1, mov_end_2]
        # actual tests
        for mov_start_var in mov_start_variations:
            for bytes_var_1 in bytes_variations:
                for mov_end_var in mov_end_variations:
                    for bytes_var_2 in bytes_variations:
                        sample_code = (
                            prologue
                            + mov_start_var
                            + bytes_var_1
                            + kernel
                            + mov_end_var
                            + bytes_var_2
                            + epilogue
                        )
                        with self.subTest(
                            mov_start=mov_start_var,
                            bytes_start=bytes_var_1,
                            mov_end=mov_end_var,
                            bytes_end=bytes_var_2,
                        ):
                            sample_parsed = self.parser_AArch.parse_file(sample_code)
                            sample_kernel = reduce_to_section(sample_parsed, 'AArch64')
                            self.assertEqual(len(sample_kernel), kernel_length)
                            kernel_start = len(
                                list(
                                    filter(
                                        None, (prologue + mov_start_var + bytes_var_1).split('\n')
                                    )
                                )
                            )
                            parsed_kernel = self.parser_AArch.parse_file(
                                kernel, start_line=kernel_start
                            )
                            self.assertEqual(sample_kernel, parsed_kernel)

    def test_marker_matching_x86(self):
        # preparation
        bytes_1_line = '.byte     100,103,144\n'
        bytes_2_lines_1 = '.byte     100,103\n' + '.byte 144\n'
        bytes_2_lines_2 = '.byte     100\n' + '.byte 103,144\n'
        bytes_3_lines = (
            '.byte     100 # IACA MARKER UTILITY\n'
            + '.byte     103 # IACA MARKER UTILITY\n'
            + '.byte     144 # IACA MARKER UTILITY\n'
        )
        mov_start_1 = 'movl      $111, %ebx # IACA START\n'
        mov_start_2 = 'mov      $111, %ebx # IACA START\n'
        mov_end_1 = 'movl      $222, %ebx # IACA END\n'
        mov_end_2 = 'mov      $222, %ebx # IACA END\n'
        prologue = 'movl    -92(%rbp), %r11d\n' + 'movl      $111, %ebx\n'
        kernel = (
            'vfmadd132sd (%r15,%rcx,8), %xmm5, %xmm0\n'
            + 'vmovsd  %xmm0, (%r14,%rcx,8)\n'
            + 'cmpl    %ebx, %ecx\n'
            + 'jge .L8\n'
        )
        epilogue = '.LE9:\t\t#12.2\n' 'call    dummy\n'
        kernel_length = len(list(filter(None, kernel.split('\n'))))

        bytes_variations = [bytes_1_line, bytes_2_lines_1, bytes_2_lines_2, bytes_3_lines]
        mov_start_variations = [mov_start_1, mov_start_2]
        mov_end_variations = [mov_end_1, mov_end_2]
        # actual tests
        for mov_start_var in mov_start_variations:
            for bytes_var_1 in bytes_variations:
                for mov_end_var in mov_end_variations:
                    for bytes_var_2 in bytes_variations:
                        sample_code = (
                            prologue
                            + mov_start_var
                            + bytes_var_1
                            + kernel
                            + mov_end_var
                            + bytes_var_2
                            + epilogue
                        )
                        with self.subTest(
                            mov_start=mov_start_var,
                            bytes_start=bytes_var_1,
                            mov_end=mov_end_var,
                            bytes_end=bytes_var_2,
                        ):
                            sample_parsed = self.parser_x86.parse_file(sample_code)
                            sample_kernel = reduce_to_section(sample_parsed, 'x86')
                            self.assertEqual(len(sample_kernel), kernel_length)
                            kernel_start = len(
                                list(
                                    filter(
                                        None, (prologue + mov_start_var + bytes_var_1).split('\n')
                                    )
                                )
                            )
                            parsed_kernel = self.parser_x86.parse_file(
                                kernel, start_line=kernel_start
                            )
                            self.assertEqual(sample_kernel, parsed_kernel)

    def test_marker_special_cases_AArch(self):
        bytes_line = '.byte     213,3,32,31\n'
        mov_start = 'mov      x1, #111\n'
        mov_end = 'mov      x1, #222\n'
        prologue = 'dup v0.2d, x14\n' + '    neg x9, x9\n' + '    .p2align    6\n'
        kernel = (
            '.LBB0_28:\n'
            + 'fmul    v7.2d, v7.2d, v19.2d\n'
            + 'stp q0, q1, [x10, #-32]\n'
            + 'b.ne    .LBB0_28\n'
        )
        epilogue = '.LBB0_29:   //   Parent Loop BB0_20 Depth=1\n' + 'bl    dummy\n'
        kernel_length = len(list(filter(None, kernel.split('\n'))))

        # marker directly at the beginning
        code_beginning = mov_start + bytes_line + kernel + mov_end + bytes_line + epilogue
        beginning_parsed = self.parser_AArch.parse_file(code_beginning)
        test_kernel = reduce_to_section(beginning_parsed, 'AArch64')
        self.assertEqual(len(test_kernel), kernel_length)
        kernel_start = len(list(filter(None, (mov_start + bytes_line).split('\n'))))
        parsed_kernel = self.parser_AArch.parse_file(kernel, start_line=kernel_start)
        self.assertEqual(test_kernel, parsed_kernel)

        # marker at the end
        code_end = prologue + mov_start + bytes_line + kernel + mov_end + bytes_line + epilogue
        end_parsed = self.parser_AArch.parse_file(code_end)
        test_kernel = reduce_to_section(end_parsed, 'AArch64')
        self.assertEqual(len(test_kernel), kernel_length)
        kernel_start = len(list(filter(None, (prologue + mov_start + bytes_line).split('\n'))))
        parsed_kernel = self.parser_AArch.parse_file(kernel, start_line=kernel_start)
        self.assertEqual(test_kernel, parsed_kernel)

        # no kernel
        code_empty = prologue + mov_start + bytes_line + mov_end + bytes_line + epilogue
        empty_parsed = self.parser_AArch.parse_file(code_empty)
        test_kernel = reduce_to_section(empty_parsed, 'AArch64')
        self.assertEqual(len(test_kernel), 0)
        kernel_start = len(list(filter(None, (prologue + mov_start + bytes_line).split('\n'))))
        self.assertEqual(test_kernel, [])

        # no start marker
        code_no_start = prologue + bytes_line + kernel + mov_end + bytes_line + epilogue
        no_start_parsed = self.parser_AArch.parse_file(code_no_start)
        with self.assertRaises(LookupError):
            reduce_to_section(no_start_parsed, 'AArch64')

        # no end marker
        code_no_end = prologue + mov_start + bytes_line + kernel + mov_end + epilogue
        no_end_parsed = self.parser_AArch.parse_file(code_no_end)
        with self.assertRaises(LookupError):
            reduce_to_section(no_end_parsed, 'AArch64')

        # no marker at all
        code_no_marker = prologue + kernel + epilogue
        no_marker_parsed = self.parser_AArch.parse_file(code_no_marker)
        with self.assertRaises(LookupError):
            reduce_to_section(no_marker_parsed, 'AArch64')

    def test_marker_special_cases_x86(self):
        bytes_line = '.byte     100\n.byte     103\n.byte     144\n'
        mov_start = 'movl     $111, %ebx\n'
        mov_end = 'movl     $222, %ebx\n'
        prologue = 'movl    -88(%rbp), %r10d\n' + 'xorl    %r11d, %r11d\n' + '.p2align 4,,10\n'
        kernel = (
            '.L3: #L3\n'
            + 'vmovsd  .LC1(%rip), %xmm0\n'
            + 'vmovsd  %xmm0, (%r15,%rcx,8)\n'
            + 'cmpl    %ecx, %ebx\n'
            + 'jle .L3\n'
        )
        epilogue = 'leaq    -56(%rbp), %rsi\n' + 'movl    %r10d, -88(%rbp)\n' + 'call    timing\n'
        kernel_length = len(list(filter(None, kernel.split('\n'))))

        # marker directly at the beginning
        code_beginning = mov_start + bytes_line + kernel + mov_end + bytes_line + epilogue
        beginning_parsed = self.parser_x86.parse_file(code_beginning)
        test_kernel = reduce_to_section(beginning_parsed, 'x86')
        self.assertEqual(len(test_kernel), kernel_length)
        kernel_start = len(list(filter(None, (mov_start + bytes_line).split('\n'))))
        parsed_kernel = self.parser_x86.parse_file(kernel, start_line=kernel_start)
        self.assertEqual(test_kernel, parsed_kernel)

        # marker at the end
        code_end = prologue + mov_start + bytes_line + kernel + mov_end + bytes_line + epilogue
        end_parsed = self.parser_x86.parse_file(code_end)
        test_kernel = reduce_to_section(end_parsed, 'x86')
        self.assertEqual(len(test_kernel), kernel_length)
        kernel_start = len(list(filter(None, (prologue + mov_start + bytes_line).split('\n'))))
        parsed_kernel = self.parser_x86.parse_file(kernel, start_line=kernel_start)
        self.assertEqual(test_kernel, parsed_kernel)

        # no kernel
        code_empty = prologue + mov_start + bytes_line + mov_end + bytes_line + epilogue
        empty_parsed = self.parser_x86.parse_file(code_empty)
        test_kernel = reduce_to_section(empty_parsed, 'x86')
        self.assertEqual(len(test_kernel), 0)
        kernel_start = len(list(filter(None, (prologue + mov_start + bytes_line).split('\n'))))
        self.assertEqual(test_kernel, [])

        # no start marker
        code_no_start = prologue + bytes_line + kernel + mov_end + bytes_line + epilogue
        no_start_parsed = self.parser_x86.parse_file(code_no_start)
        with self.assertRaises(LookupError):
            reduce_to_section(no_start_parsed, 'x86')

        # no end marker
        code_no_end = prologue + mov_start + bytes_line + kernel + mov_end + epilogue
        no_end_parsed = self.parser_x86.parse_file(code_no_end)
        with self.assertRaises(LookupError):
            reduce_to_section(no_end_parsed, 'x86')

        # no marker at all
        code_no_marker = prologue + kernel + epilogue
        no_marker_parsed = self.parser_x86.parse_file(code_no_marker)
        with self.assertRaises(LookupError):
            reduce_to_section(no_marker_parsed, 'x86')

    def test_find_jump_labels(self):
        self.assertEqual(find_jump_labels(self.parsed_x86),
                         OrderedDict([('.LFB24', 10), ('.L4', 65), ('.L3', 79), ('.L2', 102),
                                      ('.L13', 111), ('.L12', 120), ('.L6', 132), ('.L10', 145),
                                      ('.L9', 161), ('.L8', 183), ('.L15', 252), ('.L26', 256),
                                      ('.L14', 259), ('.LFB25', 277), ('.L28', 289)]))

        self.assertEqual(
            find_jump_labels(self.parsed_AArch),
            OrderedDict([('triad', 18), ('.LBB0_3', 71), ('.LBB0_4', 76), ('.LBB0_5', 84),
                         ('.LBB0_7', 92), ('.LBB0_8', 95), ('.LBB0_9', 106), ('.LBB0_11', 118),
                         ('.LBB0_12', 133), ('.LBB0_14', 177), ('.LBB0_15', 190),
                         ('.LBB0_16', 205), ('.LBB0_17', 208), ('.LBB0_18', 221),
                         ('.LBB0_19', 228), ('.LBB0_20', 260), ('.LBB0_22', 272),
                         ('.LBB0_24', 283), ('.LBB0_26', 290), ('.LBB0_28', 298),
                         ('.LBB0_29', 306), ('.LBB0_31', 448), ('.LBB0_32', 458),
                         ('.LBB0_33', 480), ('.LBB0_34', 484), ('.LBB0_35', 493),
                         ('.LBB0_36', 504), ('.LBB0_37', 508), ('.LBB0_38', 518),
                         ('main', 574)]))

    def test_find_basic_blocks(self):
        self.assertEqual(
            [(k, v[0]['line_number'], v[-1]['line_number'])
             for k, v in find_basic_blocks(self.parsed_x86).items()],
            [('.LFB24', 12, 56), ('.L4', 67, 74), ('.L3', 81, 89), ('.L2', 104, 112),
             ('.L13', 113, 121), ('.L12', 122, 125), ('.L6', 134, 135), ('.L10', 147, 154),
             ('.L9', 163, 170), ('.L8', 185, 187), ('.L15', 254, 256), ('.L26', 258, 259),
             ('.L14', 261, 262), ('.LFB25', 279, 290), ('.L28', 291, 300)])

        self.assertEqual(
            [(k, v[0]['line_number'], v[-1]['line_number'])
             for k, v in find_basic_blocks(self.parsed_AArch).items()],
            [('triad', 20, 64), ('.LBB0_3', 73, 77), ('.LBB0_4', 78, 83), ('.LBB0_5', 86, 89),
             ('.LBB0_7', 94, 95), ('.LBB0_8', 97, 105), ('.LBB0_9', 108, 114),
             ('.LBB0_11', 120, 134), ('.LBB0_12', 135, 173), ('.LBB0_14', 179, 191),
             ('.LBB0_15', 192, 205), ('.LBB0_16', 207, 208), ('.LBB0_17', 210, 222),
             ('.LBB0_18', 223, 228), ('.LBB0_19', 230, 261), ('.LBB0_20', 262, 269),
             ('.LBB0_22', 274, 280), ('.LBB0_24', 285, 286), ('.LBB0_26', 292, 293),
             ('.LBB0_28', 300, 307), ('.LBB0_29', 308, 444), ('.LBB0_31', 450, 459),
             ('.LBB0_32', 460, 480), ('.LBB0_33', 482, 484), ('.LBB0_34', 486, 494),
             ('.LBB0_35', 495, 504), ('.LBB0_36', 506, 508), ('.LBB0_37', 510, 518),
             ('.LBB0_38', 520, 568), ('main', 576, 590)])

    def test_find_basic_loop_body(self):
        self.assertEqual(
            [(k, v[0]['line_number'], v[-1]['line_number'])
             for k, v in find_basic_loop_bodies(self.parsed_x86).items()],
            [('.L4', 67, 74), ('.L10', 147, 154), ('.L28', 291, 300)])

        self.assertEqual(
            [(k, v[0]['line_number'], v[-1]['line_number'])
             for k, v in find_basic_loop_bodies(self.parsed_AArch).items()],
            [('.LBB0_12', 135, 173), ('.LBB0_15', 192, 205), ('.LBB0_18', 223, 228),
             ('.LBB0_29', 308, 444), ('.LBB0_32', 460, 480), ('.LBB0_35', 495, 504)])

    ##################
    # Helper functions
    ##################

    @staticmethod
    def _find_file(name):
        testdir = os.path.dirname(__file__)
        name = os.path.join(testdir, 'test_files', name)
        assert os.path.exists(name)
        return name


if __name__ == '__main__':
    suite = unittest.TestLoader().loadTestsFromTestCase(TestMarkerUtils)
    unittest.TextTestRunner(verbosity=2).run(suite)
