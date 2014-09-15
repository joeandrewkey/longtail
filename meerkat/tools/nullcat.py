#!/usr/local/bin/python3.3

"""This module transforms panels built by the Clustering Tool into a
format also used by Meerkat. It does not use Meerkat.

@author: J. Andrew Key
"""

#################### USAGE ##########################

# python3.3 -m meerkat.nullcat <bank_or_card> <regex_filter>
# python3.3 -m meercat.nullcat bank 201306.*[02468]

#####################################################

import boto
import gzip
import re
import sys

from boto.s3.connection import Key, Location
from copy import deepcopy
from .various_tools import safely_remove_file

OUTPUT_FORMAT = [\
"UNIQUE_MEM_ID", "UNIQUE___BLANK_ACCOUNT_ID", "UNIQUE___BLANK_TRANSACTION_ID",\
"MEM_ID", "__BLANK_ACCOUNT_ID", "__BLANK_TRANSACTION_ID", "COBRAND_ID",\
"SUM_INFO_ID", "AMOUNT", "CURRENCY_ID", "DESCRIPTION", "TRANSACTION_DATE",\
"POST_DATE", "TRANSACTION_BASE_TYPE", "TRANSACTION_CATEGORY_ID",\
"TRANSACTION_CATEGORY_NAME", "MERCHANT_NAME", "STORE_ID", "FACTUAL_CATEGORY",\
"STREET", "CITY", "STATE", "ZIP_CODE", "WEBSITE", "PHONE_NUMBER", "FAX_NUMBER",\
"CHAIN_NAME", "LATITUDE", "LONGITUDE", "NEIGHBOURHOOD", "TRANSACTION_ORIGIN",\
"CONFIDENCE_SCORE", "FACTUAL_ID", "FILE_CREATED_DATE"]

CLEAN_PATTERN = re.compile(r"\\+\|")

def begin_processing_loop(some_container, filter_expression):
	"""Fetches a list of input files to process from S3 and loops over them."""

	conn = boto.connect_s3()
	pending_list = []
	completed = {}

	# Set source details
	src_bucket_name = "s3yodlee"
	src_folders = "ctprocessed/gpanel/" + some_container + "/"
	src_s3_path_regex = re.compile(src_folders + "(" + filter_expression + "[^/]+)")
	src_local_path = "/mnt/ephemeral/input/"
	src_bucket = conn.get_bucket(src_bucket_name, Location.USWest2)

	# Set destination details
	dst_bucket_name = "yodleeproducts"
	dst_folders = "panels/6m/" + some_container + "/"
	dst_s3_path_regex = re.compile(dst_folders + "(" + filter_expression + "[^/]+)")
	dst_local_path = "/mnt/ephemeral/output/"
	dst_bucket = conn.get_bucket(dst_bucket_name, Location.USWest2)

	# Set error destination details
	error_bucket_name = "yodleeproducts"
	error_local_path = "/mnt/ephemeral/output/"
	error_bucket = conn.get_bucket(error_bucket_name, Location.USWest2)
	error_s3_path = "panels/6m/error/"

	print("DST folder is: s3://{0}/{1}({2}[^/]+)".format(dst_bucket_name, dst_folders, filter_expression))
	print("SRC folder is: s3://{0}/{1}({2}[^/]+)".format(src_bucket_name, src_folders, filter_expression))

	# Get the list of completed files (already proceseed)
	for j in dst_bucket.list():
		if dst_s3_path_regex.search(j.key):
			completed[dst_s3_path_regex.search(j.key).group(1)] = j.size

	# Get list of pending files (yet to be processed)
	for k in src_bucket.list():

		if src_s3_path_regex.search(k.key):
			file_name = src_s3_path_regex.search(k.key).group(1)
			if file_name in completed:

				#Exclude files that have already been completed
				ratio = float(k.size) / completed[file_name]
				#Completed incorrectly
				if ratio >= 1.8:
					print("Completed Size, Source Size, Ratio: {0}, {1}, {2:.2f}".format(completed[file_name], k.size, ratio))
					print("Re-running {0}".format(file_name))
					pending_list.append(k)
			elif k.size > 0:
				pending_list.append(k)

	# THIS IS WHERE THIS FUNCTION SHOULD END - NAME something like get current task status
	# Should return pending list, perhaps other things as well

	# Reverse the pending list so that they are processed in reverse chronological order
	pending_list.reverse()
	if not pending_list:
		print("Everything is up-to-date.")

	# Loop through each file in the list of files to process
	dst_s3_path = "meerkat/nullcat/" + some_container + "/"

	for item in pending_list:
		src_file_name = src_s3_path_regex.search(item.key).group(1)
		dst_file_name = src_file_name
		print(src_file_name)

		# Copy the input file from S3 to the local file system
		item.get_contents_to_filename(src_local_path + src_file_name)
		header_name_pos, header_pos_name = get_header_dictionaries(some_container, \
		src_file_name, src_local_path)
		map_of_column_positions = get_map_of_column_positions(header_name_pos,\
		some_container)

		#Process the individual file
		process_args = [src_file_name, src_local_path, dst_file_name]
		process_args = process_args + [dst_local_path, header_pos_name, map_of_column_positions, some_container]
		had_error = process_file(*process_args)
		safely_remove_file(src_local_path + src_file_name)

		#Push the results from the local file system to S3
		dst_key = Key(dst_bucket)
		dst_key.key = dst_s3_path + src_file_name
		bytes_written = dst_key.set_contents_from_filename(dst_local_path + dst_file_name,\
		encrypt_key=True, replace=True)
		print("{0} bytes written".format(bytes_written))
		safely_remove_file(dst_local_path + dst_file_name)

		#write error file
		if had_error:
			error_file_name = dst_file_name[:-3] + ".error.gz"
			error_key = Key(error_bucket)
			error_key.key = error_s3_path + error_file_name
			bytes_written = error_key.set_contents_from_filename(dst_local_path + error_file_name,\
			encrypt_key=True, replace=True)
			print("{0} bytes written".format(bytes_written))
			safely_remove_file(dst_local_path + error_file_name)

def clean_line(line):
	"""Strips out the part of a binary line that is not usable"""
	return CLEAN_PATTERN.sub(" ", str(line)[2:-3])

def get_header_dictionaries(some_container, src_file_name, src_local_path):
	"""Pulls the header from an input file and creates the following:
		1.  A dictionary of header names and their positions
		2.  A dictionary of header positions and their names"""
	container = some_container.upper()
	name_translator = {
		"UNIQUE_ACCOUNT_ID" : "UNIQUE_" + container + "_ACCOUNT_ID",
		"UNIQUE_TRANSACTION_ID" : "UNIQUE_" + container + "_TRANSACTION_ID",
		"TYPE" : "TRANSACTION_BASE_TYPE",
		"GOOD_DESCRIPTION" : "MERCHANT_NAME"
	}
	with gzip.open(src_local_path + src_file_name, "rb") as gzipped_input:
		for line in gzipped_input:
			header = clean_line(line)
			header_list = header.split("|")
			header_name_pos, header_pos_name = {}, {}
			counter = 0
			for column in header_list:
				if column in name_translator:
					column = name_translator[column]
				header_name_pos[column] = counter
				header_pos_name[counter] = column
				counter += 1
			return header_name_pos, header_pos_name

def get_map_of_column_positions(header_name_pos, some_container):
	"""Builds a dictionary that maps the input header positions to the output
	header positions.  This dictionary is keyed by the column name.
	Example Key/Value: 'MEM_ID', (0,3)
	A.  The key is the name of the data column
	B.  The value is a tuple of:
		1.  The ordinal of the data column for the OUTPUT
		2.  The ordinal of the data column for the INPUT """
	output_format = get_output_format(some_container)
	map_of_column_positions = {}
	count = 0
	for column in output_format:
		if column in header_name_pos:
			map_of_column_positions[column] = (count, header_name_pos[column])
		else:
			map_of_column_positions[column] = (count, None)
		count += 1
	return map_of_column_positions

def get_output_format(some_container):
	"""Creates an output format based upon a template blended with a container
	name."""
	my_container = some_container.upper()
	output_format = [x.replace("__BLANK", my_container) for x in OUTPUT_FORMAT]
	return output_format

def write_error_file(path, file_name, line, error_msg):
	total_line = error_msg + "\nLine was:\n" + line
	with gzip.open(path + file_name[:-3] + ".error.gz", "ab") as gzipped_output:
		gzipped_output.write(bytes(total_line + "\n", 'UTF-8'))

def process_file(src_file_name, src_local_path, dst_file_name, dst_local_path,\
header_pos_name, map_of_column_positions, container):

	""" Does the following:
		1. Takes a gzipped input file from the local file system
		2. Re-arranges the contents to meet our Meerkat output specification
		3. Stores the result in a gzipped output file which is written to the
		   local file system"""

	had_error = False
	output_format = get_output_format(container)
	blank_result = [""] * len(output_format)
	my_container = container.upper()

	with gzip.open(src_local_path + src_file_name, "rb") as gzipped_input:

		line_count = 0
		line_error_count = 0

		with gzip.open(dst_local_path + dst_file_name, "wb") as gzipped_output:
			first_line = True
			for line in gzipped_input:
				line_error = False
				line_count +=1
				line = clean_line(line)

				#Treat the first line differently, since it is a header
				if first_line:
					first_line = False
					first_line_delimiter_count = len(line.split("|"))
					output_line = "|".join(output_format)
					#Verify that the first line is the header
					if "|GOOD_DESCRIPTION|" not in line:
						gzipped_output.close()
						had_error = True
						write_error_file(dst_local_path, dst_file_name, line, "No header found in source file")
						return
				else:
					split_list = line.split("|")
					result = deepcopy(blank_result)
					count = 0
					for item in split_list:
						try:
							name = header_pos_name[count]
						except:
							#Verify that each line has the correct number of delimiters
							had_error = True
							line_error = True
							line_error_count +=1
							this_line_delimiter_count = len(line.split("|"))
							error_msg = "First Line had " + str(first_line_delimiter_count) + " delimiters.\n"
							error_msg += "This Line had " + str(this_line_delimiter_count) + " delimiters.\n"
							error_msg += "Improperly structured line #" + str(line_count)
							write_error_file(dst_local_path, dst_file_name, line, error_msg)
							break
							#return
						if name in map_of_column_positions:
							position = map_of_column_positions[name][0]
							result[position] = item
						count += 1

					#Turn the output list into a pipe-delimited string
					if line_error:
						continue
						
					output_line = "|".join(result)

					if output_line[0] == "|":
						#Verify the each line begins with a non-pipe
						had_error = True
						line_error = True
						line_error_count += 1
						write_error_file(dst_local_path, dst_file_name, output_line, "Output line was corrupt on line #" + str(line_count))
						continue

				#Encode the line as bytes in UTF-8 and write them to a gzipped file
				output_line = bytes(output_line + "\n", 'UTF-8')
				gzipped_output.write(output_line)
		
		if had_error:
			error_values = [str(line_count), str(line_error_count), str(1.0 * line_error_count / line_count)] 
			error_msg = "Total line count: {}\nTotal error count: {}\n Success Ratio:"
			error_msg = error_msg.format(*error_values)
			write_error_file(dst_local_path, dst_file_name, "", error_msg)

	return had_error

def run_from_command_line(command_line_arguments):
	"""Runs these commands if the module is invoked from the command line"""

	print("Begin")
	begin_processing_loop(sys.argv[1], sys.argv[2])
	print("End")

if __name__ == "__main__":
	run_from_command_line(sys.argv)