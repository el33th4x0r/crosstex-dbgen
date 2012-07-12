.PHONY: all

all: xtx/TIMESTAMP xtx/locations.xtx

xtx/TIMESTAMP: dblp.xml dblpparse.py  latex.py  xtx/locations.xtx  overrides.py  parentheticals.py
	python dblpparse.py

xtx/locations.xtx: locations.py
	python locations.py

dblp.xml:
	wget http://dblp.uni-trier.de/xml/dblp.xml.gz
	gunzip dblp.xml.gz
	wget http://dblp.uni-trier.de/xml/dblp.dtd

clobber:
	rm -f dblp.xml dblp.xml.gz dblp.dtd
