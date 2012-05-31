.PHONY: all

all: xtx/TIMESTAMP xtx/locations.xtx

xtx/TIMESTAMP: dblp.xml dblpparse.py  latex.py  locations.py  overrides.py  parentheticals.py
	python dblpparse.py

xtx/locations.xtx: locations.py
	python locations.py

dblp.xml:
	wget http://dblp.uni-trier.de/xml/dblp.xml.gz
	gunzip dblp.xml.gz
