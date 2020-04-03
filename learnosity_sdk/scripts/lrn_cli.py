#!/usr/bin/env python

import click
import logging
import json
import sys

from requests import Response
from learnosity_sdk.request import DataApi


DEFAULT_API_DATA_HOST = 'https://data.learnosity.com'
DEFAULT_API_DATA_VERSION = 'v1'


# TODO: use credentials from environment/file
@click.group()
@click.option('--consumer-key', '-k',
              help='API key for desired consumer',
              default='yis0TYCu7U9V4o7M')
# This is a public Learnosity Demos consumer
# XXX: never commit any other secret anywhere!
@click.option('--consumer-secret', '-S',
              help='Secret associated with the consumer key',
              default='74c5fd430cf1242a527f6223aebd42d30464be22')
@click.option('--request-json', '-R', 'request_json',
              help='JSON body of the request to send,',
              default=None)
@click.option('--file', '-f', type=click.File('r'),
              help='File containing the JSON request',
              default='-')
@click.option('--dump-meta', '-m', is_flag=True, default = False,
              help='output meta object to stderr')
@click.option('--log-level', '-l', default='info',
              help='log level')
@click.option('--requests-log-level', '-L', default='warning',
              help='log level for the HTTP requests')
@click.pass_context
def cli(ctx, consumer_key, consumer_secret,
        file, request_json=None,
        dump_meta = False,
        log_level='info',
        requests_log_level='warning',
        ):
    ''' Prepare and send request to Learnosity APIs '''
    ctx.ensure_object(dict)
    ctx.obj['consumer_key'] = consumer_key
    ctx.obj['consumer_secret'] = consumer_secret
    ctx.obj['file'] = file
    ctx.obj['request_json'] = request_json
    ctx.obj['dump_meta'] = dump_meta

    logging.basicConfig(
        format='%(asctime)s %(levelname)s:%(message)s',
        level=log_level.upper())

    requests_logger = logging.getLogger('urllib3')
    requests_logger.setLevel(requests_log_level.upper())
    requests_logger.propagate = True

    logger = logging.getLogger()
    ctx.obj['logger'] = logger


@cli.command()
@click.argument('endpoint_url')
@click.option('--reference', '-r', 'references',
              help='`reference` to request (can be used multiple times',
              multiple=True)
@click.option('--set', '-s', 'do_set', is_flag=True, default=False,
              help='Send a SET request')
@click.option('--recurse', '-R', 'do_recurse', is_flag=True, default=False,
              help='Automatically recurse using the next token')
@click.option('--update', '-u', 'do_update', is_flag=True, default=False,
              help='Send an UPDATE request')
@click.pass_context
def data(ctx, endpoint_url, references=None,
         do_set=False, do_update=False, do_recurse=False):
    ''' Make a request to Data API.

    The endpoint_url can be:

    - a full URL: https://data.learnosity.com/v1/itembank/items

    - a REST path, with or without version:

      - /v1/itembank/items

      - /itembank/items

    '''
    ctx.ensure_object(dict)
    logger = ctx.obj['logger']
    consumer_key = ctx.obj['consumer_key']
    consumer_secret = ctx.obj['consumer_secret']
    file = ctx.obj['file']
    request_json = ctx.obj['request_json']
    dump_meta = ctx.obj['dump_meta']

    # TODO: factor this out into a separate function
    if not endpoint_url.startswith('http'):
        if not endpoint_url.startswith('/'):  # Prepend leading / if missing
            endpoint_url = '/' + endpoint_url
        if not endpoint_url.startswith('/v'):  # API version
            endpoint_url = '/' + DEFAULT_API_DATA_VERSION + endpoint_url
        endpoint_url = DEFAULT_API_DATA_HOST + endpoint_url

    if request_json is not None:
        logger.debug(f'Using request JSON from command line argument')
        data_request = json.loads(request_json)
    else:
        if file.isatty():
            # Make sure the user is aware they need to enter something
            logger.info(f'Reading request json from {file}...')
        else:
            logger.debug(f'Reading request json from {file}...')
        data_request = json.load(file)

    action = 'get'
    if do_set:
        action = 'set'

    if do_update:
        # XXX: Mutually exclusive options, This would be better implemented at the Click level
        if action == 'get':
            action = 'update'
        else:
            logger.error('Options --set and --update are mutually exclusive')
            exit(1)

    if len(references) > 0:
        if 'references' in data_request:
            logger.warning('Overriding `references` from request with references from the command line')
        data_request['references'] = references

    logger.debug('Sending %s request to %s ...' %
                 (action.upper(), endpoint_url))
    try:
        r = _get_data(endpoint_url, consumer_key, consumer_secret, data_request, action,
                      logger, do_recurse)
    except Exception as e:
        logger.error('Exception sending request to %s: %s' %
                     (endpoint_url, e))
        return False

    try:
        response = _decode_response(r, logger, dump_meta)
    except Exception as e:
        logger.error('Exception decoding response: %s\nResponse text: %s' % (e, r.text))
        return False

    if not response['meta']['status']:
        logger.error('Incorrect status for request to %s: %s' %
                     (endpoint_url, response['meta']['message']))
        return False

    data = response['data']

    print(json.dumps(data, indent=True))
    return True

def _get_data(endpoint_url, consumer_key, consumer_secret, request, action, logger,
              do_recurse=False):
    data_api = DataApi()

    security = _make_data_security_packet(consumer_key, consumer_secret)

    if not do_recurse:
        r = data_api.request(endpoint_url, security, consumer_secret, request, action)
    else:
        meta = {
            '_comment': 'fake meta recreated by lrn-cli for failing initial recursive request',
            'status': 'false',
        }
        data = None
        logger.debug('Iterating through pages of data...')
        for r_iter in data_api.request_iter(endpoint_url, security, consumer_secret, request, action):
            meta = r_iter['meta']
            new_data = r_iter['data']
            if data is None:
                data = new_data
            elif type(data) is list:
                data += new_data
            elif type(data) is dict:
                data.update(new_data)
            else:
                raise Exception('Unexpected retun data type: not list or dict')
            logger.debug(f'Got {len(new_data)} new objects')
        meta['records'] = len(data)
        r = {
            'meta': meta,
            'data': data,
        }

    return r


def _make_data_security_packet(consumer_key, consumer_secret,
                               domain='localhost'):
    return {
        'consumer_key': consumer_key,
        'domain': domain,
    }


def _decode_response(response, logger, dump_meta=False):
    if type(response) == Response:
        if response.status_code != 200:
            logger.error('Error %d sending request to %s: %s' %
                         # TODO: try to extract an error message from r.json()
                         (response.status_code, response.url, response.text))
        response = response.json()
    if dump_meta and response['meta']:
        sys.stderr.write(json.dumps(response['meta'], indent=True) + '\n')
    return response
