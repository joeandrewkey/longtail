#!/usr/local/bin/python3
# pylint: disable=C0301

"""This script scans, tokenizes, and constructs queries to match transaction
description strings (unstructured data) to merchant data indexed with
ElasticSearch (structured data)."""

import csv, datetime, json, logging, queue, sys, urllib, re
from longtail.custom_exceptions import InvalidArguments, Misconfiguration
from longtail.description_consumer import DescriptionConsumer
from longtail.binary_classifier.bay import predict_if_physical_transaction

def get_desc_queue(params):
	"""Opens a file of descriptions, one per line, and load a description
	queue."""

	lines, filename, encoding = None, None, None
	desc_queue = queue.Queue()

	try:
		filename = params["input"]["filename"]
		encoding = params["input"]["encoding"]
		with open(filename, 'r', encoding=encoding) as inputfile:
			lines = inputfile.read()
	except IOError:
		msg = "Invalid ['input']['filename'] key; Input file: " + filename \
		+ " cannot be found. Correct your config file."
		logging.critical(msg)
		sys.exit()

	# Run Binary Classifier
	for input_string in lines.split("\n"):
		prediction = predict_if_physical_transaction(input_string)
		if prediction == "1":
			desc_queue.put(input_string)
		elif prediction == "0":
			logging.info("NON-PHYSICAL: " + input_string)

	return desc_queue

def initialize():
	"""Validates the command line arguments."""
	input_file, params = None, None

	if len(sys.argv) != 2:
		usage()
		raise InvalidArguments(msg="Incorrect number of arguments", expr=None)

	try:
		input_file = open(sys.argv[1], encoding='utf-8')
		params = json.loads(input_file.read())
		input_file.close()
	except IOError:
		logging.error(sys.argv[1] + " not found, aborting.")
		sys.exit()

	params["search_cache"] = {}

	if validate_params(params):
		logging.warning("Parameters are valid, proceeding.")
	return params

def tokenize(params, desc_queue, parameter_key):
	"""Opens a number of threads to process the descriptions queue."""
	consumer_threads = 1
	result_queue = queue.Queue()
	if "concurrency" in params:
		consumer_threads = params["concurrency"]
	start_time = datetime.datetime.now()
	for i in range(consumer_threads):
		new_consumer = DescriptionConsumer(i, params, desc_queue, result_queue, parameter_key)
		new_consumer.setDaemon(True)
		new_consumer.start()
	desc_queue.join()
	#Writing to an output file, if necessary.
	if "file" in params["output"] and "format" in params["output"]["file"]\
	and params["output"]["file"]["format"] in ["csv", "json"]:
		write_output_to_file(params, result_queue)
	else:
		logging.critical("Not configured for file output.")
	time_delta = datetime.datetime.now() - start_time
	logging.critical("Total Time Taken: " + str(time_delta))

def write_output_to_file(params, result_queue):
	"""Outputs results to a file"""
	output_list = []
	while result_queue.qsize() > 0:
		try:
			output_list.append(result_queue.get())
			result_queue.task_done()

		except queue.Empty:
			break

	if len(output_list) < 1:
		logging.warning("No results available to write")
		return

	result_queue.join()
	file_name = params["output"]["file"].get("path", '../data/output/longtailLabeled.csv')
	file_format = params["output"]["file"].get("format", 'csv')

	# Output as CSV
	if file_format == "csv":
		delimiter = params["output"]["file"].get("delimiter", ',')
		output_file = open(file_name, 'w')
		dict_w = csv.DictWriter(output_file, delimiter=delimiter, fieldnames=output_list[0].keys())
		dict_w.writeheader()
		dict_w.writerows(output_list)
		output_file.close()

	# Output as JSON
	if file_format == "json":
		with open(file_name, 'w') as outfile:
			json.dump(output_list, outfile)

def validate_params(params):
	"""Ensures that the correct parameters are supplied."""
	mandatory_keys = ["elasticsearch", "concurrency", "input", "logging"]
	for key in mandatory_keys:
		if key not in params:
			raise Misconfiguration(msg="Misconfiguration: missing key, '" + key + "'", expr=None)

	if params["concurrency"] <= 0:
		raise Misconfiguration(msg="Misconfiguration: 'concurrency' must be a positive integer", expr=None)

	if "parameter_key" not in params["input"]:
		params["input"]["parameter_key"] = "config/keys/default.json"

	if "index" not in params["elasticsearch"]:
		raise Misconfiguration(msg="Misconfiguration: missing key, 'elasticsearch.index'", expr=None)
	if "type" not in params["elasticsearch"]:
		raise Misconfiguration(msg="Misconfiguration: missing key, 'elasticsearch.type'", expr=None)
	if "cluster_nodes" not in params["elasticsearch"]:
		raise Misconfiguration(msg="Misconfiguration: missing key, 'elasticsearch.cluster_nodes'", expr=None)
	if "path" not in params["logging"]:
		raise Misconfiguration(msg="Misconfiguration: missing key, 'logging.path'", expr=None)
	if "filename" not in params["input"]:
		raise Misconfiguration(msg="Misconfiguration: missing key, 'input.filename'", expr=None)
	if "encoding" not in params["input"]:
		raise Misconfiguration(msg="Misconfiguration: missing key, 'input.encoding'", expr=None)

	return True

def load_parameter_key(params):
	"""Attempts to load parameter key"""
	parameter_key = None
	try:
		input_file = open(params["input"]["parameter_key"], encoding='utf-8')
		parameter_key = json.loads(input_file.read())
		input_file.close()
	except IOError:
		logging.error(params["input"]["parameter_key"] + " not found, aborting.")
		sys.exit()
	return parameter_key

def usage():
	"""Shows the user which parameters to send into the program."""
	result = "Usage:\n\t<path_to_json_format_config_file>"
	logging.error(result)
	return result

if __name__ == "__main__":
	#Runs the entire program.
	PARAMS = initialize()
	KEY = load_parameter_key(PARAMS)
	DESC_QUEUE = get_desc_queue(PARAMS)
	tokenize(PARAMS, DESC_QUEUE, KEY)