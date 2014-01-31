#!/usr/bin/python3.3
"""Creates an ElasticSearch index and bulk loads it with data."""

import json, sys, re
from longtail.various_tools import string_cleanse
from longtail.custom_exceptions import InvalidArguments, InvalidNumberOfLines\
, FileProblem
from longtail.query_templates import get_mapping_template, get_create_object\
, get_composites

USAGE = """Usage:
	<input_file_name>
	<input_lines_to_scan>
	<elasticsearch_index>
	<elasticsearch_type>"""

NAME, DATA_TYPE, INDEX = 0, 1, 2

def initialize():
	"""This function does basic validation for the command-line
	parameters."""
	if len(sys.argv) != 5:
		usage()
		raise InvalidArguments("Incorrect number of arguments")
	input_file_name, input_lines_to_scan, es_index, es_type = sys.argv[1:5]
	try:
		number_of_lines = int(input_lines_to_scan)
	except:
		usage()
		raise InvalidNumberOfLines("Number of lines must be an integer")
	try:
		input_file = open(input_file_name)
		input_file.close()
	except:
		usage()
		raise FileProblem(input_file_name + " cannot be opened.")

	bulk_create_file = es_index + "." + es_type + ".bulk_create"
	try:
		bulk_create_file = open(bulk_create_file, "w")
	except:
		raise FileProblem(bulk_create_file + " cannot be created.")

	type_mapping_file = es_index + "." + es_type + ".mapping"
	try:
		type_mapping_file = open(type_mapping_file, "w")
	except:
		raise FileProblem(type_mapping_file + " cannot be created.")

	return number_of_lines, input_file_name, bulk_create_file\
	, type_mapping_file, es_index, es_type

def revise_column_data_type(col_num, my_cell, column_meta):
	"""This function tries to determine the best fit for the column,
	based upon observing values found in the input for the column."""
	pattern = 1
	my_data_type = column_meta[col_num][DATA_TYPE]
	if my_data_type == STRING:
		return my_data_type
	if my_cell == "":
		return my_data_type
	if DATA_TYPES[my_data_type][pattern].match(my_cell):
		return my_data_type
	else:
		column_meta[col_num][DATA_TYPE] += 1
		return revise_column_data_type(col_num, my_cell, column_meta)

def scan_column_headers(my_cells):
	"""This function scans the first line of the data input file in
	order to provide column names for our index."""
	column_meta = {}
	for my_col_number in range(len(my_cells)):
		#NAME, DATA_TYPE, INDEX
		column_meta[my_col_number] = [my_cells[my_col_number].strip()
		, NULL, "analyzed" ]
	return column_meta

def usage():
	"""Shows which command line arguments should be passed to the
	program."""
	print(USAGE)

def process_row(cells, column_meta, es_index, es_type):
	"""Scans a row from the input and returns:
	1.  JSON for the 'bulk create'
	2.  A record object that contains most fields needed"""
	record_obj = {}
	for column_number in range(len(cells)):
		cell = string_cleanse(str(cells[column_number]).strip())
		if column_number == 0:
			create_obj = get_create_object(es_index, es_type, cell)
			create_json = json.dumps(create_obj)
		revise_column_data_type(column_number, cell, column_meta)

		#Special handling for LATITUDE and LONGITUDE
		if column_meta[column_number][NAME] == "LATITUDE":
			record_obj["pin"] = {}
			record_obj["pin"]["location"] = {}
			record_obj["pin"]["location"]["lat"] = cell
		elif column_meta[column_number][NAME] == "LONGITUDE":
			record_obj["pin"]["location"]["lon"] = cell
		elif len(cell) == 0:
			continue
		else:
			record_obj[column_meta[column_number][NAME]] = cell

	return record_obj, create_json

def process_input_rows(input_file_name, es_index, es_type):
	"""Reads each line in the input file, creating bulk insert records
	for each in ElasticSearch."""
	line_count = 0
	column_meta = {}

	with open(input_file_name, "r", encoding="utf-8") as input_file:
		lines = input_file.read()

	for line in lines.split("\n"):
		cells = line.split("\t")
		column_meta["total_fields"] = len(cells)
		if line_count == 0:
			column_meta = scan_column_headers(cells)
		elif line_count >= INPUT_LINES_TO_SCAN:
			break
		else:
			#Process each row of input data
			record_obj, create_json = process_row(cells\
			, column_meta, es_index, es_type)
			#Add the composite features
			get_composites(record_obj)
			record_json = str(json.dumps(record_obj))
			BULK_CREATE_FILE.write(create_json + "\n")
			BULK_CREATE_FILE.write(record_json + "\n")
		line_count += 1
	return column_meta

#DICTIONARIES
NULL, FLOAT, DATE, INT, STRING = 0, 1, 2, 3, 4
DATE_REGEX = "^[0-9]{4}(0[1-9]|1[012])(0[1-9]|[12][0-9]|3[01])$"
DATA_TYPES = { \
	NULL : ("null", re.compile("^$")) , \
	FLOAT : ("float", re.compile(r"[-+]?[0-9]*\.[0-9]+")) , \
	DATE : ("date", re.compile(DATE_REGEX)) , \
	INT : ("integer", re.compile("^[-+]?[0-9]+$")) , \
	STRING : ("string", re.compile(".+")) \
}

if __name__ == "__main__":
	#Runs the entire program.
	INPUT_LINES_TO_SCAN, INPUT_FILE, BULK_CREATE_FILE, TYPE_MAPPING_FILE\
	, ES_INDEX, ES_TYPE = initialize()
	COLUMN_META = process_input_rows(INPUT_FILE, ES_INDEX, ES_TYPE)
	MY_MAP = get_mapping_template(ES_TYPE, 3, 2, COLUMN_META, DATA_TYPES)
	TYPE_MAPPING_FILE.write(json.dumps(MY_MAP))