"""Unit test for meerkat/classification/classification_report.py"""

import os
import meerkat.classification.classification_report as cr
import unittest
import argparse

from nose_parameterized import parameterized
from tests.classification.fixture import classification_report_fixture
from meerkat.various_tools import load_piped_dataframe

class ClassifcationReportTests(unittest.TestCase):
	"""Unit tests for meerkat.classification.auto_load."""

	@parameterized.expand([
		([classification_report_fixture.get_machine_result(), False,
			classification_report_fixture.get_compare_label_result_non_fast()]),
		([classification_report_fixture.get_machine_result(), True,
			classification_report_fixture.get_compare_label_result_fast()])
	])
	def test_compare_label(self, machine, fast, expected):
		"""Test compare_label with parameters"""
		cf = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
		kwargs = {"doc_key": "DESCRIPTION_UNMASKED", "fast_mode": fast}
		self.assertEqual(cr.compare_label(machine, 'PREDICTED_CLASS', 'PROPOSED_SUBTYPE', cf, 3,
			**kwargs), expected)

	@parameterized.expand([
		(False, ["model", "data", "label_map", "label",  "--doc_key", "SNOZ"])
	])
	def test_parse_arguments(self, exception_test, arguments):
		"""Simple test to ensure that this function works"""
		if not exception_test:
			parser = cr.parse_arguments(arguments)
			self.assertEqual(parser.model, "model")
			self.assertEqual(parser.data, "data")
			self.assertEqual(parser.label_map, "label_map")
			self.assertEqual(parser.label, "label".upper())
			self.assertEqual(parser.doc_key, "SNOZ")

	@parameterized.expand([
		([classification_report_fixture.get_csv(), 18])
	])
	def test_count_transactions(self, filename, num_of_trans):
		"""Test count_transactions with parameters"""
		self.assertEqual(cr.count_transactions(filename), num_of_trans)

	@parameterized.expand([
		([classification_report_fixture.get_confusion_matrix("valid_cf"),
			classification_report_fixture.get_label_map(), False]),
		([classification_report_fixture.get_confusion_matrix("invalid_cf"), {}, True])
	])
	def test_get_classification_report(self, cm_file, label_map, exception):
		"""Test get_classification_report with parameters"""
		base_dir = "tests/classification/fixture/"
		report_path = base_dir + "result_classification_report.csv"
		if exception:
			self.assertRaises(Exception, cr.get_classification_report,
				cm_file, label_map, report_path)
		else:
			cr.get_classification_report(cm_file, label_map, report_path)
			expected_path = base_dir + "expected_classification_report.csv"
			df_result = load_piped_dataframe(report_path)
			df_expected = load_piped_dataframe(expected_path)
			self.assertTrue(df_result.equals(df_expected))
			os.remove(report_path)

	@parameterized.expand([
		(['tests/classification/fixture/test_get_write_func.csv', ['TRANSACTION_DESCRIPTION', 'ACTUAL']])
	])
	def test_get_write_func(self, filename, header):
		write_correct = cr.get_write_func(filename, header)
		correct = [['NEWTON GRV BST NEWTON GROVE NC', 'Abc']]
		write_correct(correct)
		self.assertTrue(os.path.isfile(filename), True)
		os.remove(filename)

if __name__ == '__main__':
	unittest.main()
