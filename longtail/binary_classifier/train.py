'''
Created on Feb 25, 2014

@author: Matt Sevrens
'''

#!/usr/local/bin/python3
# pylint: disable=all

import csv, sys, logging, os

from random import random
from sklearn.cross_validation import train_test_split
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.linear_model import SGDClassifier
from sklearn.grid_search import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.externals import joblib

def split_data(labeled_transactions="data/misc/verifiedLabeledTrans.csv"):

    if not os.path.isfile(labeled_transactions):
        logging.error("Please provide a set of labeled transactions to build the classifier on")

    transactions = []
    labels = []

    # Load Data
    transactions, labels = load_data(transactions, labels, labeled_transactions)

    # Append More
    transactions, labels = load_data(transactions, labels, "data/misc/10K_Card.csv")
    transactions, labels = load_data(transactions, labels, "data/misc/verifiedLabeledTrans.csv")

    # Split into training and testing sets
    if len(transactions) < 100:
        logging.error("Not enough labeled data to create a model from")

    trans_train, trans_test, labels_train, labels_test = train_test_split(transactions, labels, test_size=0.5, random_state=42)

    return trans_train, trans_test, labels_train, labels_test

def load_data(transactions, labels, file_name, test_size=1):

    HL_file = open(file_name, encoding='utf-8', errors="replace")
    human_labeled = list(csv.DictReader(HL_file))
    HL_file.close()

    for i in range(len(human_labeled)):
        if human_labeled[i]["IS_PHYSICAL_TRANSACTION"] != "" and random() < test_size:
            transactions.append(human_labeled[i]["DESCRIPTION"])
            labels.append(human_labeled[i]["IS_PHYSICAL_TRANSACTION"])

    return transactions, labels

def build_model(trans_train, trans_test, labels_train, labels_test):

    pipeline = Pipeline([
        ('vect', CountVectorizer()),
        ('tfidf', TfidfTransformer()),
        ('clf', SGDClassifier())
    ])

    parameters = {
        'vect__max_df': (0.5, 0.75, 1.0),
        'vect__max_features': (500, 750),
        'vect__ngram_range': ((1, 1), (1, 2)),  # unigrams or bigrams
        'tfidf__use_idf': (True, False),
        'tfidf__norm': ('l1', 'l2'),
        'clf__alpha': (0.00001, 0.000001),
        'clf__penalty': ('l2', 'elasticnet'),
        'clf__n_iter': (10, 50, 80)
    }

    grid_search = GridSearchCV(pipeline, parameters, n_jobs=-1, verbose=1)
    grid_search.fit(trans_train, labels_train)
    score = grid_search.score(trans_test, labels_test)

    print("Best score: %0.3f" % grid_search.best_score_)
    print("Best parameters set:")
    best_parameters = grid_search.best_estimator_.get_params()
    for param_name in sorted(parameters.keys()):
        print("\t%s: %r" % (param_name, best_parameters[param_name]))

    print("Actual Score: " + str(score))

    # Save Model
    joblib.dump(grid_search, 'longtail/binary_classifier/US.pkl', compress=3)

    test_model("data/misc/verifiedLabeledTrans.csv", grid_search)
    test_model("data/misc/10K_Card.csv", grid_search)
    test_model("data/misc/10K_Bank.csv", grid_search)

def test_model(file_to_test, model):

    transactions, labels = load_data([], [], file_to_test)
    score = model.score(transactions, labels)

    print(file_to_test, " Score: ", score)

if __name__ == "__main__":

    if len(sys.argv) == 2 and os.path.isfile(sys.argv[1]):
        trans_train, trans_test, labels_train, labels_test = split_data(labeled_transactions=sys.argv[1])
    else:
        trans_train, trans_test, labels_train, labels_test = split_data()

    build_model(trans_train, trans_test, labels_train, labels_test)