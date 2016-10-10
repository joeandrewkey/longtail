import csv
import sys
import logging
import yaml
import json
import queue
import threading
import pandas as pd
import multiprocessing as mp
from elasticsearch import Elasticsearch
from elasticsearch import helpers

logging.config.dictConfig(yaml.load(open('meerkat/logging.yaml', 'r')))
logger = logging.getLogger('tools')

endpoint = 'search-agg-and-factual-aq75mydw7arj5htk3dvasbgx4e.us-west-2.es.amazonaws.com'
host = [{'host': endpoint, 'port': 80}]
index_name, index_type = 'agg_index_20161010', 'agg_type'
es = Elasticsearch(host)

def load_dataframe_into_index(df, **kwargs):
	"""Bulk Load a dataframe into the index"""
	# This ensures that all columns are cast as strings
	for column in df.columns:
		df[column] = df[column].astype('str')

	data = df.to_dict(orient='records')
	# Strip whitespace, which may interfere with a term query
	df.apply(lambda x: x.str.strip(), axis=1)

	actions = []
	offset = kwargs['chunk_count'] * kwargs['chunksize']
	for i in range(len(data)):
		# Removing all NaN values
		for j in list(data[i]):
			if data[i][j] == "nan":
				del data[i][j]
		# creating actions for a bulk load operation
		action = {
			'_index': index_name,
			'_type': index_type,
			'_id': offset + i,
			'_source': data[i]
		}
		actions.append(action)

	# Bulk load the index
	if len(actions) > 0:
		helpers.bulk(es, actions)

def build_index(filename):
	"""This is the main function, which creates the index, type_mapping, and
	then populates the index."""
	if es.indices.exists(index_name):
		logger.warning("Deleting existing index: {}".format(index_name))
		res = es.indices.delete(index=index_name)

	# create an index with a few hints for the type_mapping schema
	not_analyzed_string = { "index": "not_analyzed", "type" : "string"}
	type_mapping = {
		"mappings": {
			index_type: {
				"_source": {
					"enabled" : True
				},
				"properties" : {
					"list_name": not_analyzed_string,
					"city": not_analyzed_string,
					"state": not_analyzed_string
				}
			}
		}
	}
	logger.info("Creating index with type mapping")
	es.indices.create(index=index_name, body=type_mapping)
	logger.info("Index created")

	# set all data types to "str" in the reader, so that nothing is mangled
	reader = pd.read_csv(filename, chunksize=10)
	test_chunk = reader.get_chunk(0)
	dtype = {}
	for column in test_chunk.columns:
		dtype[column] = "str"

	# build the index, one chunk at a time
	chunk_count, chunksize = 0, 10000
	reader = pd.read_csv(filename, chunksize=chunksize, dtype=dtype)
	pool = mp.Pool(mp.cpu_count())

	for chunk in reader:
		chunk_count += 1
		logger.info("Chunk {0}".format(chunk_count))

		kwargs = {"chunk_count": chunk_count, "chunksize": chunksize}
		load_dataframe_into_index(chunk, **kwargs)
		# pool.apply(load_dataframe_into_index, [chunk], kwargs)
		# pool.apply_async(load_dataframe_into_index, [chunk], kwargs)

def build_index_multi_threading(filename):
	"Build index with the threading module"""
	if es.indices.exists(index_name):
		logger.warning("Deleting existing index: {}".format(index_name))
		res = es.indices.delete(index=index_name)

	def worker():
		while True:
			df, kwargs = q.get()
			if df is None: break
			load_dataframe_into_index(df, **kwargs)
			q.task_done()

	q = queue.Queue()
	threads = []
	for i in range(8):
		t = threading.Thread(target=worker)
		t.start()
		threads.append(t)

	chunk_count, chunksize = 0, 10000
	reader = pd.read_csv(filename, chunksize=chunksize)
	for chunk in reader:
		chunk_count += 1
		kwargs = {"chunk_count": chunk_count, "chunksize": chunksize}
		q.put((chunk, kwargs))

	q.join()

	for i in range(8):
		q.put((None, None))
	for t in threads:
		t.join()

if __name__ == '__main__':
	build_index('./selected-lists-5224.csv')
	sys.exit()
	build_index_multi_threading('./selected-lists-5224.csv')
