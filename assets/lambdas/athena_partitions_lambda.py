import os
import re

import boto3
import datetime

from lambdas.utils import wait_for_athena_query_completion

PARTITION_REGEX = '(\d{4}/\d{2}/\d{2})'


def extract_partition_path(file_key):
    firehose_data_key = os.environ['FIREHOSE_DATA_PREFIX']
    pattern = os.path.join(firehose_data_key, PARTITION_REGEX)
    match = re.search(pattern, file_key)
    if match is None:
        raise ValueError(
            'Invalid Firehose data key {} not matched on pattern {} with key {}'.format(
                firehose_data_key,
                pattern,
                file_key
            )
        )
    return match.group(1)


def make_query(partition_path, partition_name):
    partition_location = os.path.join(
        's3://',
        os.environ['FIREHOSE_DATA_BUCKET_NAME'],
        os.environ['FIREHOSE_DATA_PREFIX'],
        partition_path
    )
    return "ALTER TABLE {}.{} ADD IF NOT EXISTS PARTITION ({}='{}') LOCATION '{}'".format(
        os.environ['ATHENA_DATABASE_NAME'],
        os.environ['ATHENA_TABLE_NAME'],
        os.environ['ATHENA_TABLE_PARTITION_KEY_NAME'],
        partition_name,
        partition_location
    )


def make_output_location():
    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    output_file_name = 'alter-partitions-{}'.format(timestamp)
    return os.path.join(os.environ['ATHENA_QUERY_RESULT_LOCATION_DIR'], output_file_name)


def register_partition(partition_path, partition_name):
    client = boto3.client('athena')
    query = make_query(partition_path, partition_name)
    output_location = make_output_location()
    query_config = dict(
        QueryString=query,
        ResultConfiguration={
            'OutputLocation': output_location
        }
    )
    response = client.start_query_execution(**query_config)
    query_execution_id = response['QueryExecutionId']
    wait_for_athena_query_completion(client, query_execution_id)


def is_partition_registered(partition_path):
    firehose_data_prefix = os.environ['FIREHOSE_DATA_PREFIX']
    partition_key = os.path.join(firehose_data_prefix, partition_path)
    s3_resource = boto3.resource('s3')
    data_bucket = s3_resource.Bucket(os.environ['FIREHOSE_DATA_BUCKET_NAME'])
    return len(list(data_bucket.objects.filter(Prefix=partition_key).limit(2))) == 2


def lambda_handler(event, context):
    file_key = event['Records'][0]['s3']['object']['key']
    partition_path = extract_partition_path(file_key)
    partition_name = partition_path.replace('/', '-')
    if not is_partition_registered(partition_path):
        print('Registering partition {}'.format(partition_name))
        register_partition(partition_path, partition_name)
