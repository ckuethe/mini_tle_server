#!/bin/bash

CURL="curl -H Content-Type:application/json"
SRV='localhost:4853'

set -x

$CURL -XGET ${SRV}/
$CURL -XGET ${SRV}/help
$CURL -XGET ${SRV}/list

$CURL -XGET ${SRV}/schema
$CURL -XGET ${SRV}/columns
$CURL -XGET ${SRV}/range
$CURL -XGET ${SRV}/range/intldes

$CURL -XGET ${SRV}/search/name/eq/starlink%
$CURL -XGET ${SRV}/search/norad_catalog/in/44000/45000
$CURL -XGET ${SRV}/search/intldes/eq/19029%

$CURL -XPOST -d "@iss.json" ${SRV}/add
$CURL -XPOST -d "@iss.json" ${SRV}/add/classified
$CURL -XPOST -d '[ "this", "will", "fail" ]' ${SRV}/add/classified

#$CURL -XGET ${SRV}/delete/norad_catalog/16
#$CURL -XDELETE ${SRV}/delete/norad_catalog/16
