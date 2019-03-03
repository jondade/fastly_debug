"""fastly_debug.py

Module for the fetching of fastly debug data. Performs diagnostic functions
and generates an encoded JSON blob for debugging.

If using a machine with a GUI browser such as Firefox, Chrome etc are better
candidates and supported by Fastly.

Example:
    $ python fastly_debug
"""

import argparse
import base64
import json
import os
import uuid
import re
import socket
import sys
import time
import requests

VERSION = '0.1.0'

def fetcher(hostname, url, debug=False, method='GET'):
    """Grabs https content for other methods

    Args:
        url (str): URL path to be requested.
        hostname (str): the hostname to connect to.
        method (str): HTTP method to use.
        debug (bool): whether to output debug information

    Return:
        HTTPResponse: The repsonse object
    """

    headers = {'User-agent': 'Fastly-Debug-CLI '+VERSION, 'accept-language': 'en-US'}

    url = 'https://' + hostname + url
    response = requests.request(method, url, headers=headers)
    # Handle debugging output
    if debug:
        print('Host:' + hostname, file=sys.stderr)
        print('Status: ' + str(response.status_code), file=sys.stderr)
        for name, value in response.headers.items():
            print(name + ': ' + value, file=sys.stderr)

    return response

def json_fetcher(hostname, url, debug=False, method='GET'):
    """Grabs and parses the json data for other functions

    Args:
        url (str): URL path to be requested.
        hostname (str): the hostname to connect to.
        method (str): HTTP method to use.
        debug (bool): whether to output debug information

    Return:
        json: The parsed repsonse object
    """
    info = fetcher(hostname, url, debug, method)
    #data = json.loads(info.read().decode())
    data = json.loads(info.text)


    # Set the resolver data to an empty string if not an OK response
    if info.status_code != 200:
        data = '{}'
    return data

def fetch_resolver(client_id=uuid.uuid4(), debug=False):
    """Grabs the dns resolver information from the Fastly API endpoint

    Returns:
        json: the data about the client's resolver from Fastly's view
    """
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    url = '/debug_resolver'
    hostname = str(client_id) + ".u.fastly-analytics.com"
    fetched = fetcher(hostname, url, debug)
    fetched_data = json.loads(fetched.text)
    json_data = {}
    # Resolver data
    json_data['resolver_ip'] = fetched_data['dns_resolver_info']['ip']
    json_data['resolver_as_name'] = fetched_data['dns_resolver_info']['as_name']
    json_data['resolver_as_number'] = fetched_data['dns_resolver_info']['as_number']
    json_data['resolver_country_code'] = fetched_data['dns_resolver_info']['cc']

    # Client info
    json_data['client_ip'] = fetched_data['client_ip_info']['ip']
    json_data['client_as_name'] = fetched_data['client_ip_info']['as_name']
    json_data['client_as_number'] = fetched_data['client_ip_info']['as_number']
    json_data['client_ip'] = fetched_data['client_ip_info']['ip']

    # Request info
    json_data['time'] = timestamp
    json_data['host'] = 'www.fastly-debug.com'
    json_data['accept'] = fetched.request.headers['accept']
    json_data['user-agent'] = fetched.request.headers['user-agent']
    json_data['acceptlanguage'] = fetched.request.headers['accept-language']
    json_data['acceptencoding'] = fetched.request.headers['accept-encoding']
    json_data['fastlyserverip'] = socket.gethostbyname('www.fastly-debug.com')
    # Fetch a copy of www.fastly-debug.com/ to find the last few details
    fst_dbg = fetcher('www.fastly-debug.com', '/', debug)
    json_data['xff'] = find_xff(fst_dbg)
    json_data['datacenter'] = find_datacenter(fst_dbg)
    json_data['bandwidth_mbps'] = fetch_bandwidth(client_id)

    #Fetch the TCP information json
    fst_tcp_info = json_fetcher('www.fastly-debug.com', '/tcpinfo')
    json_data['cwnd'] = fst_tcp_info['cwnd']
    json_data['nexthop'] = fst_tcp_info['nexthop']
    json_data['rtt'] = fst_tcp_info['rtt'] / 1000
    json_data['delta_retrans'] = fst_tcp_info['delta_retrans']
    json_data['total_retrans'] = fst_tcp_info['total_retrans']

    if debug:
        print(json_data)
    return json_data

def fetch_bandwidth(client_id=uuid.uuid4()):
    """Times retrieving a specific object to work out the approximate
    bandwidth to the server.

    Returns:
        float: the (estimated) bandwidth in bps for the request
    """
    timer_data = {}
    # Time a 204 to get the overhead
    timer_set('204_start', timer_data)
    response = requests.get("https://" + client_id + ".u.fastly-analytics.com/generate_204",
                            hooks={'response':timer_set('204_response', timer_data)})
    timer_set('204_end', timer_data)
    # Now get the timings for some data
    timer_set('start', timer_data)
    response = requests.get("https://www.fastly-debug.com/speedtest",
                            hooks={'response':timer_set('response', timer_data)})
    timer_set('end', timer_data)
    # Lets calculate timing difference
    time_taken_204 = timer_data['204_end'] - timer_data['204_start']
    time_taken_200 = timer_data['end'] - timer_data['start']
    time_taken = time_taken_200 - time_taken_204
    if time_taken_200 <= time_taken_204:
        time_taken = time_taken_200
    size = int(response.headers['Content-length']) * 8
    #time_taken = timer_data['end'] - timer_data['response']
    bandwidth = (size / time_taken) / 1000000
    return bandwidth

def fetch_perfmap(client_id=uuid.uuid4(), debug=False):
    """Grabs the perfmap information from the Fastly API endpoint

    Returns:
        json: the data to use for remaining perf data collection
    """
    url = '/perfmapconfig.js?jsonp=FASTLY.setupPerfmap'
    hostname = str(client_id) + "-perfmap.u.fastly-analytics.com"
    #res = fetcher(hostname, url, debug).read().decode()
    res = fetcher(hostname, url, debug).text
    data = str(res[25:-2]).replace('\'', '\"')
    info = json.loads(data)
    if debug:
        print(data)
    return info

def fetch_pops(hosts, client_id=uuid.uuid4(), debug=False):
    """Retrieves the Point of Presence name for different address resolution methods.

    Arguments:
        hosts (dict): Containing a hostname and and a type key to look up.
        client_id: (str): A unique identifier to ensure no caching of DNS.
    Returns:
        dict: list of types and their associated Point of Presence
    """
    pop_assignments = dict()
    for host in hosts:
        res = fetcher(host['hostname'], "/popname.js?jsonp=fastly.setPopName&unique="
                      + str(client_id), debug).text
        data = str(res[23:-7]).replace('\'', '\"')
        info = json.loads(data)
        pop_assignments[host['type']] = info['popname']
        if debug:
            print(data)
    return pop_assignments

def fetch_latencies(hosts, client_id=uuid.uuid4(), debug=False):
    """Tests the latency to a provided list of PoPs and returns them

    Arguments:
        hosts (dict): a list of hosts and PoP identifiers
        client_id (str): a unique identifier
        debug (boolean): flag to output debug information
    """
    latencies = dict()
    for host in hosts:
        timer_data = dict()
        url = "https://" + host['hostname'] + "/testobject.svg?unique="
        url = url + client_id + "-perfmap&popId=" + host['popId']
        timer_set("start", timer_data)
        requests.get(url, hooks={'response':timer_set('response', timer_data)})
        timer_set('end', timer_data)
        if debug:
            print("PoP: " + host['popId'])
            print("Time Total: %f"% (timer_data['end'] - timer_data['start']))
            print("Time start-response: %f"% (timer_data['response'] - timer_data['start']))
            print("Time response-end: %f"% (timer_data['end'] - timer_data['response']))
        timer_value = int((timer_data['end'] - timer_data['response']) * 100)
        latencies[host['popId']] = timer_value
    return latencies

def find_xff(response):
    """Grabs just the XFF data from the page

    Returns:
        string: the body of the xff table cell
    """
    data = response.text
    value = re.search(r'xff">([^<]*)', data, re.MULTILINE)
    return value.group(1)

def find_datacenter(response):
    """Grabs the X-Served-By header and pulls the last three characters
    as the datacenter

    Returns:
        string: the datacenter identification code
    """
    xsb = response.headers['X-Served-By']
    return xsb[len(xsb) - 3: len(xsb)]

def timer_set(reference_name, timer_dict):
    """Adds or replaces a timer key/value in a dictionary

    Arguments:
        reference_name (str): name for the key to use
        timer_dict (dict): the dictionary to insert the timer value into.
    """
    timer_dict[reference_name] = time.time()
    return

def send_out(data="{}", quiet=True, out_file=None):
    """Handler for outputing data.

    Arguments:
        data (str): string of data to output

    """
    if not quiet:
        print(data)
        print(os.linesep)

    if out_file is not None:
        out_file = open(out_file, 'w')
    elif sys.stdout.isatty():
        out_file = sys.stdout

    if out_file is not None:
        out_file.write(base64.urlsafe_b64encode(str.encode(data)).decode())
        out_file.write(os.linesep)
        out_file.close()

def _parse_args():
    """
    Handles the arguments from the command line
    """
    parser = argparse.ArgumentParser(prog='fastly_debug')
    parser.add_argument('-D', '--debug', help='Turn on debugging information.', action='store_true')
    parser.add_argument('-o', '--out', help='Filename to write the output into.')
    parser.add_argument('-q', '--quiet', help='Do not display the data to be encoded',
                        action='store_true')
    parser.add_argument('-v', '--version', help='Display version information.',
                        action='version', version="%(prog)s "+VERSION)
    args = parser.parse_args()
    return args

def _main():
    # Set some default values
    args = _parse_args()
    client_id = str(uuid.uuid4())
    # create a structure to store the information
    debug_info = {'geoip': dict(),
                  'popLatency': dict(),
                  'popAssignments': dict(),
                  'request': dict()}
    # Lets start filling in those data points
    perfmap = fetch_perfmap(client_id, debug=args.debug)
    debug_info['geoip'] = perfmap['geo_ip']
    debug_info['popLatency'] = fetch_latencies(perfmap['pops'], client_id, debug=args.debug)
    debug_info['popAssignments'] = fetch_pops(hosts=perfmap['domains'], debug=args.debug)
    debug_info['request'] = fetch_resolver(client_id, debug=args.debug)

    # Now lets stringify and output that data
    debug_json = json.dumps(debug_info, indent=2)
    send_out(debug_json, args.quiet, args.out)
