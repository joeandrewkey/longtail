#!/usr/local/bin/python3
# pylint: disable=C0301

"""This bulk loader handles multiple threads."""
import json
import logging
import queue
import re
import sys
import threading
from pprint import pprint

from elasticsearch import Elasticsearch, helpers
from datetime import datetime

from meerkat.custom_exceptions import InvalidArguments, Misconfiguration
def initialize():
	"""Validates the command line arguments."""
	input_file, params = None, None

	if len(sys.argv) != 2:
		#usage()
		raise InvalidArguments(msg="Supply a single argument for the json"\
		+ "formatted configuration file.", expr=None)

	try:
		input_file = open(sys.argv[1], encoding='utf-8')
		params = json.loads(input_file.read())
		input_file.close()
	except IOError:
		logging.error(sys.argv[1] + " not found, aborting.")
		sys.exit()

	if validate_params(params):
		logging.warning("Parameters are valid, proceeding.")
	return params

def load_document_queue(params):
	"""Opens a file of merchants, one per line, and loads a document queue."""

	lines, filename, encoding = None, None, None
	document_queue = queue.Queue()

	try:
		filename = params["input"]["filename"]
		encoding = params["input"]["encoding"]
		with open(filename, 'r', encoding=encoding) as inputfile:
			records = [line.rstrip('\n') for line in inputfile]
	except IOError:
		msg = "Invalid ['input']['filename'] key; Input file: " + filename \
		+ " cannot be found. Correct your config file."
		logging.critical(msg)
		sys.exit()

	header = records.pop(0).split("\t")

	for input_string in records:
		document_queue.put(input_string)
	document_queue_populated = True

	return header, document_queue, document_queue_populated

class ThreadConsumer(threading.Thread):
	"""Used for our consumer threads."""
	def __init__(self, thread_id, params):
		"""Constructor"""
		threading.Thread.__init__(self)
		self.thread_id = thread_id
		self.params = params
		self.document_queue = params["document_queue"]
		self.params["concurrency_queue"].put(self.thread_id)
		cluster_nodes = self.params["elasticsearch"]["cluster_nodes"]
		self.es_connection = Elasticsearch(cluster_nodes, sniff_on_start=True,
			sniff_on_connection_fail=True, sniffer_timeout=5, sniff_timeout=5)
		self.__set_logger()
		self.batch_list = []

	def __set_logger(self):
		"""Creates a logger, based upon the supplied config object."""
		levels = {'debug': logging.DEBUG, 'info': logging.INFO\
		, 'warning': logging.WARNING, 'error': logging.ERROR\
		, 'critical': logging.CRITICAL}
		params = self.params
		my_level = params["logging"]["level"]
		if my_level in levels:
			my_level = levels[my_level]
		my_path = params["logging"]["path"]
		my_formatter = logging.Formatter(params['logging']['formatter'])
		#You'll want to add something to identify the thread
		my_logger = logging.getLogger("thread " + str(self.thread_id))
		my_logger.setLevel(my_level)
		file_handler = logging.FileHandler(my_path)
		file_handler.setLevel(my_level)
		file_handler.setFormatter(my_formatter)
		my_logger.addHandler(file_handler)

		#Add console logging, if configured
		if params["logging"]["console"] is True:
			console_handler = logging.StreamHandler()
			console_handler.setLevel(my_level)
			console_handler.setFormatter(my_formatter)
			my_logger.addHandler(console_handler)
		my_logger.info("Log initialized.")

	def run(self):
		"""Eats from the document queue and bulk loads."""
		my_logger = logging.getLogger("thread " + str(self.thread_id))
		params, document_queue = self.params, self.document_queue
		batch_list = self.batch_list
		concurrency_queue = params["concurrency_queue"]
		document_queue_populated = params["document_queue_populated"]
		while True:
			count = 0
			if document_queue_populated and document_queue.empty():
				concurrency_queue.get()
				concurrency_queue.task_done()
				concurrency_qsize = concurrency_queue.qsize()
				my_logger.info("Consumer finished, concurrency queue size: %i",
					concurrency_queue.qsize())
				return
			for i in range(params["batch_size"]):
				try:
					batch_list.append(document_queue.get(block=False))
					document_queue.task_done()
					count = count + 1
				except queue.Empty:
					if count > 0:
						my_logger.info("queue was empty")
						self.__publish_batch()
						count = 0
			if count > 0:
				self.__publish_batch()

	def __publish_batch(self):
		"""Publishes a bulk index to ElasticSearch."""
		my_logger = logging.getLogger("thread " + str(self.thread_id))
		header = self.params["header"]
		queue_size = len(self.batch_list)
		my_logger.debug("Queue size %i", queue_size)

		#Split the batch into cells built of keys and values, excluding
		#blank values
		params = self.params
		docs, actions = [], []
		composite_fields = params["elasticsearch"]["composite_fields"]
		dispersed_fields = params["elasticsearch"]["dispersed_fields"]
		while len(self.batch_list) > 0:
			current_item = self.batch_list.pop(0)
			item_list = current_item.split("\t")

			if len(header) == len(item_list):
				d = {x: y for (x, y) in list(zip(header, item_list)) if y != ""}
				#merge latitude and longitude into a point
				if "longitude" in d and "latitude" in d:
					d["pin"] = { "location": {
						"type": "point", "coordinates" : [
						d["longitude"], d["latitude"] ] } }
					del d["longitude"]
					del d["latitude"]

				#Routine to create composite fields
				for field in composite_fields:
					keys = field.keys()
					for key in keys:
						my_dict = field[key]
						components = my_dict["components"]
						composite_format = my_dict["format"]
						component_values = []
						for component in components:
							if component in d:
								component_values.append(d[component])
							else:
								component_values.append('')
						composite_string = composite_format.format(*component_values).strip()
						if "composite" not in d:
							d["composite"] = {}
						d["composite"][key] = composite_string
						my_logger.debug("New dict is: %s", str(d))

				#Routine to create dispersed_fields
				for field in dispersed_fields:
					keys = field.keys()
					for key in keys:
						my_dict = field[key]
						dispersion_regex = my_dict["dispersion_regex"]
						dispersion_re=re.compile(dispersion_regex)
						components = my_dict['components']
						if "dispersed" not in d:
							d["dispersed"] = {}
						d["dispersed"][key] = {}
						for component in components:
							component_name = component["name"]
							if key in d:
								input_string = d[key]
								if dispersion_re.search(input_string):
									matches = dispersion_re.match(input_string)
									d["dispersed"][key][component_name] = matches.group(component_name)

				docs.append(d)
				action = {
					"_index": params["elasticsearch"]["index"],
					"_type": params["elasticsearch"]["type"],
					"_id": d["factual_id"],
					"_source": d,
					"timestamp": datetime.now()
				}
				actions.append(action)
		
		# Make Calls to Elastic Search
		_, errors = helpers.bulk(self.es_connection, actions)
		
		# Evaluate Success Rate
		success, failure, total = 0, 0, 0
		"""for item in errors:
			if item["index"]["ok"]:
				success += 1
			else:
				failure += 1
			total += 1
		my_logger.info("Success/Failure/Total: %i/%i/%i - %i documents in queue."
			, success, failure, total, self.document_queue.qsize())
		"""
		my_logger.info("%i documents in queue.", self.document_queue.qsize())

def start_consumers(params):
	"""Starts our consumer threads"""
	for i in range(params["concurrency"]):
		c = ThreadConsumer(i,params)
		c.setDaemon(True)
		c.start()

def ensure_keys_in_dictionary(dictionary, keys, prefix=''):
	"""Function to determine if the supplied dictionary has the necessary keys."""
	for key in keys:
		if key not in dictionary:
			raise Misconfiguration(msg="Missing key, '" + prefix + key + "'", expr=None)
	return True

def validate_params(params):
	"""Ensures that the correct parameters are supplied."""
	my_keys = ["elasticsearch", "concurrency", "input", "logging", "batch_size"]
	ensure_keys_in_dictionary(params, my_keys)

	my_keys = ["index", "type_mapping", "type", "cluster_nodes",
		"boost_labels", "boost_vectors", "composite_fields", "dispersed_fields"]
	ensure_keys_in_dictionary(params["elasticsearch"], my_keys,
		prefix="elasticsearch.")

	my_keys = ["filename", "encoding"]
	ensure_keys_in_dictionary(params["input"], my_keys, prefix="input.")

	my_keys = ["path", "level", "formatter", "console"]
	ensure_keys_in_dictionary(params["logging"], my_keys, prefix="logging.")

	if params["concurrency"] <= 0:
		raise Misconfiguration(msg="'concurrency' must be a positive integer", expr=None)

	my_type = params["elasticsearch"]["type"]
	my_props = params["elasticsearch"]["type_mapping"]["mappings"][my_type]["properties"]

	composite_fields = params["elasticsearch"]["composite_fields"]
	my_keys = ["components", "format", "index", "type"]
	for field in composite_fields:
		keys = field.keys()
		for key in keys:
			my_dict = field[key]
			ensure_keys_in_dictionary(my_dict, my_keys,
				prefix="elasticsearch.composite_fields.")

			components = my_dict["components"]
			for component in components:
				if component not in my_props:
					raise Misconfiguration(msg="Component feature '" + component +\
					"' does not exist and cannot be used to build the '" +\
					key + "' feature.", expr=None)

	#TODO:  Validate "dispersed_fields" for good regex, valid components
	dispersed_fields = params["elasticsearch"]["dispersed_fields"]
	my_keys = ["dispersion_regex", "components"]
	for field in dispersed_fields:
		keys = field.keys()
		for key in keys:
			my_dict = field[key]
			ensure_keys_in_dictionary(my_dict, my_keys,
				prefix="elasticsearch.dispersed_fields.")



	#Ensure that "boost_labels" and "boost_vectors" row vectors have the same cardinality
	label_length = len(params["elasticsearch"]["boost_labels"])
	boost_vectors = params["elasticsearch"]["boost_vectors"]
	for key in boost_vectors:
		if len(boost_vectors[key]) != label_length:
			raise Misconfiguration(msg="Row vector 'elasticsearch.boost_vectors." + key +\
			"' should have exactly " + str(label_length) + " values.", expr=None)

	#Ensure that "boost_vectors" is a subset of your mapping properties
	add_composite_type_mappings(params)
	add_dispersed_type_mappings(params)
	my_props = params["elasticsearch"]["type_mapping"]["mappings"][my_type]["properties"]
	missing_keys = dict.fromkeys(boost_vectors.keys() - my_props, "")
	found_keys = []
	for key in missing_keys:
		key_expand = key.replace(".",".properties.")
		key_split = key_expand.split(".")
		my_dict, key_count, key_total = my_props, 0, len(key_split)
		for second_key in key_split:
			if second_key in my_dict:
				my_dict = my_dict[second_key]
			else:
				raise Misconfiguration(msg="The following boost_vector key " +\
				"is missing from the type mapping: " + str(key) , expr=None)
			key_count += 1
			if key_count == key_total:
				logging.warning("key: '" + key + "' was found.")
				found_keys.append(key)
	for key in found_keys:
		del missing_keys[key]

	if missing_keys:
		raise Misconfiguration(msg="The following boost_vector keys are" +\
		"missing from the type mapping: " + str(missing_keys) , expr=None)
	return True

def add_composite_type_mappings(params):
	"""Add additional type mapping properties for composite fields."""
	my_type = params["elasticsearch"]["type"]
	my_properties = params["elasticsearch"]["type_mapping"]["mappings"][my_type]["properties"]
	composite_fields = params["elasticsearch"]["composite_fields"]
	for field in composite_fields:
		keys = field.keys()
		for key in keys:
			my_dict = field[key]
			if "composite" not in my_properties:
				my_properties["composite"] = { "properties" : {} }
			my_properties["composite"]["properties"][key] = {
				"index" : field[key]["index"],
				"type" : field[key]["type"]
			}
	logging.critical(json.dumps(params, sort_keys=True, indent=4, separators=(',', ':')))

def add_dispersed_type_mappings(params):
	"""Add additional type mapping properties for dispersed fields."""
	my_type = params["elasticsearch"]["type"]
	my_properties = params["elasticsearch"]["type_mapping"]["mappings"][my_type]["properties"]
	dispersed_fields = params["elasticsearch"]["dispersed_fields"]
	if "dispersed" not in my_properties:
		my_properties["dispersed"] = { "properties" : {} }
	for field in dispersed_fields:
		keys = field.keys()
		for key in keys:
			components = field[key]["components"]
			for component in components:
				my_properties["dispersed"]["properties"][component["name"]] = {
					"index" : component["index"],
					"type" : component["type"]
				}
	logging.critical(json.dumps(params, sort_keys=True, indent=4, separators=(',', ':')))

def guarantee_index_and_doc_type(params):
	"""Ensure that the index and document type mapping are as they should be"""
	cluster_nodes = params["elasticsearch"]["cluster_nodes"]
	es_index = params["elasticsearch"]["index"]
	doc_type = params["elasticsearch"]["type"]
	es_connection = Elasticsearch(cluster_nodes, sniff_on_start=True,
		sniff_on_connection_fail=True, sniffer_timeout=5, sniff_timeout=5)
	if es_connection.indices.exists(index=es_index):
		logging.critical("Index exists, continuing")
		if es_connection.indices.exists_type(index=es_index,doc_type=doc_type):
			logging.critical("Doc type exists, continuing")
	else:
		logging.warning("Index does not exist, creating")
		index_body = params["elasticsearch"]["type_mapping"]
		result = es_connection.indices.create(index=es_index,body=index_body)
		ok, acknowledged = result["ok"], result["acknowledged"]
		if ok and acknowledged:
			logging.critical("Index created successfully.")
		else:
			logging.error("Failed to create index, aborting.")
			sys.exit()

if __name__ == "__main__":
	#Runs the entire program.
	PARAMS = initialize()
	logging.warning(json.dumps(PARAMS, sort_keys=True, indent=4, separators=(',', ':')))
	guarantee_index_and_doc_type(PARAMS)
	PARAMS["document_queue_populated"] = False
	PARAMS["concurrency_queue"] = queue.Queue()
	PARAMS["header"], PARAMS["document_queue"],\
	PARAMS["document_queue_populated"] = load_document_queue(PARAMS)
	start_consumers(PARAMS)
	PARAMS["concurrency_queue"].join()
	logging.info("Concurrency joined")
	PARAMS["document_queue"].join()
	logging.info("Documents joined")

	logging.critical("End of program.")