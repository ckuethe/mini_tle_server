#!/usr/bin/env python
# vim: tabstop=4:softtabstop=4:shiftwidth=4:expandtab:

from __future__ import print_function

import os
import re
import sqlite3
from argparse import ArgumentParser
from ephem import readtle
from math import pi, degrees
from requests import get as wget
from tempfile import mkstemp
from zipfile import ZipFile


# From https://physics.stackexchange.com/questions/113300/why-does-earth-have-a-minimum-orbital-period
# Assuming for a sec that there was no atmosphere, and the earth is a perfectly
# smooth sphere with a radius of 6378km and we're orbiting just above the surface,
# we can calculate that the minimum orbital period is about 84.47 minutes
minimum_period = 84.47

# we seem to think of 60 miles / 100km as "space" ... that's the altitude where you
# get your astronaut wings. The thermosphere is from 80-500km altitude, and below
# about 160km a satellite in a *circular* orbit can interact with enough of this
# thin atmosphere to rapidly decay. Highly elliptical orbits are quite different.
#
# Some photoreconnaissance satellites had a perigee as low as 152km, Molniya
# orbits can come closer - about 120km
minimum_orbit = 100

# Perhaps I should use the python-sgp4 checksum fixer...
tle_line_length = 69

def readzip(zip_archive, file_name):
    '''read a file from a zip archive'''
    buf = ''
    with ZipFile(zip_archive) as zf:
        with zf.open(file_name) as zfd:
            buf = zfd.read()
    return buf

def readfile(fn, mode='rb'):
    '''read the contents of a file'''
    with open(fn, mode) as fd:
        return fd.read()

def fetch(args, url, headers=None):
    '''download a file'''
    fname = os.path.basename(url)
    if not os.path.exists(fname) or args.refetch is True:
        if headers is None:
            headers = {}
        with wget(url, timeout=5, stream=True, headers=headers) as resp:
            if resp.ok:
                (tempfd, tempfn) = mkstemp(dir='.', prefix='tmp')
                with open(tempfn, 'wb') as fd:
                    for chunk in resp.iter_content(chunk_size=32768):
                        if chunk:
                            fd.write(chunk)
                os.rename(tempfn, fname)

            else:
                print('URL {} failed: {}\n{}'.format(url, resp.status_code, resp.content))

    if args.do_print:
        print('file {}, size {}'.format(fname, os.path.getsize(fname)))

def check_violated_constraints(r):
    bad_checks = []
    if r['norad_catalog'] <= 0:
        bad_checks.append("norad_catalog")
    if not (6<= len(r['intldes']) <=8):
        bad_checks.append("intldes")
    if not (-180 <= r['inclination'] <=180):
        bad_checks.append("inclination")
    if r['classified'] not in [0, 1]:
        bad_checks.append('classified')
    if r['apogee'] < minimum_orbit:
        bad_checks.append('apogee')
    if r['perigee'] < minimum_orbit:
        bad_checks.append('perigee')
    if r['period'] < minimum_period:
        bad_checks.append('period')
    if r['mean_motion'] <= 0.0:
        bad_checks.append('mean_motion')
    if r['eccentricity'] < 0.0:
        bad_checks.append('eccentricity')
    if r['semimajor_axis'] < 0.0:
        bad_checks.append('semimajor_axis')
    if len(r['line1']) != tle_line_length:
        bad_checks.append('line1')
    if len(r['line2']) != tle_line_length:
        bad_checks.append('line2')
    if bad_checks == []:
        bad_checks.append('UNIQUE')
    return bad_checks

def dbinit(args):
    '''initialize a database connection'''
    create_table_sql = '''
      CREATE TABLE "tles" (
        "norad_catalog"   INTEGER NOT NULL CHECK(norad_catalog>0) UNIQUE,
        "classified"      INTEGER NOT NULL DEFAULT 0 CHECK(classified==0 or classified==1),
        "inclination"     REAL NOT NULL CHECK(inclination>=-180 and inclination <=180),
        "period"          REAL NOT NULL CHECK(period>={0}),
        "apogee"          REAL NOT NULL CHECK(apogee>={1} or perigee>={1}),
        "perigee"         REAL NOT NULL CHECK(apogee>={1} or perigee>={1}),
        "mean_motion"     REAL NOT NULL CHECK(mean_motion>0),
        "eccentricity"    REAL NOT NULL CHECK(eccentricity>=0),
        "semimajor_axis"  REAL NOT NULL CHECK(semimajor_axis>=0),
        "epoch"           TIMESTAMP NOT NULL,
        "intldes"         VARCHAR(8)  NOT NULL CHECK(length(intldes)>=6 and length(intldes)<=8) UNIQUE,
        "name"            VARCHAR(80) NOT NULL DEFAULT "",
        "line1"           TEXT NOT NULL CHECK(length(line1)=={2}),
        "line2"           TEXT NOT NULL CHECK(length(line2)=={2}),
        PRIMARY KEY("norad_catalog")
    ) WITHOUT ROWID;

      CREATE INDEX ix_name ON tles (name);
      CREATE INDEX ix_intldes ON tles (intldes);
      CREATE INDEX ix_classified ON tles (classified);
      CREATE INDEX ix_eccentricity ON tles (eccentricity);
      CREATE INDEX ix_perigee ON tles (perigee);
      CREATE INDEX ix_apogee ON tles (apogee);
      CREATE INDEX ix_period ON tles (period);
      CREATE INDEX ix_mean_motion ON tles (mean_motion);
      CREATE INDEX ix_inclination ON tles (inclination);
      CREATE INDEX ix_semimajor_axis ON tles (semimajor_axis);
      CREATE INDEX ix_epoch ON tles (epoch);
    '''.format(minimum_period, minimum_orbit, tle_line_length)

    dbh = sqlite3.connect(args.database)
    dbh.row_factory = sqlite3.Row
    if args.initdb:
        dbh.execute('drop table if exists tles')

    try:
        dbh.executescript(create_table_sql)
    except sqlite3.OperationalError:
        if args.do_print:
            print("database exists; not reinitializing")
        pass
    return dbh

def orbital_properties(n, e):
    '''Compute some nice orbital metadata

    Slightly modified from space-track.org FAQ:

    We added semi-major axis, period, apogee, and perigee to the TLE and TLE_latest
    API classes so that users can filter their queries by these values, download
    only the data they need, and decrease the amount of the site's bandwidth that
    they use. Now, all the orbital elements in the satellite catalog (SATCAT) are
    available in the TLE class. However, the value of the same element (e.g.
    apogee) may not match exactly.

    Every TLE already displays a value for the object's mean motion ("n") and
    eccentricity ("e"), so we derive these additional four values using the
    following calculations:

    period = 1440/n
    Using mu, the standard gravitational parameter for the earth (398600.4418),
    semi-major axis "a" = (mu/(n*2*pi/(24*3600))^2)^(1/3)
    Using semi-major axis "a", eccentricity "e", and the Earth's radius in km,
    apogee = (a * (1 + e))- 6378.135
    perigee = (a * (1 - e))- 6378.135
    '''

    earth_radius = 6378.135
    mu = 398600.4418
    seconds_per_day = 86400.0
    minutes_per_day = seconds_per_day / 60.0

    semimajor_axis = (mu/(n * 2.0 * pi / seconds_per_day) ** 2 ) ** (1.0/3.0)
    apogee = (semimajor_axis * (1 + e)) - earth_radius
    perigee = (semimajor_axis * (1 - e)) - earth_radius
    period = minutes_per_day / n

    return (semimajor_axis, apogee, perigee, period)

def build_record(tle, classified):
    '''build a record to insert into the database'''
    es = readtle(*tle)
    semimajor_axis, apogee, perigee, period = orbital_properties(es._n, es._e)
    intldes = tle[1][9:17].strip()
    return {
        'norad_catalog': es.catalog_number,
        'intldes': intldes,
        'name': es.name,
        'classified': classified,
        'inclination': degrees(es._inc),
        'mean_motion': es._n,
        'period': period,
        'eccentricity': es._e,
        'semimajor_axis': semimajor_axis,
        'epoch': es._epoch.datetime(),
        'apogee': apogee,
        'perigee': perigee,
        'line1': tle[1].strip(),
        'line2': tle[2].strip()
    }


def dbinsert(dbh, tle, classified=False, update=False, do_print=False):
    '''insert a record into the database'''
    rec = build_record(tle, classified)
    rv = True
    columns = ', '.join(rec.keys())
    placeholders = ':'+', :'.join(rec.keys())
    u = ""
    if update:
        u = "OR REPLACE"
    sql = 'INSERT %s INTO tles (%s) VALUES (%s)' % (u, columns, placeholders)
    try:
        dbh.execute(sql, rec)
    except sqlite3.IntegrityError:
        if do_print:
            print("error inserting {}/{}/{}".format(rec['name'], rec['norad_catalog'], rec['intldes']))
            print("constraints: ", check_violated_constraints(rec))
            print(rec)
        rv = False
    return (rv, rec['name'], rec['norad_catalog'], rec['intldes'])

def do_download(args):
    '''download the datafiles'''
    fake_hdr = {
        'Referer': 'https://tle.info/joomla/index.php',
        'User-Agent': 'Wget/1.71.1 (linux-gnu)',
        'Accept-Encoding': 'identity',
    }

    fetch(args, 'https://www.prismnet.com/~mmccants/tles/classfd.zip')
    fetch(args, 'https://www.tle.info/data/ALL_TLE.ZIP', fake_hdr)

def load_compressed_tle(args, archive, member, dbh, classified=0):
    '''extract the named member from a zip archive, parse out the TLE entries, and load them into the database'''
    buf = readzip(archive, member)
    tles = {}
    for sat in re.findall('(?P<name>^.+?\n)?(?P<line1>^1 .+?)\n(?P<line2>^2 .+?)\n', buf, re.MULTILINE):
        tles[sat[0].strip()] = (sat[0].strip(), sat[1], sat[2])

    if args.do_print:
        print("file {} contains {} TLEs".format(member, len(tles)))

    for sat in tles:
        dbinsert(dbh, tles[sat], classified, update=args.update, do_print=args.do_print)

    dbh.commit()

def main():
    ap = ArgumentParser()
    ap.add_argument('-d', '--database', dest='database', default='tles.sqlite')
    ap.add_argument('-i', '--initdb', dest='initdb', default=False, action='store_true')
    ap.add_argument('-r', '--refetch', dest='refetch', default=False, action='store_true')
    ap.add_argument('-u', '--update', dest='update', default=False, action='store_true')
    ap.add_argument('-q', '--quiet', dest='do_print', default=True, action='store_false')
    args = ap.parse_args()

    dbh = dbinit(args)

    do_download(args)

    load_compressed_tle(args, 'ALL_TLE.ZIP', 'ALL_TLE.TXT', dbh)
    load_compressed_tle(args, 'classfd.zip', 'classfd.tle', dbh, classified=1)

    r = dbh.execute('select count(*) from tles')
    n = r.fetchone()['count(*)']
    print("database contains ", n, " records")

if __name__ == '__main__':
    main()
