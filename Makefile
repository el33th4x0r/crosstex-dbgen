.PHONY: all xtx install install-local install-global

all:
	@echo "Commonly used rules"
	@echo "    xtx      rebuild the xtx/* output from the latest dblp.xml (fetch it if not exist)"
	@echo "    install  install the xtx files to ~/.crosstex"
	@echo "    install-global"
	@echo "             install the xtx files to /usr/local/share/crosstex"
	@echo "    clean    remove the generated locations.xtx and xtx/TIMESTAMP"
	@echo "    clobber  remove the inputs so \"xtx\" will re-download dblp.xml (implies \"clean\")"
	@echo "    dblp.xml.gz"
	@echo "             redownload the dblp.xml file"

xtx: xtx/TIMESTAMP

pre-wipe:
	rm xtx/*

xtx/TIMESTAMP: dblp.xml dblp.dtd dblpparse.py latex.py pre-wipe xtx/locations.xtx  overrides.py  parentheticals.py
	python dblpparse.py

xtx/locations.xtx: locations.py
	python locations.py

dblp.dtd:
	wget -Nq http://dblp.uni-trier.de/xml/dblp.dtd

dblp.xml.gz:
	wget -N http://dblp.uni-trier.de/xml/dblp.xml.gz

dblp.xml: dblp.xml.gz
	gunzip -c $< > $@

install: install-local

install-local:
	mkdir -p ${HOME}/.crosstex
	cp xtx-static/*.xtx ${HOME}/.crosstex
	cp xtx-todo/*.xtx ${HOME}/.crosstex
	cp xtx/*.xtx ${HOME}/.crosstex

install-global:
	mkdir -p /usr/local/share/crosstex
	cp xtx-static/*.xtx /usr/local/share/crosstex
	cp xtx-todo/*.xtx /usr/local/share/crosstex
	cp xtx/*.xtx /usr/local/share/crosstex

clean:
	rm -f xtx/TIMESTAMP xtx/locations.xtx

clobber: clean
	rm -f dblp.xml dblp.xml.gz dblp.dtd
