#!/usr/local/bin/python3
# pylint: disable=C0103
# pylint: disable=C0301

"""This script tests the current accuracy of our labeling tool"""

import csv
import datetime
import logging
import math
import os
import sys
from pprint import pprint
from meerkat.various_tools import load_dict_list

def test_accuracy(params, file_path=None, non_physical_trans=[], result_list=[]):
	"""Takes file by default but can accept result
	queue/ non_physical list. Attempts to provide various
	accuracy tests"""

	if len(result_list) > 0:
		machine_labeled = result_list
	elif file_path is not None and os.path.isfile(file_path):
		ML_file = open(file_path, encoding="utf-8", errors='replace')
		machine_labeled = list(csv.DictReader(ML_file))
	else:
		logging.warning("Not enough information provided to perform accuracy tests on")
		return

	# Load Verification Source
	verification_source = params.get("verification_source", "data/misc/verifiedLabeledTrans.csv")
	human_labeled = load_dict_list(verification_source, delimiter=",")

	#Ensure there is something to process
	total = len(machine_labeled)
	total_processed = len(machine_labeled) + len(non_physical_trans)

	if total == 0 or total_processed == 0:
		logging.warning("Nothing provided to perform accuracy tests on")
		return

	non_physical_trans = non_physical_trans or []
	needs_hand_labeling = []
	non_physical = []
	mislabeled = []
	unlabeled = []
	correct = []

	# Test Recall / Precision
	for machine_labeled_row in machine_labeled:

		# Our confidence was not high enough to label
		if machine_labeled_row["factual_id"] == "":
			unlabeled.append(machine_labeled_row['DESCRIPTION'])
			continue

		# Verify against human labeled
		for index, human_labeled_row in enumerate(human_labeled):
			if machine_labeled_row['DESCRIPTION'] == human_labeled_row['DESCRIPTION']:
				if human_labeled_row['IS_PHYSICAL_TRANSACTION'] == '0':
					# Transaction is non physical
					non_physical.append(machine_labeled_row['DESCRIPTION'])
					break
				elif human_labeled_row["factual_id"] == "":
					# Transaction is not yet labeled
					needs_hand_labeling.append(machine_labeled_row['DESCRIPTION'])
					break
				elif machine_labeled_row["factual_id"] == human_labeled_row["factual_id"]:
					# Transaction was correctly labeled
					correct.append(human_labeled_row['DESCRIPTION'] + " (ACTUAL:" + human_labeled_row["factual_id"] + ")")
					break
				else:
					# Transaction is mislabeled
					mislabeled.append(human_labeled_row['DESCRIPTION'] + " (ACTUAL:" + human_labeled_row["factual_id"] + ")" + " (FOUND:" + machine_labeled_row["factual_id"] + ")")
					break
			elif index + 1 == len(human_labeled):
				needs_hand_labeling.append(machine_labeled_row['DESCRIPTION'])

	# Test Binary
	for item in unlabeled:
		for index, human_labeled_row in enumerate(human_labeled):
			if item == human_labeled_row['DESCRIPTION']:
				if human_labeled_row['IS_PHYSICAL_TRANSACTION'] == '0':
					# Transaction is non physical
					non_physical.append(item)
					break

	incorrect_non_physical = []

	for item in non_physical_trans:
		for index, human_labeled_row in enumerate(human_labeled):
			if item == human_labeled_row['DESCRIPTION']:
				if human_labeled_row['IS_PHYSICAL_TRANSACTION'] == '1':
					incorrect_non_physical.append(item)

	# Collect results into dict for easier access
	num_labeled = total - len(unlabeled)
	num_verified = num_labeled - len(needs_hand_labeling)
	num_verified = num_verified if num_verified > 0 else 1
	num_correct = len(correct)
	binary_accuracy = 100 - ((len(non_physical) + len(incorrect_non_physical)) / total_processed) * 100

	rounded_percent = lambda x: math.ceil(x * 100)

	return {
		"total_processed": total_processed,
		"total_physical": len(machine_labeled) / total_processed * 100,
		"total_non_physical": len(non_physical_trans) / total_processed * 100,
		"correct": correct,
		"needs_hand_labeling": needs_hand_labeling,
		"non_physical": non_physical,
		"unlabeled": unlabeled,
		"num_verified": num_verified,
		"num_labeled": num_labeled,
		"mislabeled": mislabeled,
		"total_recall": num_labeled / total_processed * 100,
		"total_recall_physical": num_labeled / total * 100,
		"precision": num_correct / num_verified * 100,
		"binary_accuracy": binary_accuracy
	}

def speed_tests(start_time, accuracy_results):
	"""Run a number of tests related to speed"""

	time_delta = datetime.datetime.now() - start_time
	seconds = time_delta.seconds if time_delta.seconds > 0 else 1

	time_per_transaction = seconds / accuracy_results['total_processed']
	transactions_per_minute = (accuracy_results['total_processed'] / seconds) * 60

	print("\nSPEED TESTS:")
	print("{0:35} = {1:11}".format("Total Time Taken", str(time_delta)[0:11]))
	print("{0:35} = {1:11.2f}".format("Time per Transaction (in seconds)", time_per_transaction))
	print("{0:35} = {1:11.2f}".format("Transactions Per Minute", transactions_per_minute))

	return {'time_delta':time_delta,
			'time_per_transaction': time_per_transaction,
			'transactions_per_minute':transactions_per_minute}

def print_results(results):
	"""Provide useful readable output"""

	if results is None:
		return
		
	print("\nSTATS:")
	print("{0:35} = {1:11}".format("Total Transactions Processed", results['total_processed']))
	print("{0:35} = {1:10.2f}%".format("Total Labeled Physical", results['total_physical']))
	print("{0:35} = {1:10.2f}%".format("Total Labeled Non Physical", results['total_non_physical']))
	print("{0:35} = {1:10.2f}%".format("Binary Classifier Accuracy", results['binary_accuracy']))
	print("\n")
	print("{0:35} = {1:10.2f}%".format("Recall all transactions", results['total_recall']))
	print("{0:35} = {1:10.2f}%".format("Recall physical", results['total_recall_physical']))
	print("{0:35} = {1:11}".format("Number of transactions labeled", results['num_labeled']))
	print("{0:35} = {1:11}".format("Number of transactions verified", results['num_verified']))
	print("{0:35} = {1:10.2f}%".format("Precision", results['precision']))
	print("", "MISLABELED:", '\n'.join(results['mislabeled']), sep="\n")
	print("", "MISLABELED BINARY:", '\n'.join(results['non_physical']), sep="\n")

if __name__ == "__main__":
	output_path = sys.argv[1] if len(sys.argv) > 1 else "data/output/meerkatLabeled.csv"
	pprint(test_accuracy(file_path=output_path))
	#print_results(test_accuracy(file_path=output_path))