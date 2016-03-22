"""Unit test for meerkat.various_tools"""

import numpy as np
import unittest
import meerkat.various_tools as various_tools
from nose_parameterized import parameterized
from tests.fixture import various_tools_fixture

class VariousToolsTests(unittest.TestCase):

	"""Our UnitTest class."""

	strings = (("Weekend at Bernie's[]{}/:", "weekend at bernie s"),
                ('Trans with "" quotes', 'trans with quotes'))

	numbers = (("[8]6{7}5'3/0-9", "8675309"),
				('333"6"6"6"999', '333666999'))

	def test_string_cleanse(self):
		"""string_cleanse test"""

		for chars, no_chars in self.strings:
			result = various_tools.string_cleanse(chars)
			self.assertEqual(no_chars, result)

	@parameterized.expand([
		([various_tools_fixture.get_queue()["non_empty"], [1, 2, 3]]),
		([various_tools_fixture.get_queue()["empty"], []])
	])
	def test_queue_to_list(self, result_queue, result_list):
		"""Test queue_to_list with parameters"""
		self.assertEqual(various_tools.queue_to_list(result_queue), result_list)

	@parameterized.expand([
		(["abc\\|ef\"ghi", "c ef"]),
		(["abc\\ef\"\"ghij", "c\\efg"]),
		(["abc|efghij", "c|efg"])
	])
	def test_clean_line(self, line, output):
		"""Test clean_line with parameters"""
		self.assertEqual(various_tools.clean_line(line), output)

if __name__ == '__main__':
	unittest.main()
