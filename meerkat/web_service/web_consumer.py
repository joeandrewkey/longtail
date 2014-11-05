#!/usr/local/bin/python3.3

"""This module enriches transactions with additional
data found by Meerkat

Created on Nov 3, 2014
@author: Matthew Sevrens
"""

import json

from pprint import pprint
from scipy.stats.mstats import zscore

from meerkat.various_tools import get_es_connection, string_cleanse, get_boosted_fields
from meerkat.various_tools import synonyms, get_bool_query, get_qs_query
from meerkat.binary_classifier.load import select_model

BANK_CLASSIFIER = select_model("bank")
CARD_CLASSIFIER = select_model("card")

class Web_Consumer():
	"""Acts as a web service client to process and enrich
	transactions in real time"""

	def __init__(self, params, hyperparams, cities):
		"""Constructor"""

		self.params = params
		self.hyperparams = hyperparams
		self.cities = cities
		self.es = get_es_connection(params)

	def __get_query(self, transaction):
		"""Create an optimized query"""

		result_size = self.hyperparams.get("es_result_size", "10")
		fields = self.params["output"]["results"]["fields"]
		transaction = string_cleanse(transaction["description"]).rstrip()

		# Input transaction must not be empty
		if len(transaction) <= 2 and re.match('^[a-zA-Z0-9_]+$', transaction):
			return

		# Replace synonyms
		transaction = synonyms(transaction)
		transaction = string_cleanse(transaction)

		# Construct Optimized Query
		o_query = get_bool_query(size=result_size)
		o_query["fields"] = fields
		should_clauses = o_query["query"]["bool"]["should"]
		field_boosts = get_boosted_fields(self.hyperparams, "standard_fields")
		simple_query = get_qs_query(transaction, field_boosts)
		should_clauses.append(simple_query)

		return o_query

	def __search_index(self, query):
		"""Search against a structured index"""

		index = self.params["elasticsearch"]["index"]

		try:
			results = self.es.search(index=index, body=query)
		except Exception:
			results = {"hits":{"total":0}}

		return results

	def __z_score_delta(self, scores):
		"""Find the Z-Score Delta"""

		if len(scores) < 2:
			return None

		z_scores = zscore(scores)
		first_score, second_score = z_scores[0:2]
		z_score_delta = round(first_score - second_score, 3)

		return z_score_delta

	def __process_results(self, results, transaction):
		"""Process search results and enrich transaction
		with found data"""

		params = self.params
		hyperparams = self.hyperparams
		field_names = params["output"]["results"]["fields"]

		# Must be at least one result
		if results["hits"]["total"] == 0:
			for field in field_names:
				transaction[field] = ""

			return transaction

		# Collect Necessary Information
		hits = results['hits']['hits']
		top_hit = hits[0]
		hit_fields = top_hit.get("fields", "")
		
		# If no results return
		if hit_fields == "":
			return transaction

		# Collect Fallback Data
		business_names = [result.get("fields", {"name" : ""}).get("name", "") for result in hits]
		business_names = [name[0] for name in business_names if type(name) == list]
		city_names = [result.get("fields", {"locality" : ""}).get("locality", "") for result in hits]
		city_names = [name[0] for name in city_names if type(name) == list]
		state_names = [result.get("fields", {"region" : ""}).get("region", "") for result in hits]
		state_names = [name[0] for name in state_names if type(name) == list]

		# Need Names
		if len(business_names) < 2:
			return transaction

		# City Names Cause issues
		if business_names[0] in self.cities:
			return transaction

		# Collect Relevancy Scores
		scores = [hit["_score"] for hit in hits]
		z_score_delta = self.__z_score_delta(scores)
		threshold = float(hyperparams.get("z_score_threshold", "2"))
		decision = True if (z_score_delta > threshold) else False

		# Enrich Data if Passes Boundary
		args = [decision, transaction, hit_fields, z_score_delta, business_names, city_names, state_names]
		enriched_transaction = self.__enrich_transaction(*args)

		return enriched_transaction

	def __enrich_transaction(self, decision, transaction, hit_fields, z_score_delta, business_names, city_names, state_names):
		"""Enriches the transaction with additional data"""

		params = self.params
		field_names = params["output"]["results"]["fields"]
		fields_in_hit = [field for field in hit_fields]
		
		# Collect Mapping Details
		fields = params["output"]["results"]["fields"]
		labels = params["output"]["results"]["labels"]
		attr_map = dict(zip(fields, labels))

		# Enrich with found data
		if decision == True:
			for field in field_names:
				if field in fields_in_hit:
					field_content = hit_fields[field][0] if isinstance(hit_fields[field], (list)) else str(hit_fields[field])
					transaction[attr_map.get(field, field)] = field_content
				else:
					transaction[attr_map.get(field, field)] = ""

		# Add Business Name, City and State as a fallback
		if decision == False:
			for field in field_names:
				transaction[attr_map.get(field, field)] = ""
			transaction = self.__business_name_fallback(business_names, transaction, attr_map)
			transaction = self.__geo_fallback(city_names, state_names, transaction, attr_map)

		# Ensure Proper Casing
		if transaction[attr_map['name']] == transaction[attr_map['name']].upper():
			transaction[attr_map['name']] = string.capwords(transaction[attr_map['name']], " ")

		# Add Source
		index = params["elasticsearch"]["index"]
		transaction["source"] = "FACTUAL" if ("factual" in index) else "OTHER"

		return transaction

	def __geo_fallback(self, city_names, state_names, transaction, attr_map):
		"""Basic logic to obtain a fallback for city and state
		when no factual_id is found"""

		fields = self.params["output"]["results"]["fields"]
		city_names = city_names[0:2]
		state_names = state_names[0:2]
		states_equal = state_names.count(state_names[0]) == len(state_names)
		city_in_transaction = (city_names[0].lower() in transaction["description"].lower())
		state_in_transaction = (state_names[0].lower() in transaction["description"].lower())

		if (city_in_transaction):
			transaction[attr_map['locality']] = city_names[0]

		if (states_equal and state_in_transaction):
			transaction[attr_map['region']] = state_names[0]

		return transaction

	def __business_name_fallback(self, business_names, transaction, attr_map):
		"""Basic logic to obtain a fallback for business name
		when no factual_id is found"""
		
		fields = self.params["output"]["results"]["fields"]
		business_names = business_names[0:2]
		top_name = business_names[0].lower()
		all_equal = business_names.count(business_names[0]) == len(business_names)
		not_a_city = top_name not in self.cities

		if (all_equal and not_a_city):
			transaction[attr_map['name']] = business_names[0]

		return transaction

	def ensure_output_schema(self, physical, non_physical):
		"""Clean output to proper schema"""

		# Add or Modify Fields
		for trans in non_physical:
			trans["category"] = ""

		for trans in physical:
			trans["category_label"] = json.loads(trans["category_label"])[0]

		# Combine Transactions
		transactions = physical + non_physical

		# Strip Fields
		for trans in transactions:
			del trans["description"]
			del trans["amount"]
			del trans["date"]

		return transactions

	def __enrich_physical(self, transactions):
		"""Enrich physical transactions with Meerkat"""

		enriched = []

		for trans in transactions:
			query =  self.__get_query(trans)
			results = self.__search_index(query)
			trans_plus = self.__process_results(results, trans)
			enriched.append(trans_plus)

		return enriched

	def __sws(self, transactions):
		"""Split transactions into physical and non-physical"""

		physical, non_physical = [], []

		# Determine Whether to Search
		for trans in transactions:
			label = BANK_CLASSIFIER(trans["description"])
			trans["is_physical_merchant"] = True if (label == "1") else False
			(non_physical, physical)[label == "1"].append(trans)

		return physical, non_physical

	def classify(self, data):
		"""Classify a set of transactions"""

		physical, non_physical = self.__sws(data["transaction_list"])
		physical = self.__enrich_physical(physical)
		transactions = self.ensure_output_schema(physical, non_physical)
		data["transaction_list"] = transactions

		return data

if __name__ == "__main__":
	"""Print a warning to not execute this file as a module"""
	print("This module is a Class; it should not be run from the console.")