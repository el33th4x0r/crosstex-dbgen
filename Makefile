.PHONY: all

all: xtx/TIMESTAMP xtx/locations.xtx

xtx/TIMESTAMP: dblp.xml dblp.dtd dblpparse.py  latex.py  xtx/locations.xtx  overrides.py  parentheticals.py
	python dblpparse.py

xtx/locations.xtx: locations.py
	python locations.py

dblp.dtd:
	wget -Nq http://dblp.uni-trier.de/xml/dblp.dtd

dblp.xml:
	wget -N http://dblp.uni-trier.de/xml/dblp.xml.gz
	gunzip dblp.xml.gz

clean:
	rm -f dblp.dtd

clobber: clean
	rm -f dblp.xml dblp.xml.gz dblp.dtd

