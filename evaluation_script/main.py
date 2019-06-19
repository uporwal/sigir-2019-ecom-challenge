from .utils import get_file_extension
from .utils import open_file
from .utils import BaseMetrics
from .utils import Metrics

query_level_base_metrics = {}
"""This dictionary holds the base metrics for each query. Counts of true positives,
false positives, etc. The query id is the key, a BaseMetrics object is the value.
Only queries having at least one judged document are included in the dictionary.
"""

query_level_metrics = {}
"""This dictionary holds the scoring metrics for each query. Precision, recall, etc.
These are calculated from the metrics stored in the query_level_base_metrics dictionary.
Only queries having at least one judged document are included in the dictionary.
"""

documents_with_ground_truth = set()
"""This set contains all the document ids that have one or more judgements. This is used
to speed up scoring a prediction file.
"""

def calculate_query_level_metrics():
    """Calculates query level metrics from query level base metrics.

    Query level metrics include recall, precision, and similar metrics. These are
    calculated on a per-query basis and stored in the query_level_metrics dicitionary.
    A set of metrics of averaged across all queries is calculated and returned. 

    Base metrics includes counts like true positives, false positives, etc. These are
    calculated while walking the prediction.
    
    Notes:
    * Since, we checked the length of the query_level_base_metrics.keys() in the begining
      we will never get all base metrics as zero. Also, because of this check we dont need
      to worry about total_queries being zero in the division.
    """
    
    qa_precision = 0
    qa_recall = 0
    qa_fpr = 0
    qa_accuracy = 0
    qa_f1 = 0
    total_queries = len(query_level_base_metrics.keys())

    for query_id in query_level_base_metrics:
        base_metrics = query_level_base_metrics[query_id]
        query_level_metrics[query_id].precision = base_metrics.calculate_precision()
        query_level_metrics[query_id].recall = base_metrics.calculate_recall()
        query_level_metrics[query_id].fpr = base_metrics.calculate_fpr()
        query_level_metrics[query_id].accuracy = base_metrics.calculate_accuracy()
        query_level_metrics[query_id].f1 = base_metrics.calculate_f1()

    for query_id in query_level_base_metrics:
        qa_precision = qa_precision + query_level_metrics[query_id].precision
        qa_recall = qa_recall + query_level_metrics[query_id].recall
        qa_fpr = qa_fpr + query_level_metrics[query_id].fpr
        qa_accuracy = qa_accuracy + query_level_metrics[query_id].accuracy
        qa_f1 = qa_f1 + query_level_metrics[query_id].f1

    qa_precision = float(qa_precision) / total_queries
    qa_recall = float(qa_recall) / total_queries
    qa_fpr = float(qa_fpr) / total_queries
    qa_accuracy = float(qa_accuracy) / total_queries
    qa_f1 = float(qa_f1) / total_queries

    return (qa_precision, qa_recall, qa_fpr, qa_accuracy, qa_f1)

def populate_index_map(infile):
    """Reads the first line (header line) of a ground truth or prediction file and
    creates a mapping from the column index positions to the query-id in the header.
    The first column is not a query-id and is not included. For example, the map 
    might be {1:query_id_1, 2:query_id_2, 3:query_id_3}. The map is returned.

    Note that ground truth and prediction files commonly have query-id identical to
    to column index. However, this is not required.
    """
    
    index_map = {}
    with open_file(infile) as f:
        for line in f:
            line = line.strip("\n")
            arr = line.split("\t")
            for i in range(1, len(arr)):
                index_map[i] = arr[i]
            break
    return index_map

def calculate_base_metrics(infile, truth):
    """Processes a prediction file and calculates base metrics.

    Each query-document pair in the prediction file is examined one-at-a-time. Each
    prediction is compared to the value in the ground truth dictionary generated by
    populate_ground_truth.

    Base metrics are counts of true positives, false positives, etc. Metrics are
    computed both globaly and per-query. Per-query metrics are stored in the
    query_level_base_metrics dictionary. Aggregate metrics are returned in a tuple.

    Note: This skips the first line (header).
    """
    global_base_metrics = BaseMetrics()
    predicted_keys = set()
    """ predicted_keys serves dual purpose.
    1. Prevents the case where a (query_id, doc_id) pair is present multiple times.
    2. Helps us penalize those (query_id, doc_id) pairs that are present in ground truth
       but are absent in the prediction file (unlikely though) 
    """
    index = populate_index_map(infile)
    with open_file(infile) as f:
        next(f)
        for line in f:
            line = line.strip("\n")
            arr = line.split("\t")
            length = len(arr)
            doc_id = arr[0]
            if doc_id in documents_with_ground_truth:
                for i in range(1, length):
                    query_id = index[i]
                    
                    # We dont need toi check if the query_id is in the query_level_base_metrics
                    # as (query_id, doc_id) in truth will take care of that.
                    if (query_id, doc_id) in truth:
                        if (query_id, doc_id) not in predicted_keys:
                            predicted_keys.add((query_id, doc_id))
                            if truth[(query_id, doc_id)] == arr[i]:
                                if arr[i] == '1':
                                    global_base_metrics.add_tp(1)
                                    query_level_base_metrics[query_id].add_tp(1)
                                else:
                                    global_base_metrics.add_tn(1)
                                    query_level_base_metrics[query_id].add_tn(1)
                            else:
                                if truth[(query_id, doc_id)] == '1':
                                    global_base_metrics.add_fn(1)
                                    query_level_base_metrics[query_id].add_fn(1)
                                else:
                                    global_base_metrics.add_fp(1)
                                    query_level_base_metrics[query_id].add_fp(1)

    # An unlikely case where (query_id, doc_id) pairs are present in 
    # the groung truth but are absent in the prediction file
    for (query_id, doc_id) in truth.keys():
        if (query_id, doc_id) not in predicted_keys:
            if truth[(query_id, doc_id)] == '1':
                # Assume that prediction is -1
                global_base_metrics.add_fn(1)
                query_level_base_metrics[query_id].add_fn(1)
            else:
                # Assume that prediction is 1
                global_base_metrics.add_fp(1)
                query_level_base_metrics[query_id].add_fp(1)

    return global_base_metrics

def populate_ground_truth(infile):
    """Processes the ground truth file.

    A dictionary of every query-document pair having a judgement is returned. A query-document
    is considered to have a judgment if the entry in the ground truth file is non-zero.

    The key for the map is (query_id,doc_id) and value is the prediction, typically 1 or -1,
    though any non-zero value is retained.

    This routine also initializes the query_level_base_metrics and query_level_metrics
    dictionaries with an entry for each query having at least one judgement.

    Note: This skips the first line of a ground truth file (header).
    """
    index = populate_index_map(infile)
    results = {}
    with open_file(infile) as f:
        next(f)
        for line in f:
            line = line.strip("\n")
            arr = line.split("\t")
            length = len(arr)
            doc_id = arr[0]
            for i in range(1, length):
                if arr[i] != '0':
                    documents_with_ground_truth.add(doc_id)
                    query_id = index[i]
                    results[(query_id, doc_id)] = arr[i]

                    # We should only include queries where there is any judgement for
                    # calculating (base) metrics. Exclude queries with no judgements.
                    if query_id not in query_level_base_metrics:
                        query_level_base_metrics[query_id] = BaseMetrics()
                        query_level_metrics[query_id] = Metrics()
    return results

def evaluate(test_annotation_file, user_submission_file, phase_codename, **kwargs):
    """
    Evaluates the submission for a particular challenge phase adn returns score
    Arguments:

        `test_annotations_file`: Path to test_annotation_file on the server
        `user_submission_file`: Path to file submitted by the user
        `phase_codename`: Phase to which submission is made

        `**kwargs`: keyword arguments that contains additional submission
        metadata that challenge hosts can use to send slack notification.
        You can access the submission metadata
        with kwargs['submission_metadata']

        Example: A sample submission metadata can be accessed like this:
        >>> print(kwargs['submission_metadata'])
        {
            'status': u'running',
            'when_made_public': None,
            'participant_team': 5,
            'input_file': 'https://abc.xyz/path/to/submission/file.json',
            'execution_time': u'123',
            'publication_url': u'ABC',
            'challenge_phase': 1,
            'created_by': u'ABC',
            'stdout_file': 'https://abc.xyz/path/to/stdout/file.json',
            'method_name': u'Test',
            'stderr_file': 'https://abc.xyz/path/to/stderr/file.json',
            'participant_team_name': u'Test Team',
            'project_url': u'http://foo.bar',
            'method_description': u'ABC',
            'is_public': False,
            'submission_result_file': 'https://abc.xyz/path/result/file.json',
            'id': 123,
            'submitted_at': u'2017-03-20T19:22:03.880652Z'
        }
    """
    
    print("Starting Evaluation.....")
    query_level_base_metrics.clear()
    query_level_metrics.clear()
    documents_with_ground_truth.clear()
    output = {}
    precision = 0
    recall = 0
    fpr = 0
    f1 = 0
    qa_precision = 0
    qa_recall = 0
    qa_fpr = 0
    qa_f1 = 0

    if phase_codename == "unsupervised" or phase_codename == "supervised" or phase_codename == "final":
        print("evaluating for " +phase_codename+ " phase")
        truth = populate_ground_truth(test_annotation_file)

        # We populate query_level_base_metrics with queries with any judgements as keys.
        # This will be zero if ground truth file is all empty or no queries are judged.
        # Note that this test prevents all base metrics to be zero after calculate_base_metrics().
        
        if len(query_level_base_metrics.keys()) > 0:
            extension = get_file_extension(user_submission_file)
            if extension == "tsv" or extension == "gz": 
                global_base_metrics = calculate_base_metrics(user_submission_file, truth)
                precision = global_base_metrics.calculate_precision()
                recall = global_base_metrics.calculate_recall()
                fpr = global_base_metrics.calculate_fpr()
                accuracy = global_base_metrics.calculate_accuracy()
                f1 = global_base_metrics.calculate_f1()
                (qa_precision, qa_recall, qa_fpr, qa_accuracy, qa_f1) = calculate_query_level_metrics()
 
        print("completed evaluation for " +phase_codename + " phase")
    output["result"] = [
        {
            "data": {
                "global_precision": precision,
                "global_recall": recall,
                "global_f1": f1,
                "global_tpr": recall,
                "global_fpr": fpr,
                "global_accuracy": accuracy,
                "average_precision": qa_precision,
                "average_recall": qa_recall,
                "average_f1": qa_f1,
                "average_tpr": qa_recall,
                "average_fpr": qa_fpr,
                "average_accuracy": qa_accuracy
            }
        }
    ]
    output["submission_result"] = output["result"][0]["data"]
    return output
