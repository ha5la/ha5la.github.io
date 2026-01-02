#!/bin/sh

set -uex

pngquant -o "$2" "$1"
pngcrush -brute -ow "$2"
