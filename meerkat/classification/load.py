#!/usr/local/bin/python3.3

"""This module loads our general classifier and produces a helper function
that will classify a single transaction. Depending on the mode provided
(Bank or Card) this module will load a different previously generated and
pickled SciKit model.

Created on Feb 25, 2014
@author: Matthew Sevrens
"""

from sklearn.externals import joblib

def select_model(mode):
	"""Load either Card or Bank classifier depending on
	requested model"""

	# Switch on Models
	if mode == "card":
		print("--- Classifying Transactions in Card Mode ---")
		model_path = "meerkat/binary_classifier/models/final_card.pkl"
	elif mode == "bank":
		print("--- Classifying Transactions in Bank Mode ---")
		model_path = "meerkat/binary_classifier/models/final_bank.pkl"
	elif mode == "bank_NPMN":
		print("--- Classifying Merchant Name in Non-Physical Bank Mode ---")
		model_path = "meerkat/binary_classifier/models/bank_NPMN_2.pkl"
	elif mode == "sub_transaction_type":
		print("--- Classifying sub transaction type ---")
		model_path = "meerkat/binary_classifier/models/STO_bank_model_99.pkl"
	elif mode == "transaction_type":
		print("--- Classifying transaction type on non spend transactions ---")
		model_path = "meerkat/binary_classifier/models/TO_bank_model_99.pkl"
	else:
		print("--- Binary Classifier requested not found. Terminating ---")
		sys.exit()

	# Load Model
	model = joblib.load(model_path)

	# Generate Helper Function
	def classifier(description):
		result = list(model.predict([description]))[0]
		return result
			
	return classifier

if __name__ == "__main__":
	"""Print a warning to not execute this file as a module"""
	print("This module is a library that contains useful functions; it should not be run from the console.")