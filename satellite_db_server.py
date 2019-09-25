#!/usr/bin/env python
# coding: utf-8
# vim: tabstop=4:softtabstop=4:shiftwidth=4:expandtab:

from __future__ import print_function
from flask import Flask, jsonify, request, make_response, abort
import argparse
import sqlite3
import urllib
from ephem import readtle
from satellite_db_loader import dbinsert, build_record

app = Flask(__name__)
args = None
search_params = [
    'name',
    'norad_catalog',
    'intldes',
    'classified',
    'inclination',
    'mean_motion',
    'period',
    'epoch',
    'eccentricity',
    'apogee',
    'perigee',
    'semimajor_axis',
]
search_params.sort()

search_ops = {
    'eq': '= ?',
    'gt': '> ?',
    'lt': '< ?',
    'ge': '>= ?',
    'le': '<= ?',
    'in': 'between ? and ?',
}

for op in search_ops.keys():
    search_ops['n{}'.format(op)] = search_ops[op]

@app.errorhandler(403)
def http_forbidden(error):
    return make_response(jsonify({'error': 'Permission Denied'}), 403)

@app.errorhandler(404)
def http_not_found(error):
    return make_response(jsonify({'error': 'Not Found'}), 404)

@app.errorhandler(405)
def http_not_allowed(error):
    return make_response(jsonify({'error': 'Method Not Allowed'}), 405)

@app.errorhandler(406)
def http_not_acceptable(error):
    return make_response(jsonify({'error': 'Not Acceptable'}), 406)

@app.errorhandler(409)
def http_conflict(error):
    return make_response(jsonify({'error': 'Conflict'}), 409)

@app.errorhandler(410)
def http_gone(error):
    return make_response(jsonify({'error': 'Gone'}), 410)

def index():
    endpoints = {
        '/': {'descr': 'this page'},
        '/schema': {'descr': 'GET database schema'},
        '/count': {'descr': 'count number of entries in the database'},
        '/add': {'descr': 'POST a new TLE, or update the TLE for an existing object'},
        '/delete': {
            'descr': 'DELETE a satelite',
            'syntax': ['/delete/intldes/<id>', '/delete/norad_catalog/<id>']
            },
        '/search': {
            'descr': 'GET TLE search results',
            'column': search_params,
            'op': search_ops.keys(),
            'syntax': ['/search/<column>/<op>/<equals_value>', '/search/<column>/<op>/<start_value>/<end_value>' ],
            },
        '/range': {
            'descr': 'GET the range of values in a column',
            'column': search_params,
            'syntax':['/range', '/range/<column>']},
    }
    return jsonify(endpoints)


@app.route('/', methods=['GET'])
@app.route('/help', methods=['GET'])
@app.route('/list', methods=['GET'])
def list_routes():
    '''List the routes known to this app, and print their docstrings'''
    namespace = __import__(__name__)
    routes = []
    # https://stackoverflow.com/questions/13317536/get-list-of-all-routes-defined-in-the-flask-app
    for rule in app.url_map.iter_rules():
        func_name = rule.endpoint
        path = str(rule)

        # We don't support /static
        if func_name == 'static':
            continue

        # If the server is not in writable mode don't advertise these
        if args.update is False:
            if path in ['/add', '/delete', '/update']:
                continue
        rule_doc = getattr(namespace, func_name).func_doc
        line = {'handler': func_name, 'path': str(rule), 'help':rule_doc.format(search_ops.keys()).strip()}
        routes.append(line)

    # this achieves the effect of sorting the output by handler then by path,
    # for handlers that can take variable numbers of args, such as /search
    routes.sort(key=lambda x: x['path'])
    routes.sort(key=lambda x: x['handler'])
    return jsonify(routes)


@app.route('/add', methods=['GET', 'POST'])
@app.route('/add/classified', methods=['GET', 'POST'])
def add_tle():
    ''''POST /add' requires 'application/json' containing a 3 element list containing: ['object name', 'tle line 1', 'tle line 2']\nIt will fail with error code 403 if the server is not writable. It will fail with error code 409 if a TLE for the norad or international catalog id already exists. if the '/classified' suffix is given, the classified attribute will be set in the database
    '''

    if args.update is False:
        abort(403)

    if request.headers.get('Content-Type', '') != 'application/json':
        abort(406)

    if request.method != 'POST':
        # allow this route to receive GET requests, just so I can return a help message.
        # this TLE came from NASA which, as far as I can tell, has no redistribution
        # restrictions... unlike JSPOC-originated TLEs.
        # https://spaceflight.nasa.gov/realdata/sightings/SSapplications/Post/JavaSSOP/orbit/ISS/SVPOST.html
        iss = [
            'ISS',
            '1 25544U 98067A   19128.56248153  .00016717  00000-0  10270-3 0  9002',
            '2 25544  51.6390 198.1271 0001239 315.7000  44.4052 15.52641749  9097',
            ]
        return make_response(jsonify({'error': 'Method Not Allowed', 'help': 'POST a TLE as a 3-element JSON list', 'tle_example': iss}), 405)

    tle = [str(x) for x in request.json]
    classified = request.path.endswith('classified')
    with sqlite3.connect(args.database) as dbh:
        try:
            resp = dbinsert(dbh, tle, classified, False)
        except ValueError:
            # probably a badly formatted TLE
            abort(406)

        if resp[0] is False:
            abort(409)
        return jsonify({'name': resp[1], 'norad_catalog': resp[2], 'intldes': resp[3], 'classified': classified})


@app.route('/delete/norad_catalog/<idnum>', methods=['DELETE'])
@app.route('/delete/intldes/<idnum>', methods=['DELETE'])
def delete_tle(idnum):
    ''''DELETE /delete/<catalog>/<id>' deletes the specified\nIt will fail with error code 403 if the server is not writable. It will fail with error code 410 if a TLE for the norad or international catalog id does not exist.
    '''

    if args.update is False:
        abort(403)

    if request.headers.get('Content-Type', '') != 'application/json':
        abort(406)

    catalog = 'intldes' if 'intldes' in request.path else 'norad_catalog'
    with sqlite3.connect(args.database) as dbh:
        dbh.row_factory = sqlite3.Row
        r = dbh.execute('DELETE FROM tles WHERE {} = ?'.format(catalog), (idnum,))
        if r.rowcount:
            return jsonify({'status': 'ok', 'catalog': catalog, 'id': idnum})
        else:
            abort(410)


@app.route('/count', methods=['GET'])
def count():
    ''''GET /count' returs the number of records present'''
    with sqlite3.connect(args.database) as dbh:
        dbh.row_factory = sqlite3.Row
        r = dbh.execute('select count(*) from tles')
        return jsonify({'count': r.fetchone()['count(*)'] })


@app.route('/columns', methods=['GET'])
def columns():
    '''GET /columns' returns a list of columns which can be searched'''
    return jsonify(search_params)


@app.route('/range', methods=['GET'])
def range_all():
    '''GET /range' returns the range of each column in the database'''
    with sqlite3.connect(args.database) as dbh:
        rv = {}
        dbh.row_factory = sqlite3.Row
        for column in search_params:
            r = dbh.execute('select MIN({0}) as A, MAX({0}) as B from tles'.format(column)).fetchone()
            rv[column] = { 'min': r['A'], 'max': r['B']}
        return jsonify(rv)


@app.route('/range/<column>', methods=['GET'])
def range_col(column=None):
    '''GET /range/<column>' returns the range of the specified column'''
    if column not in search_params:
        return jsonify({'error': True, 'message': 'column not in allowed set', 'allowed': search_params})

    with sqlite3.connect(args.database) as dbh:
        dbh.row_factory = sqlite3.Row
        r = dbh.execute('select MIN({0}) as A, MAX({0}) as B from tles'.format(column)).fetchone()
        #return jsonify({'field': column, 'min': r['A'], 'max': r['B']})
        return jsonify( {column: {'min': r['A'], 'max': r['B']}} )


@app.route('/schema', methods=['GET'])
def schema():
    ''''GET /schema' returns the sqlite schema used to construct the database.'''
    with sqlite3.connect(args.database) as dbh:
        dbh.row_factory = sqlite3.Row
        c = dbh.execute('select sql from sqlite_master where type = "table" and tbl_name = "tles"')
        r = c.fetchone()
        return jsonify({'sql': r['sql']})


@app.route('/search/<column>/<op>/<v1>', methods=['GET'])
@app.route('/search/<column>/<op>/<v1>/<v2>', methods=['GET'])
def search(column=None, op=None, v1=None, v2=None):
    ''''GET /search/<column>/<op>/...' returns results from comparing <column> using the <op> with <v1> and <v2> if necessary. Operators are {}; the 'n' are negated/inverted'''

    op = op.lower()
    column = column.lower()

    if column not in search_params:
        abort(406)

    if op not in search_ops:
        abort(406)

    if v1 is None:
        abort(406)

    if v2 is not None and op not in ['in', 'nin']:
        # v2 only makes sense for the 'in'/'nin' operators
        abort(406)

    if op.startswith('n'):
        negate = 'not'
    else:
        negate = ''

    with sqlite3.connect(args.database) as dbh:
        dbh.row_factory = sqlite3.Row
        if op.endswith('eq') and ('%' in v1 or '_' in v1) :  # sqlite wildcards
            q = 'SELECT * FROM tles WHERE {0} {1} LIKE ? ORDER BY {0}'.format(column, negate)
            c = dbh.execute(q, [v1]) # i hate you sqlite. a string of length N is treated like an N element vector?! WTF!

        elif op.endswith('in'):
            q = 'SELECT * FROM tles WHERE {0} {1} BETWEEN ? AND ? ORDER BY {0}'.format(column, negate)
            if v2 is None:
                v2 = v1
            if v1 > v2:
                v1, v2 = v2, v1 # i <3 python
            c = dbh.execute(q, (v1, v2))

        else:
            q = 'select * from tles where {0} {1} {2} ORDER BY {0}'.format(column, negate, search_ops[op])
            c = dbh.execute(q, [v1]) # i hate you sqlite. a string of length N is treated like an N element vector?! WTF!

        return jsonify({'result': [dict(x) for x in c.fetchall()]})

if __name__ == '__main__':
    ap = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('-d', '--debug', dest='debug', default=False,
                    action='store_true', help='run server in debug mode')
    ap.add_argument('-w', '--writable', dest='update', default=False,
                    action='store_true', help='allow write api operations')
    ap.add_argument('-f', '--database', dest='database', default='tles.sqlite',
                    metavar='FILE', help='database file')
    ap.add_argument('-l', '--listen', dest='listen',
                    default='127.0.0.1', metavar='ADDR', help='bind address')
    ap.add_argument('-p', '--port', dest='port', default=4853,
                    help='listen port') # spells 4TLE on a phone keypad
    args = ap.parse_args()

    if args.update:
        print("CAUTION: database is writable")
    app.run(debug=args.debug, port=args.port, host=args.listen)
