
# mini_tle_server

From time to time it would be nice to retrieve TLEs over the network, possibly as the result of a search/query.
This little tool does that.

## Loader Usage

```
usage: satellite_db_loader.py [-h] [-d DATABASE] [-i] [-r] [-u] [-q]

optional arguments:
  -h, --help                        show this help message and exit
  -d DATABASE, --database DATABASE  database file (default: tles.sqlite)
  -i, --initdb                      initialize the database (default: False)
  -r, --refetch                     download new datafiles (default: False)
  -u, --update                      update database records (default: False)
  -q, --quiet
```

## Server Usage

```
usage: satellite_db_server.py [-h] [-d] [-w] [-f FILE] [-l ADDR] [-p PORT]

optional arguments:
  -h, --help                 show this help message and exit
  -d, --debug                run server in debug mode (default: False)
  -w, --writable             allow write api operations (default: False)
  -f FILE, --database        FILE database file (default: tles.sqlite)
  -l ADDR, --listen ADDR     bind address (default: 127.0.0.1)
  -p PORT, --port PORT       listen port (default: 4853) 
```

## Endpoints

Here is a list of the endpoints available from the TLE server.
Similar output is available by retrieving `/`, `/help`, or `/list` endpoints.

### /add

`POST /add'` requires a JSON payload containing a 3 element list containing: `['object name', 'tle line 1', 'tle line 2']`
It will fail with error code 403 if the server is not writable.
It will fail with error code 409 if a TLE for the norad or international catalog id already exists.

### /columns

`GET /columns` returns a list of columns which can be searched

### /count

`GET /count` returns the number of records present

### /delete/&lt;catalog&gt;/&lt;id&gt;

`DELETE /delete/<catalog>/<id>` deletes the specified TLE. The catalog must be one of `intldes` or `norad_catalog`.
It will fail with error code 403 if the server is not writable.
It will fail with error code 410 if a TLE for the norad or international catalog id does not exist.

### /range

`GET /range` returns the range of each column in the database

### /range/&lt;column&gt;

`GET /range/<column>` returns the range of the specified column

### /schema

`GET /schema` returns the sqlite schema used to construct the database.

### /search

`GET /search/<column>/<op>/...` returns results from comparing <column> using the <op> with <v1> (and <v2> if necessary).
Operators are [`nge`, `le`, `nin`, `nlt`, `ge`, `ngt`, `lt`, `gt`, `nle`, `in`, `eq`, `neq`]; the `n` are negated/inverted.  
